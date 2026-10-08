"""Syntax-directed translation from the decorated AST to linear three-address
code.

Expressions synthesize an `addr` attribute (the operand holding their value).
Boolean conditions are translated as jumping code: gen_cond receives the
inherited attributes `true` and `false` (labels) and emits short-circuit
control flow for &&, || and !, exactly the classical backpatching-free
formulation of Aho, Lam, Sethi and Ullman.  Loops push (continue, break)
label pairs so that break/continue become unconditional jumps.
"""

from .ir import Instr, Function, Module

ARITH = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}
REL = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge", "==": "eq", "!=": "ne"}
COMPOUND = {"+=": "add", "-=": "sub", "*=": "mul"}


class IRGen:
    def __init__(self):
        self.module = Module()
        self.fn = None
        self.temp_count = 0
        self.label_count = 0
        self.loops = []

    def new_temp(self):
        self.temp_count += 1
        return f"t{self.temp_count}"

    def new_label(self, hint="L"):
        self.label_count += 1
        return f"{hint}{self.label_count}"

    def emit(self, op, line, **kw):
        ins = Instr(op, line=line, **kw)
        self.fn.linear.append(ins)
        return ins

    def label(self, name, line=0):
        self.emit("label", line, sym=name)

    # -- program -----------------------------------------------------------
    def gen_program(self, program):
        for decl in program.decls:
            if decl.kind == "GlobalVar" and decl.symbol is not None:
                self.module.globals[decl.symbol.uname] = decl.size
        for decl in program.decls:
            if decl.kind == "Function" and decl.symbol is not None:
                self.gen_function(decl)
        return self.module

    def gen_function(self, fn):
        params = [(p.symbol.uname, p.is_array) for p in fn.params if p.symbol is not None]
        self.fn = Function(fn.name, fn.ret_type, params, fn.line)
        self.temp_count = 0
        self.label_count = 0
        self.module.functions[fn.name] = self.fn
        self.label("entry", fn.line)
        for idx, (uname, _) in enumerate(params):
            self.emit("param", fn.line, dst=uname, args=[idx])
        self.gen_stmts(fn.body.stmts)
        end_line = fn.body.line
        if fn.ret_type == "int":
            self.emit("ret", end_line, args=[0])
        else:
            self.emit("ret", end_line)

    # -- statements ------------------------------------------------------
    def gen_stmts(self, stmts):
        for s in stmts:
            self.gen_stmt(s)

    def gen_stmt(self, s):
        k = s.kind
        line = s.line
        if k == "Block":
            self.gen_stmts(s.stmts)
        elif k == "VarDecl":
            sym = s.symbol
            if sym.kind == "array":
                self.fn.local_arrays[sym.uname] = sym.size
                return
            if s.init is None:
                self.emit("const", line, dst=sym.uname, args=[0])
            else:
                self.gen_expr_into(s.init, sym.uname)
        elif k == "Assign":
            self.gen_assign(s)
        elif k == "ExprStmt":
            self.gen_call(s.expr, want_value=False)
        elif k == "Print":
            v = self.gen_expr(s.value)
            self.emit("print", line, args=[v])
        elif k == "If":
            l_then = self.new_label("then")
            l_end = self.new_label("endif")
            l_else = self.new_label("else") if s.other is not None else l_end
            self.gen_cond(s.cond, l_then, l_else)
            self.label(l_then, line)
            self.gen_stmt(s.then)
            if s.other is not None:
                self.emit("jmp", line, targets=[l_end])
                self.label(l_else, s.other.line)
                self.gen_stmt(s.other)
            self.label(l_end, line)
        elif k == "While":
            l_cond = self.new_label("while")
            l_body = self.new_label("body")
            l_end = self.new_label("endwhile")
            self.label(l_cond, line)
            self.gen_cond(s.cond, l_body, l_end)
            self.label(l_body, line)
            self.loops.append((l_cond, l_end))
            self.gen_stmt(s.body)
            self.loops.pop()
            self.emit("jmp", line, targets=[l_cond])
            self.label(l_end, line)
        elif k == "For":
            if s.init is not None:
                self.gen_stmt(s.init)
            l_cond = self.new_label("for")
            l_body = self.new_label("body")
            l_step = self.new_label("step")
            l_end = self.new_label("endfor")
            self.label(l_cond, line)
            if s.cond is not None:
                self.gen_cond(s.cond, l_body, l_end)
            self.label(l_body, line)
            self.loops.append((l_step, l_end))
            self.gen_stmt(s.body)
            self.loops.pop()
            self.label(l_step, line)
            if s.step is not None:
                self.gen_stmt(s.step)
            self.emit("jmp", line, targets=[l_cond])
            self.label(l_end, line)
        elif k == "Return":
            if s.value is not None:
                v = self.gen_expr(s.value)
                self.emit("ret", line, args=[v])
            else:
                self.emit("ret", line)
            self.label(self.new_label("dead"), line)
        elif k == "Break":
            self.emit("jmp", line, targets=[self.loops[-1][1]])
            self.label(self.new_label("dead"), line)
        elif k == "Continue":
            self.emit("jmp", line, targets=[self.loops[-1][0]])
            self.label(self.new_label("dead"), line)

    def gen_assign(self, s):
        target = s.target
        sym = target.symbol
        line = s.line
        if target.kind == "Var":
            if sym.kind == "global":
                if s.op == "=":
                    v = self.gen_expr(s.value)
                else:
                    cur = self.new_temp()
                    self.emit("gload", line, dst=cur, sym=sym.uname)
                    rhs = self.gen_expr(s.value)
                    v = self.new_temp()
                    self.emit(COMPOUND[s.op], line, dst=v, args=[cur, rhs])
                self.emit("gstore", line, args=[v], sym=sym.uname)
            else:
                if s.op == "=":
                    self.gen_expr_into(s.value, sym.uname)
                else:
                    rhs = self.gen_expr(s.value)
                    self.emit(COMPOUND[s.op], line, dst=sym.uname, args=[sym.uname, rhs])
        else:
            base = self.gen_base(sym, line)
            idx = self.gen_expr(target.index)
            if s.op == "=":
                v = self.gen_expr(s.value)
            else:
                cur = self.new_temp()
                self.emit("aload", line, dst=cur, args=[base, idx])
                rhs = self.gen_expr(s.value)
                v = self.new_temp()
                self.emit(COMPOUND[s.op], line, dst=v, args=[cur, rhs])
            self.emit("astore", line, args=[base, idx, v])

    # -- expressions -----------------------------------------------------
    def gen_base(self, sym, line):
        """Operand holding the base address of an array."""
        if sym.kind == "array_param":
            return sym.uname
        t = self.new_temp()
        self.emit("addr", line, dst=t, sym=sym.uname)
        return t

    def gen_expr_into(self, e, dst):
        """Translate e so that its value lands in dst (target-directed: the last
        instruction's temporary is renamed instead of emitting a copy)."""
        before = len(self.fn.linear)
        v = self.gen_expr(e)
        last = self.fn.linear[-1] if len(self.fn.linear) > before else None
        if isinstance(v, str) and last is not None and last.dst == v and v.startswith("t") \
                and last.op not in ("label",) and self.is_fresh_temp(v, before):
            last.dst = dst
        elif isinstance(v, int):
            self.emit("const", e.line, dst=dst, args=[v])
        else:
            self.emit("copy", e.line, dst=dst, args=[v])

    def is_fresh_temp(self, v, start):
        """True if temp v is defined exactly once, by the last instruction, and
        not used anywhere since `start` (so it can be renamed safely)."""
        defs = 0
        for ins in self.fn.linear[start:]:
            if ins.dst == v:
                defs += 1
            if v in ins.uses():
                return False
        return defs == 1

    def gen_expr(self, e):
        k = e.kind
        line = e.line
        if k == "Num":
            return e.value
        if k == "Var":
            sym = e.symbol
            if sym.kind == "global":
                t = self.new_temp()
                self.emit("gload", line, dst=t, sym=sym.uname)
                return t
            if sym.is_array:
                return self.gen_base(sym, line)
            return sym.uname
        if k == "Index":
            base = self.gen_base(e.symbol, line)
            idx = self.gen_expr(e.index)
            t = self.new_temp()
            self.emit("aload", line, dst=t, args=[base, idx])
            return t
        if k == "Binary":
            if e.op in ARITH:
                a = self.gen_expr(e.left)
                b = self.gen_expr(e.right)
                t = self.new_temp()
                self.emit(ARITH[e.op], line, dst=t, args=[a, b])
                return t
            if e.op in REL:
                a = self.gen_expr(e.left)
                b = self.gen_expr(e.right)
                t = self.new_temp()
                self.emit(REL[e.op], line, dst=t, args=[a, b])
                return t
            return self.gen_bool_value(e)
        if k == "Unary":
            if e.op == "!":
                a = self.gen_expr(e.operand)
                t = self.new_temp()
                self.emit("not", line, dst=t, args=[a])
                return t
            a = self.gen_expr(e.operand)
            t = self.new_temp()
            self.emit("neg", line, dst=t, args=[a])
            return t
        if k == "Call":
            return self.gen_call(e, want_value=True)
        if k == "Input":
            t = self.new_temp()
            self.emit("input", line, dst=t)
            return t
        raise ValueError(k)

    def gen_bool_value(self, e):
        """Value of a short-circuit && / || expression: jumping code that
        assigns 1 or 0 to a fresh temporary on the two exits."""
        t = self.new_temp()
        l_true = self.new_label("btrue")
        l_false = self.new_label("bfalse")
        l_end = self.new_label("bend")
        self.gen_cond(e, l_true, l_false)
        self.label(l_true, e.line)
        self.emit("const", e.line, dst=t, args=[1])
        self.emit("jmp", e.line, targets=[l_end])
        self.label(l_false, e.line)
        self.emit("const", e.line, dst=t, args=[0])
        self.label(l_end, e.line)
        return t

    def gen_call(self, e, want_value):
        args = []
        for a in e.args:
            args.append(self.gen_expr(a))
        dst = self.new_temp() if (want_value or e.symbol.ret_type == "int") else None
        self.emit("call", e.line, dst=dst, args=args, sym=e.name)
        return dst

    def gen_cond(self, e, l_true, l_false):
        if e.kind == "Binary" and e.op == "&&":
            mid = self.new_label("and")
            self.gen_cond(e.left, mid, l_false)
            self.label(mid, e.line)
            self.gen_cond(e.right, l_true, l_false)
            return
        if e.kind == "Binary" and e.op == "||":
            mid = self.new_label("or")
            self.gen_cond(e.left, l_true, mid)
            self.label(mid, e.line)
            self.gen_cond(e.right, l_true, l_false)
            return
        if e.kind == "Unary" and e.op == "!":
            self.gen_cond(e.operand, l_false, l_true)
            return
        if e.kind == "Num":
            self.emit("jmp", e.line, targets=[l_true if e.value != 0 else l_false])
            return
        v = self.gen_expr(e)
        self.emit("br", e.line, args=[v], targets=[l_true, l_false])


def generate(program):
    return IRGen().gen_program(program)
