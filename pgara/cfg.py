"""Control-flow graph construction and analyses on it: basic-block
partitioning, unreachable-code removal, critical-edge splitting, dominators
(Cooper-Harvey-Kennedy iterative algorithm), dominance frontiers, and natural
loop detection (back edges u->h with h dom u)."""

from .ir import Block, Instr


def build_cfg(fn):
    """Partition fn.linear into basic blocks.  A leader is the first
    instruction, any label, and any instruction following a terminator."""
    blocks = []
    current = None
    anon = 0
    for ins in fn.linear:
        if ins.op == "label":
            if current is not None and current.terminator is None:
                current.instrs.append(Instr("jmp", targets=[ins.sym], line=ins.line))
            current = Block(ins.sym)
            blocks.append(current)
            continue
        if current is None or current.terminator is not None:
            anon += 1
            current = Block(f"B{anon}")
            blocks.append(current)
        current.instrs.append(ins.copy())
    if current is not None and current.terminator is None:
        current.instrs.append(Instr("ret", args=[0] if fn.ret_type == "int" else [], line=fn.line))
    fn.blocks = blocks
    # Labels with no instructions before the next label become blocks holding only a jump.
    fn.recompute_edges()
    remove_unreachable(fn)
    split_critical_edges(fn)
    return fn


def remove_unreachable(fn):
    bm = fn.block_map()
    seen = set()
    stack = [fn.blocks[0].name]
    while stack:
        b = stack.pop()
        if b in seen:
            continue
        seen.add(b)
        stack.extend(bm[b].succs)
    removed = [b.name for b in fn.blocks if b.name not in seen]
    fn.blocks = [b for b in fn.blocks if b.name in seen]
    if removed:
        for b in fn.blocks:
            for phi in b.phis():
                for r in removed:
                    phi.phi.pop(r, None)
        fn.recompute_edges()
    return removed


def split_critical_edges(fn):
    """An edge u->v is critical when u has several successors and v several
    predecessors.  Splitting gives every such edge its own block, which is
    where phi-resolution copies are later placed."""
    bm = fn.block_map()
    new_blocks = []
    count = 0
    for b in list(fn.blocks):
        if len(b.succs) < 2:
            continue
        for s in list(b.succs):
            if len(bm[s].preds) < 2:
                continue
            count += 1
            name = f"{b.name}_{s}"
            mid = Block(name)
            mid.instrs.append(Instr("jmp", targets=[s], line=b.terminator.line))
            t = b.terminator
            t.targets = [name if x == s else x for x in t.targets]
            for phi in bm[s].phis():
                if b.name in phi.phi:
                    phi.phi = {(name if p == b.name else p): v for p, v in phi.phi.items()}
            new_blocks.append((b.name, mid))
    if new_blocks:
        order = []
        pending = {}
        for after, mid in new_blocks:
            pending.setdefault(after, []).append(mid)
        for b in fn.blocks:
            order.append(b)
            order.extend(pending.get(b.name, []))
        fn.blocks = order
        fn.recompute_edges()
    return count


def reverse_postorder(fn):
    bm = fn.block_map()
    seen = set()
    post = []

    def dfs(name):
        stack = [(name, iter(bm[name].succs))]
        seen.add(name)
        while stack:
            node, it = stack[-1]
            advanced = False
            for s in it:
                if s not in seen:
                    seen.add(s)
                    stack.append((s, iter(bm[s].succs)))
                    advanced = True
                    break
            if not advanced:
                post.append(node)
                stack.pop()

    dfs(fn.blocks[0].name)
    return list(reversed(post))


def dominators(fn):
    """Immediate dominators by the Cooper-Harvey-Kennedy algorithm."""
    rpo = reverse_postorder(fn)
    index = {b: i for i, b in enumerate(rpo)}
    bm = fn.block_map()
    entry = rpo[0]
    idom = {entry: entry}

    def intersect(a, b):
        while a != b:
            while index[a] > index[b]:
                a = idom[a]
            while index[b] > index[a]:
                b = idom[b]
        return a

    changed = True
    while changed:
        changed = False
        for b in rpo[1:]:
            preds = [p for p in bm[b].preds if p in idom]
            if not preds:
                continue
            new = preds[0]
            for p in preds[1:]:
                new = intersect(p, new)
            if idom.get(b) != new:
                idom[b] = new
                changed = True
    return idom


def dom_tree(idom):
    children = {b: [] for b in idom}
    for b, d in idom.items():
        if b != d:
            children[d].append(b)
    return children


def dominates(idom, a, b):
    """True if block a dominates block b."""
    while True:
        if a == b:
            return True
        if idom[b] == b:
            return False
        b = idom[b]


def dominance_frontiers(fn, idom):
    df = {b.name: set() for b in fn.blocks}
    for b in fn.blocks:
        if len(b.preds) < 2:
            continue
        for p in b.preds:
            runner = p
            while runner != idom[b.name]:
                df[runner].add(b.name)
                runner = idom[runner]
    return df


def natural_loops(fn, idom=None):
    """Return (back_edges, loop_body_by_header, depth_by_block)."""
    if idom is None:
        idom = dominators(fn)
    bm = fn.block_map()
    back_edges = []
    loops = {}
    for b in fn.blocks:
        for s in b.succs:
            if dominates(idom, s, b.name):
                back_edges.append((b.name, s))
                body = loops.setdefault(s, {s})
                stack = [b.name]
                while stack:
                    x = stack.pop()
                    if x not in body:
                        body.add(x)
                        stack.extend(bm[x].preds)
    depth = {b.name: 0 for b in fn.blocks}
    for body in loops.values():
        for x in body:
            depth[x] += 1
    return back_edges, loops, depth

