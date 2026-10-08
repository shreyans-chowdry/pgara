"""Liveness analysis and static single assignment (SSA) construction.

Liveness is the classical backward may-analysis solved to a fixpoint,
extended with the standard phi convention: a phi's operand coming from
predecessor P is used at the end of P, and a phi's result is defined at the
very top of its block.

SSA construction follows Cytron et al.: phi functions are placed on the
iterated dominance frontier of each variable's definition sites (pruned by
liveness so that no dead phi is created), and a pre-order walk of the
dominator tree renames every definition to a fresh version.
"""

import sys

from .cfg import dominators, dom_tree, dominance_frontiers
from .ir import Instr

sys.setrecursionlimit(20000)


def block_use_def(block):
    """(UEVar, Defs) over the non-phi instructions; phi results count as defs."""
    use, defs = set(), set()
    for ins in block.instrs:
        if ins.op == "phi":
            defs.add(ins.dst)
            continue
        for u in ins.uses():
            if u not in defs:
                use.add(u)
        if ins.dst is not None:
            defs.add(ins.dst)
    return use, defs


def phi_uses_from(fn):
    bm = fn.block_map()
    out = {b.name: set() for b in fn.blocks}
    for b in fn.blocks:
        for s in b.succs:
            for phi in bm[s].phis():
                v = phi.phi.get(b.name)
                if isinstance(v, str):
                    out[b.name].add(v)
    return out


def liveness(fn):
    """Return (live_in, live_out, iterations)."""
    bm = fn.block_map()
    ud = {b.name: block_use_def(b) for b in fn.blocks}
    phi_out = phi_uses_from(fn)
    live_in = {b.name: set() for b in fn.blocks}
    live_out = {b.name: set() for b in fn.blocks}
    order = [b.name for b in reversed(fn.blocks)]
    iterations = 0
    changed = True
    while changed:
        changed = False
        iterations += 1
        for name in order:
            out = set(phi_out[name])
            for s in bm[name].succs:
                out |= live_in[s]
            use, defs = ud[name]
            new_in = use | (out - defs)
            if new_in != live_in[name] or out != live_out[name]:
                live_in[name] = new_in
                live_out[name] = out
                changed = True
    return live_in, live_out, iterations


def construct_ssa(fn):
    idom = dominators(fn)
    tree = dom_tree(idom)
    df = dominance_frontiers(fn, idom)
    bm = fn.block_map()
    live_in, _, _ = liveness(fn)

    params = {i.dst for i in fn.entry.instrs if i.op == "param"}
    defsites = {}
    for b in fn.blocks:
        for ins in b.instrs:
            if ins.dst is not None:
                defsites.setdefault(ins.dst, set()).add(b.name)

    # Phi placement on the iterated dominance frontier, pruned by liveness.
    has_phi = {}
    phi_count = 0
    for v, sites in defsites.items():
        work = list(sites)
        placed = set()
        while work:
            x = work.pop()
            for y in df[x]:
                if y in placed or v not in live_in[y]:
                    continue
                phi = Instr("phi", dst=v, phi={p: v for p in bm[y].preds}, sym=v, line=0)
                bm[y].instrs.insert(0, phi)
                placed.add(y)
                phi_count += 1
                if y not in sites:
                    work.append(y)
        if placed:
            has_phi[v] = placed

    multi = {v for v, s in defsites.items() if len(s) > 1 or v in has_phi}
    for v, sites in defsites.items():
        if v in multi:
            continue
        count = sum(1 for b in fn.blocks for i in b.instrs if i.dst == v)
        if count > 1:
            multi.add(v)

    counters = {}
    stacks = {}

    def fresh(v):
        if v not in multi:
            stacks.setdefault(v, []).append(v)
            return v
        counters[v] = counters.get(v, 0) + 1
        name = f"{v}.{counters[v]}"
        stacks.setdefault(v, []).append(name)
        return name

    def top(v):
        st = stacks.get(v)
        return st[-1] if st else 0      # an undefined read is the constant 0

    def rename(bname):
        block = bm[bname]
        pushed = []
        for ins in block.instrs:
            if ins.op != "phi":
                ins.args = [top(a) if isinstance(a, str) else a for a in ins.args]
            if ins.dst is not None:
                orig = ins.sym if ins.op == "phi" else ins.dst
                ins.dst = fresh(orig)
                pushed.append(orig)
        for s in block.succs:
            for phi in bm[s].phis():
                phi.phi[bname] = top(phi.sym)
        for child in tree[bname]:
            rename(child)
        for v in pushed:
            stacks[v].pop()

    rename(fn.blocks[0].name)
    for b in fn.blocks:
        for ins in b.instrs:
            if ins.op == "phi":
                ins.sym = None
    return {"phis": phi_count, "versioned": sorted(multi), "params": sorted(params)}
