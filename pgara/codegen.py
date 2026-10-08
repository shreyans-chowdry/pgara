"""Target code generation for PG-RISC, a small load/store register machine.

Machine model
    r0 .. r{k-1}   allocatable registers (caller-saved)
    t0, t1, t2     scratch registers reserved for spill code and moves
    rv             return-value register;  fp  frame pointer

    Frame (word offsets from fp):  [params][spill slots][save slots][arrays]

Instruction set
    li rd, imm        mv rd, rs          neg rd, rs        seqz rd, rs
    add|sub|mul|div|rem|slt|sle|sgt|sge|seq|sne rd, rs1, rs2
    addi rd, rs, imm
    lw rd, off(fp)    sw rs, off(fp)     lwg rd, @g        swg rs, @g
    la rd, off(fp)    la rd, @g          lwx rd, rb, ri    swx rs, rb, ri
    blt|ble|bgt|bge|beq|bne rs1, rs2, L  bnez rs, L        j L
    arg i, rs         call f             ret               enter n   leave
    print rs          input rd

Out-of-SSA translation happens here: a phi becomes a parallel copy at the end
of each predecessor (critical edges were split earlier), sequentialised with
the scratch register t2 breaking cycles.  Values live across a call that sit
in registers are saved before and restored after it.
"""

ALU = {"add": "add", "sub": "sub", "mul": "mul", "div": "div", "mod": "rem",
       "lt": "slt", "le": "sle", "gt": "sgt", "ge": "sge", "eq": "seq", "ne": "sne"}
BRANCH = {"lt": "blt", "le": "ble", "gt": "bgt", "ge": "bge", "eq": "beq", "ne": "bne"}


class MInstr:
    __slots__ = ("op", "args", "tag", "acc", "line", "ir")

    def __init__(self, op, args, tag=None, acc=0, line=0, ir=None):
        self.op = op
        self.args = args
        self.tag = tag            # spill_load | spill_store | save | restore | arg | param | phi | None
        self.acc = acc            # SSA value accesses this instruction stands for
        self.line = line
        self.ir = ir

    def text(self):
        op, a = self.op, self.args
        if op == "label":
            return f"{a[0]}:"
        if op in ("lw", "sw", "la") and isinstance(a[1], int):
            return f"    {op:<6}{a[0]}, {a[1]}(fp)"
        if op in ("lwg", "swg") or (op == "la" and isinstance(a[1], str)):
            return f"    {op:<6}{a[0]}, @{a[1]}"
        return f"    {op:<6}" + ", ".join(str(x) for x in a)

    def to_dict(self):
        return {"text": self.text(), "tag": self.tag, "line": self.line, "ir": self.ir}


class Loc:
    __slots__ = ("kind", "val")

    def __init__(self, kind, val):
        self.kind = kind      # 'r' register, 's' frame slot, 'i' immediate
        self.val = val

    def __eq__(self, other):
        return isinstance(other, Loc) and self.kind == other.kind and self.val == other.val

    def __hash__(self):
        return hash((self.kind, self.val))

    def __repr__(self):
        return f"r{self.val}" if self.kind == "r" else (f"[{self.val}]" if self.kind == "s" else str(self.val))


class FunctionCode:
    def __init__(self, name):
        self.name = name
        self.code = []
        self.frame_size = 0
        self.nparams = 0
        self.arrays = {}          # uname -> (offset, size)
        self.locations = {}


def generate_function(fn, fa, alloc, k):
    fc = FunctionCode(fn.name)
    code = fc.code
    loc = {}
    nparams = len(fn.params)
    fc.nparams = nparams
    slot = nparams
    param_values = {}
    for ins in fn.entry.instrs:
        if ins.op == "param":
            param_values[ins.dst] = ins.args[0]
    # Spill-slot coalescing: spilled members of a phi web share a frame slot
    # whenever they do not interfere, so memory-to-memory phi copies vanish.
    groups = []                     # list of (slot, members)
    for v in fa.values:
        if v in alloc.reg:
            loc[v] = Loc("r", alloc.reg[v])
            continue
        web = set(fa.webs[v])
        home = None
        for g_slot, members in groups:
            if members & web and not any(w in fa.adj[v] for w in members):
                home = (g_slot, members)
                break
        if v in param_values:
            p_slot = param_values[v]
            if home is not None and home[0] != p_slot and not any(m in param_values for m in home[1]):
                # Move the whole group into the parameter's home slot.
                groups.remove(home)
                for m in home[1]:
                    loc[m] = Loc("s", p_slot)
                home = (p_slot, home[1])
                groups.append(home)
            elif home is None or home[0] != p_slot:
                home = (p_slot, set())
                groups.append(home)
        elif home is None:
            home = (slot, set())
            groups.append(home)
            slot += 1
        home[1].add(v)
        loc[v] = Loc("s", home[0])
    save_base = slot
    slot += k
    for name, size in fn.local_arrays.items():
        fc.arrays[name] = (slot, size)
        slot += size
    fc.frame_size = slot
    fc.locations = {v: repr(l) for v, l in loc.items()}

    def R(i):
        return f"r{i}"

    def emit(op, args, tag=None, acc=0, line=0, ir=None):
        code.append(MInstr(op, args, tag, acc, line, ir))

    def fetch(v, scratch, line, ir):
        """Register holding operand v, loading it into `scratch` if needed."""
        if isinstance(v, int):
            emit("li", [scratch, v], line=line, ir=ir)
            return scratch
        l = loc[v]
        if l.kind == "r":
            return R(l.val)
        emit("lw", [scratch, l.val], tag="spill_load", line=line, ir=ir)
        return scratch

    def dest(v):
        l = loc[v]
        return R(l.val) if l.kind == "r" else "t0"

    def commit(v, reg, line, ir):
        l = loc[v]
        if l.kind == "s":
            emit("sw", [reg, l.val], tag="spill_store", line=line, ir=ir)

    def move(dst, src, line):
        """dst, src are Loc or scratch-register names (str)."""
        def reg_of(l):
            return l if isinstance(l, str) else R(l.val)
        if isinstance(src, Loc) and src.kind == "i":
            if dst.kind == "r":
                emit("li", [R(dst.val), src.val], tag="phi", acc=1, line=line)
            else:
                emit("li", ["t0", src.val], tag="phi", line=line)
                emit("sw", ["t0", dst.val], tag="spill_store", acc=1, line=line)
            return
        src_is_mem = isinstance(src, Loc) and src.kind == "s"
        if dst.kind == "r":
            if src_is_mem:
                emit("lw", [R(dst.val), src.val], tag="spill_load", acc=2, line=line)
            else:
                emit("mv", [R(dst.val), reg_of(src)], tag="phi", acc=2 if isinstance(src, Loc) else 1, line=line)
        else:
            if src_is_mem:
                emit("lw", ["t0", src.val], tag="spill_load", acc=1, line=line)
                emit("sw", ["t0", dst.val], tag="spill_store", acc=1, line=line)
            else:
                emit("sw", [reg_of(src), dst.val], tag="spill_store",
                     acc=2 if isinstance(src, Loc) else 1, line=line)

    def parallel_copy(pairs, line):
        moves = [(d, s) for d, s in pairs if d != s]
        while moves:
            srcs = [s for _, s in moves]
            for idx, (d, s) in enumerate(moves):
                if d not in srcs:
                    move(d, s, line)
                    moves.pop(idx)
                    break
            else:
                d, s = moves[0]
                # Break the cycle: park d's current value in t2.
                if d.kind == "r":
                    emit("mv", ["t2", R(d.val)], tag="phi", line=line)
                else:
                    emit("lw", ["t2", d.val], tag="spill_load", line=line)
                moves = [(dd, "t2" if ss == d else ss) for dd, ss in moves]

    bm = fn.block_map()
    emit("label", [fn.name])
    emit("enter", [fc.frame_size], line=fn.line)
    for b in fn.blocks:
        emit("label", [f"{fn.name}.{b.name}"])
        after = fa.live_after(b)
        for idx, ins in enumerate(b.instrs):
            op = ins.op
            line = ins.line
            ir = str(ins)
            if op == "phi":
                continue
            if op == "param":
                l = loc[ins.dst]
                if l.kind == "r":
                    emit("lw", [R(l.val), ins.args[0]], tag="param", acc=1, line=line, ir=ir)
                continue
            if ins.is_terminator():
                # Phi resolution for the (unique) successor before leaving the block.
                if op == "jmp":
                    succ = bm[ins.targets[0]]
                    pairs = []
                    for phi in succ.phis():
                        src = phi.phi.get(b.name, 0)
                        s_loc = Loc("i", src) if isinstance(src, int) else loc[src]
                        pairs.append((loc[phi.dst], s_loc))
                    parallel_copy(pairs, line)
                    emit("j", [f"{fn.name}.{ins.targets[0]}"], line=line, ir=ir)
                elif op == "br":
                    c = fetch(ins.args[0], "t0", line, ir)
                    emit("bnez", [c, f"{fn.name}.{ins.targets[0]}"], acc=int(isinstance(ins.args[0], str)), line=line, ir=ir)
                    emit("j", [f"{fn.name}.{ins.targets[1]}"], line=line, ir=ir)
                elif op == "cbr":
                    a = fetch(ins.args[0], "t0", line, ir)
                    c = fetch(ins.args[1], "t1", line, ir)
                    nacc = sum(isinstance(x, str) for x in ins.args)
                    emit(BRANCH[ins.relop], [a, c, f"{fn.name}.{ins.targets[0]}"], acc=nacc, line=line, ir=ir)
                    emit("j", [f"{fn.name}.{ins.targets[1]}"], line=line, ir=ir)
                elif op == "ret":
                    if ins.args:
                        v = ins.args[0]
                        if isinstance(v, int):
                            emit("li", ["rv", v], line=line, ir=ir)
                        elif loc[v].kind == "r":
                            emit("mv", ["rv", R(loc[v].val)], acc=1, line=line, ir=ir)
                        else:
                            emit("lw", ["rv", loc[v].val], tag="spill_load", acc=1, line=line, ir=ir)
                    emit("leave", [], line=line, ir=ir)
                    emit("ret", [], line=line, ir=ir)
                continue
            nacc = sum(isinstance(x, str) for x in ins.args) + (1 if ins.dst is not None else 0)
            if op in ALU:
                x, y = ins.args
                if op in ("add", "sub") and isinstance(y, int) and isinstance(x, str):
                    a = fetch(x, "t0", line, ir)
                    d = dest(ins.dst)
                    emit("addi", [d, a, y if op == "add" else -y], acc=nacc, line=line, ir=ir)
                elif op == "add" and isinstance(x, int) and isinstance(y, str):
                    a = fetch(y, "t0", line, ir)
                    d = dest(ins.dst)
                    emit("addi", [d, a, x], acc=nacc, line=line, ir=ir)
                else:
                    a = fetch(x, "t0", line, ir)
                    c = fetch(y, "t1", line, ir)
                    d = dest(ins.dst)
                    emit(ALU[op], [d, a, c], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op in ("neg", "not"):
                a = fetch(ins.args[0], "t0", line, ir)
                d = dest(ins.dst)
                emit("neg" if op == "neg" else "seqz", [d, a], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op in ("copy", "const"):
                v = ins.args[0]
                d = dest(ins.dst)
                if isinstance(v, int):
                    emit("li", [d, v], acc=nacc, line=line, ir=ir)
                else:
                    a = fetch(v, "t0", line, ir)
                    if a != d:
                        emit("mv", [d, a], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op == "addr":
                d = dest(ins.dst)
                if ins.sym in fc.arrays:
                    emit("la", [d, fc.arrays[ins.sym][0]], acc=nacc, line=line, ir=ir)
                else:
                    emit("la", [d, ins.sym], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op == "aload":
                base = fetch(ins.args[0], "t0", line, ir)
                index = fetch(ins.args[1], "t1", line, ir)
                d = dest(ins.dst)
                emit("lwx", [d, base, index], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op == "astore":
                base = fetch(ins.args[0], "t0", line, ir)
                index = fetch(ins.args[1], "t1", line, ir)
                val = fetch(ins.args[2], "t2", line, ir)
                emit("swx", [val, base, index], acc=nacc, line=line, ir=ir)
            elif op == "gload":
                d = dest(ins.dst)
                emit("lwg", [d, ins.sym], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op == "gstore":
                val = fetch(ins.args[0], "t0", line, ir)
                emit("swg", [val, ins.sym], acc=nacc, line=line, ir=ir)
            elif op == "print":
                val = fetch(ins.args[0], "t0", line, ir)
                emit("print", [val], acc=nacc, line=line, ir=ir)
            elif op == "input":
                d = dest(ins.dst)
                emit("input", [d], acc=nacc, line=line, ir=ir)
                commit(ins.dst, d, line, ir)
            elif op == "call":
                across = sorted((after[idx] - {ins.dst}), key=lambda v: str(v))
                saved = sorted({loc[v].val for v in across if v in loc and loc[v].kind == "r"})
                for r in saved:
                    emit("sw", [R(r), save_base + r], tag="save", line=line, ir=ir)
                for i, a in enumerate(ins.args):
                    reg = fetch(a, "t0", line, ir)
                    emit("arg", [i, reg], tag="arg", acc=int(isinstance(a, str)), line=line, ir=ir)
                emit("call", [ins.sym], line=line, ir=ir)
                for r in saved:
                    emit("lw", [R(r), save_base + r], tag="restore", line=line, ir=ir)
                if ins.dst is not None:
                    l = loc[ins.dst]
                    if l.kind == "r":
                        emit("mv", [R(l.val), "rv"], acc=1, line=line, ir=ir)
                    else:
                        emit("sw", ["rv", l.val], tag="spill_store", acc=1, line=line, ir=ir)
            else:
                raise ValueError(f"codegen: unknown opcode {op}")
    fc.code = peephole(code)
    return fc


def peephole(code):
    """Thread jumps through blocks that only jump, drop unreferenced labels of
    such blocks and remove jumps to the immediately following label."""
    alias = {}
    for i, ins in enumerate(code):
        if ins.op == "label" and i + 1 < len(code) and code[i + 1].op == "j" \
                and i > 0 and code[i - 1].op != "enter":
            alias[ins.args[0]] = code[i + 1].args[0]

    def resolve(label):
        seen = set()
        while label in alias and label not in seen:
            seen.add(label)
            label = alias[label]
        return label

    for ins in code:
        if ins.op in ("j", "bnez") or ins.op in BRANCH.values():
            ins.args = ins.args[:-1] + [resolve(ins.args[-1])]
    referenced = {ins.args[-1] for ins in code if ins.op in ("j", "bnez") or ins.op in BRANCH.values()}
    out = []
    skip = False
    for i, ins in enumerate(code):
        if ins.op == "label":
            name = ins.args[0]
            if "." in name and name not in referenced and name in alias:
                skip = True
                continue
            skip = False
            out.append(ins)
            continue
        if skip:
            # Unreachable jump of a threaded block.
            continue
        out.append(ins)
    # Remove `j L` immediately followed by `L:` (possibly via other labels).
    final = []
    for i, ins in enumerate(out):
        if ins.op == "j":
            j = i + 1
            following = set()
            while j < len(out) and out[j].op == "label":
                following.add(out[j].args[0])
                j += 1
            if ins.args[0] in following:
                continue
        final.append(ins)
    # Store-to-load forwarding: a reload of the slot just stored needs no memory access.
    forwarded = []
    for ins in final:
        prev = forwarded[-1] if forwarded else None
        if (ins.op == "lw" and prev is not None and prev.op == "sw" and prev.args[1] == ins.args[1]
                and isinstance(ins.args[1], int)):
            if ins.args[0] == prev.args[0]:
                continue
            forwarded.append(MInstr("mv", [ins.args[0], prev.args[0]], "forward", ins.acc, ins.line, ins.ir))
            continue
        forwarded.append(ins)
    final = forwarded
    # Labels that are no longer referenced are kept only at function entry.
    referenced = {ins.args[-1] for ins in final if ins.op in ("j", "bnez") or ins.op in BRANCH.values()}
    return [ins for ins in final if ins.op != "label" or "." not in ins.args[0] or ins.args[0] in referenced]


def generate_module(module, analyses, allocations, k):
    program = []
    functions = {}
    for name, fn in module.functions.items():
        fc = generate_function(fn, analyses[name], allocations[name], k)
        functions[name] = fc
        program.extend(fc.code)
    return program, functions
