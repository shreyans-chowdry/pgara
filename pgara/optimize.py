"""Machine-independent optimisation of SSA-form TAC.

Passes (iterated to a fixpoint by `optimize_function`):
  * SCCP   - sparse conditional constant propagation (Wegman & Zadeck),
             which also folds branches on constants and removes the blocks
             it proves unreachable;
  * copy propagation and trivial-phi elimination;
  * algebraic simplification and strength reduction (x*2 -> x+x, ...);
  * GVN    - dominator-scoped hash-based global value numbering (common
             subexpression elimination for pure instructions);
  * DCE    - mark-and-sweep dead-code elimination from side effects;
  * CFG cleanup - merging straight-line block pairs.
Finally, branches on a single-use comparison are fused into compare-and-
branch (`cbr`) instructions.
"""

from .cfg import dominators, dom_tree, remove_unreachable, split_critical_edges
from .ir import (Instr, BINOPS, UNOPS, RELOPS, COMMUTATIVE, PURE, SIDE_EFFECTS,
                 eval_binop, eval_unop, RuntimeFault)

TOP = ("top",)
BOTTOM = ("bottom",)


def _meet(a, b):
    if a is TOP:
        return b
    if b is TOP:
        return a
    if a is BOTTOM or b is BOTTOM:
        return BOTTOM
    return a if a == b else BOTTOM


def sccp(fn):
    bm = fn.block_map()
    value = {}
    uses = {}
    def_site = {}
    for b in fn.blocks:
        for ins in b.instrs:
            if ins.dst is not None:
                value[ins.dst] = TOP
                def_site[ins.dst] = (b.name, ins)
            for u in ins.uses():
                uses.setdefault(u, []).append((b.name, ins))

    def val(x):
        return x if isinstance(x, int) else value.get(x, BOTTOM)

    exec_edges = set()
    exec_blocks = set()
    flow = [(None, fn.blocks[0].name)]
    ssa = []

    def evaluate(bname, ins):
        op = ins.op
        if op == "phi":
            out = TOP
            for p, v in ins.phi.items():
                if (p, bname) in exec_edges:
                    out = _meet(out, val(v))
            return out
        if op in ("const", "copy"):
            return val(ins.args[0])
        if op in BINOPS:
            a, b = val(ins.args[0]), val(ins.args[1])
            if isinstance(a, int) and isinstance(b, int):
                try:
                    return eval_binop(op, a, b)
                except RuntimeFault:
                    return BOTTOM
            if (op == "mul" and (a == 0 or b == 0)):
                return 0
            if a is BOTTOM or b is BOTTOM:
                return BOTTOM
            return TOP
        if op in UNOPS:
            a = val(ins.args[0])
            if isinstance(a, int):
                return eval_unop(op, a)
            return a
        return BOTTOM

    def visit_terminator(bname, ins):
        if ins.op == "jmp":
            flow.append((bname, ins.targets[0]))
        elif ins.op == "br":
            c = val(ins.args[0])
            if isinstance(c, int):
                flow.append((bname, ins.targets[0] if c != 0 else ins.targets[1]))
            elif c is BOTTOM:
                flow.extend((bname, t) for t in ins.targets)
        elif ins.op == "cbr":
            a, b = val(ins.args[0]), val(ins.args[1])
            if isinstance(a, int) and isinstance(b, int):
                flow.append((bname, ins.targets[0] if eval_binop(ins.relop, a, b) else ins.targets[1]))
            elif a is BOTTOM or b is BOTTOM:
                flow.extend((bname, t) for t in ins.targets)

    def visit(bname, ins):
        if ins.dst is not None:
            new = evaluate(bname, ins)
            if new != value[ins.dst]:
                value[ins.dst] = new
                ssa.extend(uses.get(ins.dst, []))
        if ins.is_terminator():
            visit_terminator(bname, ins)

    while flow or ssa:
        while flow:
            edge = flow.pop()
            if edge in exec_edges:
                continue
            exec_edges.add(edge)
            target = edge[1]
            block = bm[target]
            first_visit = target not in exec_blocks
            exec_blocks.add(target)
            if first_visit:
                for ins in block.instrs:
                    visit(target, ins)
            else:
                for ins in block.phis():
                    visit(target, ins)
        while ssa:
            bname, ins = ssa.pop()
            if bname in exec_blocks:
                visit(bname, ins)

    changes = 0
    consts = {v: c for v, c in value.items() if isinstance(c, int)}
    # Rewrite: substitute constants, fold decided branches, drop dead edges.
    for b in fn.blocks:
        if b.name not in exec_blocks:
            continue
        new_instrs = []
        for ins in b.instrs:
            if ins.dst in consts and ins.op != "call" and ins.op != "input":
                changes += 1
                continue
            before = (list(ins.args), dict(ins.phi))
            ins.replace_uses(consts)
            if (list(ins.args), dict(ins.phi)) != before:
                changes += 1
            if ins.op in ("br", "cbr"):
                live_targets = [t for t in ins.targets if (b.name, t) in exec_edges]
                if len(set(live_targets)) == 1:
                    new_instrs.append(Instr("jmp", targets=[live_targets[0]], line=ins.line))
                    changes += 1
                    continue
            new_instrs.append(ins)
        b.instrs = new_instrs
    # Phi entries for edges that never execute are removed.
    for b in fn.blocks:
        for phi in b.phis():
            for p in list(phi.phi):
                if (p, b.name) not in exec_edges:
                    del phi.phi[p]
    fn.recompute_edges()
    removed = remove_unreachable(fn)
    for b in fn.blocks:
        for phi in b.phis():
            for p in list(phi.phi):
                if p not in b.preds:
                    del phi.phi[p]
    return changes + len(removed)


def substitute(fn, mapping):
    if not mapping:
        return
    # Resolve chains a -> b -> c.
    def resolve(v):
        seen = set()
        while isinstance(v, str) and v in mapping and v not in seen:
            seen.add(v)
            v = mapping[v]
        return v
    flat = {k: resolve(k) for k in mapping}
    for b in fn.blocks:
        for ins in b.instrs:
            ins.replace_uses(flat)


def copy_propagation(fn):
    mapping = {}
    for b in fn.blocks:
        keep = []
        for ins in b.instrs:
            if ins.op in ("copy", "const") and ins.dst is not None:
                mapping[ins.dst] = ins.args[0]
                continue
            if ins.op == "phi":
                vals = {v for v in ins.phi.values() if v != ins.dst}
                if len(vals) == 1:
                    mapping[ins.dst] = vals.pop()
                    continue
                if not vals:
                    mapping[ins.dst] = 0
                    continue
            keep.append(ins)
        b.instrs = keep
    substitute(fn, mapping)
    return len(mapping)


def simplify(fn):
    """Algebraic identities and strength reduction."""
    changes = 0
    for b in fn.blocks:
        for idx, ins in enumerate(b.instrs):
            op = ins.op
            if op not in BINOPS:
                continue
            x, y = ins.args
            new = None
            if op == "add":
                if y == 0:
                    new = ("copy", [x])
                elif x == 0:
                    new = ("copy", [y])
            elif op == "sub":
                if y == 0:
                    new = ("copy", [x])
                elif x == y:
                    new = ("const", [0])
                elif x == 0:
                    new = ("neg", [y])
            elif op == "mul":
                if y == 1:
                    new = ("copy", [x])
                elif x == 1:
                    new = ("copy", [y])
                elif x == 0 or y == 0:
                    new = ("const", [0])
                elif y == 2:
                    new = ("add", [x, x])
                elif x == 2:
                    new = ("add", [y, y])
                elif y == -1:
                    new = ("neg", [x])
            elif op == "div":
                if y == 1:
                    new = ("copy", [x])
            elif op == "mod":
                if y == 1 or y == -1:
                    new = ("const", [0])
            elif op in RELOPS and x == y and isinstance(x, str):
                new = ("const", [1 if op in ("le", "ge", "eq") else 0])
            if new is not None:
                ins.op, ins.args = new
                changes += 1
    return changes


def gvn(fn):
    idom = dominators(fn)
    tree = dom_tree(idom)
    bm = fn.block_map()
    mapping = {}
    removed = 0

    def key_of(ins):
        args = [mapping.get(a, a) if isinstance(a, str) else a for a in ins.args]
        if ins.op in COMMUTATIVE:
            args = sorted(args, key=lambda v: (isinstance(v, str), str(v)))
        if ins.op in ("addr",):
            return ("addr", ins.sym)
        if ins.op == "param":
            return ("param", ins.args[0])
        return (ins.op, tuple(args))

    def walk(bname, table):
        nonlocal removed
        scope = dict(table)
        keep = []
        for ins in bm[bname].instrs:
            ins.replace_uses(mapping)
            if ins.op in PURE and ins.op not in ("const", "copy") and ins.dst is not None:
                k = key_of(ins)
                if k in scope:
                    mapping[ins.dst] = scope[k]
                    removed += 1
                    continue
                scope[k] = ins.dst
            keep.append(ins)
        bm[bname].instrs = keep
        for child in tree[bname]:
            walk(child, scope)

    walk(fn.blocks[0].name, {})
    substitute(fn, mapping)
    return removed


def dce(fn):
    defs = {}
    for b in fn.blocks:
        for ins in b.instrs:
            if ins.dst is not None:
                defs[ins.dst] = ins
    live = set()
    work = []
    for b in fn.blocks:
        for ins in b.instrs:
            if ins.op in SIDE_EFFECTS:
                work.append(ins)
    marked = set()
    while work:
        ins = work.pop()
        if id(ins) in marked:
            continue
        marked.add(id(ins))
        for u in ins.uses():
            if u not in live:
                live.add(u)
                if u in defs:
                    work.append(defs[u])
    removed = 0
    for b in fn.blocks:
        keep = []
        for ins in b.instrs:
            if id(ins) in marked:
                if ins.op in ("call", "input") and ins.dst is not None and ins.dst not in live:
                    if ins.op == "call":
                        ins.dst = None
                keep.append(ins)
            else:
                removed += 1
        b.instrs = keep
    return removed


def merge_blocks(fn):
    """Merge B into its unique predecessor P when P's only successor is B."""
    merged = 0
    changed = True
    while changed:
        changed = False
        bm = fn.block_map()
        for b in fn.blocks[1:]:
            if len(b.preds) != 1:
                continue
            p = bm[b.preds[0]]
            if len(p.succs) != 1 or p.name == b.name or b.phis():
                continue
            p.instrs = p.instrs[:-1] + b.instrs
            fn.blocks = [x for x in fn.blocks if x.name != b.name]
            for s in b.succs:
                for phi in bm[s].phis():
                    if b.name in phi.phi:
                        phi.phi = {(p.name if q == b.name else q): v for q, v in phi.phi.items()}
            fn.recompute_edges()
            merged += 1
            changed = True
            break
    return merged


def fuse_branches(fn):
    use_count = {}
    for b in fn.blocks:
        for ins in b.instrs:
            for u in ins.uses():
                use_count[u] = use_count.get(u, 0) + 1
    fused = 0
    for b in fn.blocks:
        t = b.terminator
        if t is None or t.op != "br" or not isinstance(t.args[0], str):
            continue
        cond = t.args[0]
        if use_count.get(cond) != 1:
            continue
        for idx in range(len(b.instrs) - 2, -1, -1):
            ins = b.instrs[idx]
            if ins.dst == cond:
                if ins.op in RELOPS:
                    b.instrs[-1] = Instr("cbr", args=ins.args, targets=t.targets, line=t.line, relop=ins.op)
                    del b.instrs[idx]
                    fused += 1
                break
        else:
            continue
    for b in fn.blocks:
        t = b.terminator
        if t is not None and t.op == "br" and len(set(t.targets)) == 1:
            b.instrs[-1] = Instr("jmp", targets=[t.targets[0]], line=t.line)
    fn.recompute_edges()
    return fused


def optimize_function(fn, level=2):
    log = []
    if level <= 0:
        fused = fuse_branches(fn)
        log.append({"pass": "branch fusion", "changes": fused})
        return log
    for round_no in range(1, 11):
        total = 0
        for name, pass_fn in (("SCCP", sccp), ("copy propagation", copy_propagation),
                              ("algebraic simplification", simplify), ("GVN", gvn),
                              ("DCE", dce), ("block merging", merge_blocks)):
            c = pass_fn(fn)
            if c:
                log.append({"pass": name, "round": round_no, "changes": c})
            total += c
        if total == 0:
            break
    split_critical_edges(fn)
    fused = fuse_branches(fn)
    if fused:
        log.append({"pass": "branch fusion", "changes": fused})
    return log
