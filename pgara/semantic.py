"""Semantic analysis: scope resolution, symbol-table construction and type
checking for MiniC.

The analysis is an L-attributed traversal of the AST.  The environment
(the chain of open scopes) is an inherited attribute flowing top-down and
left-to-right; every expression synthesizes a `type` attribute from the types
of its children.  The symbol table is a stack of hash maps (one per open
scope); a lookup walks the stack from the innermost scope outwards, which
implements static (lexical) scoping with shadowing.  Every scope that was
ever opened is retained so that the GUI can show the complete table.
"""

from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    uname: str            # unique name used in the intermediate representation
    kind: str             # var | array | param | array_param | global | global_array | func
    type: str             # int | int[] | void | function signature
    scope: int
    line: int
    col: int
    size: int = None
    params: list = field(default_factory=list)   # for functions: list of 'int' / 'int[]'
    ret_type: str = None
    uses: int = 0

    @property
    def is_array(self):
        return self.kind in ("array", "array_param", "global_array")

    @property
    def is_scalar(self):
        return self.kind in ("var", "param", "global")

    def to_dict(self):
        return {
            "name": self.name,
            "uname": self.uname,
            "kind": self.kind,
            "type": self.type,
            "scope": self.scope,
            "line": self.line,
            "size": self.size,
            "uses": self.uses,
        }


@dataclass
class Scope:
    sid: int
    name: str
    parent: int
    level: int
    line: int
    symbols: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.sid,
            "name": self.name,
            "parent": self.parent,
            "level": self.level,
            "line": self.line,
            "symbols": [s.to_dict() for s in self.symbols.values()],
        }


class Diagnostic:
    def __init__(self, severity, message, line, col):
        self.severity = severity
        self.message = message
        self.line = line
        self.col = col

    def to_dict(self):
        return {"phase": "semantic", "severity": self.severity, "message": self.message,
                "line": self.line, "col": self.col}


class SymbolTable:
    def __init__(self):
        self.scopes = []
        self.stack = []
        self.name_counts = {}

    def open(self, name, line):
        parent = self.stack[-1].sid if self.stack else None
        scope = Scope(len(self.scopes), name, parent, len(self.stack), line)
        self.scopes.append(scope)
        self.stack.append(scope)
        return scope

    def close(self):
        self.stack.pop()

    def lookup(self, name):
        for scope in reversed(self.stack):
            if name in scope.symbols:
                return scope.symbols[name]
        return None

    def lookup_current(self, name):
        return self.stack[-1].symbols.get(name)

    def fresh_uname(self, name):
        count = self.name_counts.get(name, 0)
        self.name_counts[name] = count + 1
        return name if count == 0 else f"{name}#{count}"

    def declare(self, sym):
        self.stack[-1].symbols[sym.name] = sym
        return sym


class Analyzer:
    def __init__(self):
        self.table = SymbolTable()
        self.diags = []
        self.functions = {}
        self.current_fn = None
        self.loop_depth = 0

    def error(self, msg, node):
        self.diags.append(Diagnostic("error", msg, node.line, node.col))

    def warn(self, msg, node):
        self.diags.append(Diagnostic("warning", msg, node.line, node.col))

    # -- program level ---------------------------------------------------
    def analyze(self, program):
        self.table.open("global", program.line)
        # Pass 1: declare every function signature so calls may precede definitions.
        for decl in program.decls:
            if decl.kind == "Function":
                if self.table.lookup_current(decl.name):
                    self.error(f"redefinition of '{decl.name}'", decl)
                    continue
                sig = ["int[]" if p.is_array else "int" for p in decl.params]
                sym = Symbol(decl.name, decl.name, "func", f"{decl.ret_type}({', '.join(sig)})",
                             0, decl.line, decl.col, params=sig, ret_type=decl.ret_type)
                self.table.declare(sym)
                self.functions[decl.name] = sym
                decl.symbol = sym
        # Pass 2: globals in order, function bodies in order.
        for decl in program.decls:
            if decl.kind == "GlobalVar":
                self.declare_global(decl)
            elif decl.kind == "Function" and decl.symbol is not None:
                self.analyze_function(decl)
        main = self.functions.get("main")
        if main is None:
            self.diags.append(Diagnostic("error", "program has no 'main' function", 1, 1))
        else:
            if main.params:
                self.error("'main' must not take parameters", main)
            if main.ret_type != "int":
                self.error("'main' must return int", main)
        for scope in self.table.scopes[1:]:
            for sym in scope.symbols.values():
                if sym.kind in ("var", "array") and sym.uses == 0:
                    self.diags.append(Diagnostic("warning", f"variable '{sym.name}' is never used", sym.line, sym.col))
        self.table.close()

    def declare_global(self, decl):
        if decl.decl_type != "int":
            self.error(f"global variable '{decl.name}' must have type int", decl)
        if self.table.lookup_current(decl.name):
            self.error(f"redefinition of '{decl.name}'", decl)
            return
        if decl.size is not None and decl.size <= 0:
            self.error(f"array '{decl.name}' must have a positive size", decl)
        kind = "global_array" if decl.size is not None else "global"
        sym = Symbol(decl.name, self.table.fresh_uname(decl.name), kind,
                     "int[]" if decl.size is not None else "int", 0, decl.line, decl.col, size=decl.size)
        decl.symbol = self.table.declare(sym)

    def analyze_function(self, fn):
        self.current_fn = fn.symbol
        self.table.open(f"function {fn.name}", fn.line)
        for p in fn.params:
            if self.table.lookup_current(p.name):
                self.error(f"duplicate parameter '{p.name}'", p)
                continue
            kind = "array_param" if p.is_array else "param"
            sym = Symbol(p.name, self.table.fresh_uname(p.name), kind, "int[]" if p.is_array else "int",
                         self.table.stack[-1].sid, p.line, p.col)
            p.symbol = self.table.declare(sym)
        # The body block shares the parameter scope, as in C.
        self.analyze_stmts(fn.body.stmts)
        if fn.ret_type == "int" and not self.always_returns(fn.body):
            self.warn(f"control may reach the end of non-void function '{fn.name}' (returns 0)", fn)
        self.table.close()
        self.current_fn = None

    def always_returns(self, stmt):
        if stmt is None:
            return False
        k = stmt.kind
        if k == "Return":
            return True
        if k == "Block":
            return any(self.always_returns(s) for s in stmt.stmts)
        if k == "If":
            return self.always_returns(stmt.then) and self.always_returns(stmt.other)
        return False

    # -- statements -------------------------------------------------------
    def analyze_stmts(self, stmts):
        for s in stmts:
            self.analyze_stmt(s)

    def analyze_stmt(self, s):
        k = s.kind
        if k == "Block":
            self.table.open("block", s.line)
            self.analyze_stmts(s.stmts)
            self.table.close()
        elif k == "VarDecl":
            if s.init is not None:
                self.expect_int(s.init)
            if self.table.lookup_current(s.name):
                self.error(f"redeclaration of '{s.name}' in the same scope", s)
                return
            if s.size is not None and s.size <= 0:
                self.error(f"array '{s.name}' must have a positive size", s)
            kind = "array" if s.size is not None else "var"
            sym = Symbol(s.name, self.table.fresh_uname(s.name), kind, "int[]" if s.size is not None else "int",
                         self.table.stack[-1].sid, s.line, s.col, size=s.size)
            s.symbol = self.table.declare(sym)
        elif k == "If":
            self.expect_int(s.cond)
            self.scoped(s.then)
            if s.other is not None:
                self.scoped(s.other)
        elif k == "While":
            self.expect_int(s.cond)
            self.loop_depth += 1
            self.scoped(s.body)
            self.loop_depth -= 1
        elif k == "For":
            self.table.open("for", s.line)
            if s.init is not None:
                self.analyze_stmt(s.init)
            if s.cond is not None:
                self.expect_int(s.cond)
            if s.step is not None:
                self.analyze_stmt(s.step)
            self.loop_depth += 1
            self.scoped(s.body)
            self.loop_depth -= 1
            self.table.close()
        elif k == "Return":
            rt = self.current_fn.ret_type
            if s.value is None and rt == "int":
                self.error("non-void function must return a value", s)
            elif s.value is not None:
                if rt == "void":
                    self.error("void function cannot return a value", s)
                self.expect_int(s.value)
        elif k in ("Break", "Continue"):
            if self.loop_depth == 0:
                self.error(f"'{k.lower()}' outside of a loop", s)
        elif k == "Print":
            self.expect_int(s.value)
        elif k == "Assign":
            self.analyze_assign(s)
        elif k == "ExprStmt":
            self.analyze_call(s.expr, as_statement=True)

    def scoped(self, stmt):
        """A non-block statement body still gets its own scope (C semantics)."""
        if stmt.kind == "Block":
            self.analyze_stmt(stmt)
        else:
            self.table.open("block", stmt.line)
            self.analyze_stmt(stmt)
            self.table.close()

    def analyze_assign(self, s):
        target = s.target
        sym = self.table.lookup(target.name)
        if sym is None:
            self.error(f"assignment to undeclared variable '{target.name}'", target)
        elif sym.kind == "func":
            self.error(f"cannot assign to function '{target.name}'", target)
        elif target.kind == "Var" and not sym.is_scalar:
            self.error(f"cannot assign to array '{target.name}' as a whole", target)
        elif target.kind == "Index" and not sym.is_array:
            self.error(f"'{target.name}' is not an array", target)
        else:
            target.symbol = sym
            sym.uses += 1
            target.type = "int"
        if target.kind == "Index":
            self.expect_int(target.index)
        self.expect_int(s.value)

    # -- expressions ------------------------------------------------------
    def expect_int(self, e):
        t = self.expr(e)
        if t not in ("int", None):
            self.error(f"expected an int value but found {t}", e)

    def expr(self, e):
        k = e.kind
        if k == "Num":
            if not (-2 ** 31 <= e.value <= 2 ** 31 - 1):
                self.error("integer literal out of 32-bit range", e)
            e.type = "int"
        elif k == "Var":
            sym = self.table.lookup(e.name)
            if sym is None:
                self.error(f"use of undeclared identifier '{e.name}'", e)
                return None
            if sym.kind == "func":
                self.error(f"function '{e.name}' used as a value", e)
                return None
            e.symbol = sym
            sym.uses += 1
            e.type = sym.type
        elif k == "Index":
            sym = self.table.lookup(e.name)
            if sym is None:
                self.error(f"use of undeclared identifier '{e.name}'", e)
            elif not sym.is_array:
                self.error(f"'{e.name}' is not an array", e)
            else:
                e.symbol = sym
                sym.uses += 1
            self.expect_int(e.index)
            e.type = "int"
        elif k == "Binary":
            self.expect_int(e.left)
            self.expect_int(e.right)
            if e.op in ("/", "%") and e.right.kind == "Num" and e.right.value == 0:
                self.warn("division by constant zero", e)
            e.type = "int"
        elif k == "Unary":
            self.expect_int(e.operand)
            e.type = "int"
        elif k == "Call":
            e.type = self.analyze_call(e, as_statement=False)
        elif k == "Input":
            e.type = "int"
        return e.type

    def analyze_call(self, call, as_statement):
        sym = self.table.lookup(call.name)
        if sym is None or sym.kind != "func":
            self.error(f"call to undeclared function '{call.name}'", call)
            for a in call.args:
                self.expr(a)
            return None
        call.symbol = sym
        sym.uses += 1
        if len(call.args) != len(sym.params):
            self.error(f"'{call.name}' expects {len(sym.params)} argument(s) but got {len(call.args)}", call)
        for arg, ptype in zip(call.args, sym.params + [None] * len(call.args)):
            atype = self.expr(arg)
            if ptype == "int[]":
                if arg.kind != "Var" or atype != "int[]":
                    self.error(f"argument to '{call.name}' must be an array name", arg)
            elif ptype == "int" and atype not in ("int", None):
                self.error(f"argument to '{call.name}' must be an int, not {atype}", arg)
        if not as_statement and sym.ret_type == "void":
            self.error(f"void function '{call.name}' used in an expression", call)
            return None
        call.type = sym.ret_type
        return sym.ret_type


def analyze(program):
    a = Analyzer()
    a.analyze(program)
    return a
