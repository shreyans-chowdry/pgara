"""Three-address code (TAC) representation.

An instruction is a quadruple (op, dst, args, extra).  Operands are either
variable names (str) or integer constants (int).  Functions are lists of
basic blocks once the control-flow graph has been built; before that they
hold a linear instruction list with 'label' pseudo-instructions.

Opcodes
    const   dst = c                 copy  dst = a
    add sub mul div mod             dst = a (op) b
    lt le gt ge eq ne               dst = a (relop) b   (0 or 1)
    neg not                         dst = (op) a
    param   dst = param #i          addr  dst = &array
    aload   dst = base[idx]         astore base[idx] = val
    gload   dst = global            gstore global = val
    call    [dst =] f(args)         input dst = input()
    print   print a
    phi     dst = phi(pred: a, ...)
    jmp L | br a, Lt, Lf | cbr relop a b, Lt, Lf | ret [a]
"""

BINOPS = {"add", "sub", "mul", "div", "mod", "lt", "le", "gt", "ge", "eq", "ne"}
RELOPS = {"lt", "le", "gt", "ge", "eq", "ne"}
UNOPS = {"neg", "not"}
COMMUTATIVE = {"add", "mul", "eq", "ne"}
TERMINATORS = {"jmp", "br", "cbr", "ret"}
SIDE_EFFECTS = {"astore", "gstore", "call", "print", "input", "jmp", "br", "cbr", "ret"}
PURE = BINOPS | UNOPS | {"const", "copy", "addr", "param"}

OP_SYMBOL = {
    "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%",
    "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "==", "ne": "!=",
    "neg": "-", "not": "!",
}
SWAPPED_RELOP = {"lt": "gt", "gt": "lt", "le": "ge", "ge": "le", "eq": "eq", "ne": "ne"}
NEGATED_RELOP = {"lt": "ge", "ge": "lt", "gt": "le", "le": "gt", "eq": "ne", "ne": "eq"}

MASK = 0xFFFFFFFF


def wrap32(x):
    x &= MASK
    return x - 0x100000000 if x & 0x80000000 else x


class RuntimeFault(Exception):
    pass


def eval_binop(op, a, b):
    """Shared arithmetic semantics (C-like, 32-bit two's complement) used by the
    constant folder, the TAC interpreter and the target simulator."""
    if op == "add":
        return wrap32(a + b)
    if op == "sub":
        return wrap32(a - b)
    if op == "mul":
        return wrap32(a * b)
    if op in ("div", "mod"):
        if b == 0:
            raise RuntimeFault("division by zero")
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        return wrap32(q) if op == "div" else wrap32(a - q * b)
    if op == "lt":
        return int(a < b)
    if op == "le":
        return int(a <= b)
    if op == "gt":
        return int(a > b)
    if op == "ge":
        return int(a >= b)
    if op == "eq":
        return int(a == b)
    if op == "ne":
        return int(a != b)
    raise ValueError(op)


def eval_unop(op, a):
    if op == "neg":
        return wrap32(-a)
    if op == "not":
        return int(a == 0)
    raise ValueError(op)


class Instr:
    __slots__ = ("op", "dst", "args", "targets", "sym", "phi", "line", "relop", "tag")

    def __init__(self, op, dst=None, args=None, targets=None, sym=None, phi=None, line=0, relop=None):
        self.op = op
        self.dst = dst
        self.args = list(args) if args else []
        self.targets = list(targets) if targets else []
        self.sym = sym
        self.phi = dict(phi) if phi else {}
        self.line = line
        self.relop = relop
        self.tag = None

    def uses(self):
        if self.op == "phi":
            return [v for v in self.phi.values() if isinstance(v, str)]
        return [a for a in self.args if isinstance(a, str)]

    def replace_uses(self, mapping):
        if self.op == "phi":
            self.phi = {p: mapping.get(v, v) if isinstance(v, str) else v for p, v in self.phi.items()}
        else:
            self.args = [mapping.get(a, a) if isinstance(a, str) else a for a in self.args]

    def is_terminator(self):
        return self.op in TERMINATORS

    def copy(self):
        c = Instr(self.op, self.dst, self.args, self.targets, self.sym, self.phi, self.line, self.relop)
        c.tag = self.tag
        return c

    def __str__(self):
        return format_instr(self)


def fmt(v):
    return str(v)


def format_instr(i):
    op = i.op
    d = i.dst
    a = [fmt(x) for x in i.args]
    if op == "label":
        return f"{i.sym}:"
    if op == "const" or op == "copy":
        return f"{d} = {a[0]}"
    if op in BINOPS:
        return f"{d} = {a[0]} {OP_SYMBOL[op]} {a[1]}"
    if op in UNOPS:
        return f"{d} = {OP_SYMBOL[op]}{a[0]}"
    if op == "param":
        return f"{d} = param #{a[0]}"
    if op == "addr":
        return f"{d} = &{i.sym}"
    if op == "aload":
        return f"{d} = {a[0]}[{a[1]}]"
    if op == "astore":
        return f"{a[0]}[{a[1]}] = {a[2]}"
    if op == "gload":
        return f"{d} = @{i.sym}"
    if op == "gstore":
        return f"@{i.sym} = {a[0]}"
    if op == "call":
        call = f"call {i.sym}({', '.join(a)})"
        return f"{d} = {call}" if d else call
    if op == "input":
        return f"{d} = input()"
    if op == "print":
        return f"print {a[0]}"
    if op == "phi":
        parts = ", ".join(f"{p}: {fmt(v)}" for p, v in i.phi.items())
        return f"{d} = φ({parts})"
    if op == "jmp":
        return f"goto {i.targets[0]}"
    if op == "br":
        return f"if {a[0]} goto {i.targets[0]} else {i.targets[1]}"
    if op == "cbr":
        return f"if {a[0]} {OP_SYMBOL[i.relop]} {a[1]} goto {i.targets[0]} else {i.targets[1]}"
    if op == "ret":
        return f"return {a[0]}" if a else "return"
    return f"{op} {d} {a}"


class Block:
    __slots__ = ("name", "instrs", "succs", "preds")

    def __init__(self, name):
        self.name = name
        self.instrs = []
        self.succs = []
        self.preds = []

    @property
    def terminator(self):
        return self.instrs[-1] if self.instrs and self.instrs[-1].is_terminator() else None

    def phis(self):
        return [i for i in self.instrs if i.op == "phi"]

    def body(self):
        return [i for i in self.instrs if i.op != "phi"]


class Function:
    def __init__(self, name, ret_type, params, line=0):
        self.name = name
        self.ret_type = ret_type
        self.params = params            # list of (uname, is_array)
        self.local_arrays = {}          # uname -> size
        self.linear = []                # linear TAC (before CFG construction)
        self.blocks = []                # list of Block (after CFG construction)
        self.line = line

    @property
    def entry(self):
        return self.blocks[0]

    def block_map(self):
        return {b.name: b for b in self.blocks}

    def recompute_edges(self):
        bm = self.block_map()
        for b in self.blocks:
            b.succs = []
            b.preds = []
        for b in self.blocks:
            t = b.terminator
            if t is None:
                continue
            for target in t.targets:
                if target not in b.succs:
                    b.succs.append(target)
        for b in self.blocks:
            for s in b.succs:
                bm[s].preds.append(b.name)

    def listing(self):
        lines = []
        for b in self.blocks:
            lines.append({"text": f"{b.name}:", "line": 0, "kind": "label", "block": b.name})
            for i in b.instrs:
                lines.append({"text": "    " + format_instr(i), "line": i.line, "kind": i.op, "block": b.name})
        return lines

    def linear_listing(self):
        out = []
        for i in self.linear:
            if i.op == "label":
                out.append({"text": f"{i.sym}:", "line": i.line, "kind": "label"})
            else:
                out.append({"text": "    " + format_instr(i), "line": i.line, "kind": i.op})
        return out


class Module:
    def __init__(self):
        self.functions = {}             # name -> Function, in source order
        self.globals = {}               # name -> size (None for scalars)
