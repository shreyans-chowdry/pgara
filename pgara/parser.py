"""Predictive recursive-descent parser for MiniC.

Each method corresponds to one nonterminal of the LL(1) grammar in
grammar.py and chooses its production from a single token of lookahead.
Left-recursive expression rules were eliminated in the grammar (E -> T E'),
and the parser rebuilds left-associative trees while iterating over the
E' tails.  Syntax errors use panic-mode recovery: the parser records the
error, discards tokens up to a synchronising token (';', '}' or a statement
keyword) and resumes, so several errors are reported per compilation.
"""

from .ast import Node
from .lexer import Token

STMT_START = {"int", "if", "while", "for", "return", "break", "continue", "print", "{"}
SYNC = {";", "}", "$"} | STMT_START


class ParseError(Exception):
    def __init__(self, message, line, col):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.errors = []

    # -- token helpers -------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def at(self, *tags):
        return self.tok.tag in tags

    def advance(self):
        t = self.tok
        if t.kind != "EOF":
            self.pos += 1
        return t

    def expect(self, tag, what=None):
        if self.tok.tag == tag:
            return self.advance()
        found = self.tok.lexeme or "end of input"
        raise ParseError(f"expected {what or repr(tag)} but found '{found}'", self.tok.line, self.tok.col)

    def synchronize(self):
        while not self.at(*SYNC):
            self.advance()
        if self.at(";"):
            self.advance()

    # -- Program / declarations ---------------------------------------
    def parse_program(self):
        decls = []
        start = self.tok
        while not self.at("$"):
            try:
                decls.append(self.parse_decl())
            except ParseError as err:
                self.errors.append(err)
                self.synchronize()
                if self.at("}"):
                    self.advance()
        return Node("Program", start.line, start.col, decls=decls)

    def parse_decl(self):
        t = self.tok
        if not self.at("int", "void"):
            raise ParseError(f"expected a declaration but found '{t.lexeme or 'end of input'}'", t.line, t.col)
        rtype = self.advance().lexeme
        name = self.expect("ID", "an identifier").lexeme
        if self.at("("):
            self.advance()
            params = self.parse_params()
            self.expect(")")
            body = self.parse_block()
            return Node("Function", t.line, t.col, ret_type=rtype, name=name, params=params, body=body)
        size = self.parse_arrspec()
        self.expect(";")
        return Node("GlobalVar", t.line, t.col, name=name, size=size, decl_type=rtype)

    def parse_arrspec(self):
        if self.at("["):
            self.advance()
            num = self.expect("NUM", "an array size")
            self.expect("]")
            return int(num.lexeme)
        return None

    def parse_params(self):
        params = []
        if self.at("int"):
            params.append(self.parse_param())
            while self.at(","):
                self.advance()
                params.append(self.parse_param())
        return params

    def parse_param(self):
        t = self.expect("int", "'int'")
        name = self.expect("ID", "a parameter name").lexeme
        is_array = False
        if self.at("["):
            self.advance()
            self.expect("]")
            is_array = True
        return Node("Param", t.line, t.col, name=name, is_array=is_array)

    # -- Statements ------------------------------------------------------
    def parse_block(self):
        t = self.expect("{")
        stmts = []
        while not self.at("}", "$"):
            try:
                stmts.append(self.parse_stmt())
            except ParseError as err:
                self.errors.append(err)
                self.synchronize()
        self.expect("}")
        return Node("Block", t.line, t.col, stmts=stmts)

    def parse_stmt(self):
        t = self.tok
        tag = t.tag
        if tag == "int":
            return self.parse_vardecl()
        if tag == "if":
            self.advance()
            self.expect("(")
            cond = self.parse_expr()
            self.expect(")")
            then = self.parse_stmt()
            other = None
            if self.at("else"):
                self.advance()
                other = self.parse_stmt()
            return Node("If", t.line, t.col, cond=cond, then=then, other=other)
        if tag == "while":
            self.advance()
            self.expect("(")
            cond = self.parse_expr()
            self.expect(")")
            body = self.parse_stmt()
            return Node("While", t.line, t.col, cond=cond, body=body)
        if tag == "for":
            self.advance()
            self.expect("(")
            init = None
            if self.at("int"):
                it = self.advance()
                name = self.expect("ID", "an identifier").lexeme
                self.expect("=")
                value = self.parse_expr()
                init = Node("VarDecl", it.line, it.col, name=name, size=None, init=value)
            elif self.at("ID"):
                init = self.parse_simple()
            self.expect(";")
            cond = None if self.at(";") else self.parse_expr()
            self.expect(";")
            step = self.parse_simple() if self.at("ID") else None
            self.expect(")")
            body = self.parse_stmt()
            return Node("For", t.line, t.col, init=init, cond=cond, step=step, body=body)
        if tag == "return":
            self.advance()
            value = None if self.at(";") else self.parse_expr()
            self.expect(";")
            return Node("Return", t.line, t.col, value=value)
        if tag == "break":
            self.advance()
            self.expect(";")
            return Node("Break", t.line, t.col)
        if tag == "continue":
            self.advance()
            self.expect(";")
            return Node("Continue", t.line, t.col)
        if tag == "print":
            self.advance()
            self.expect("(")
            value = self.parse_expr()
            self.expect(")")
            self.expect(";")
            return Node("Print", t.line, t.col, value=value)
        if tag == "{":
            return self.parse_block()
        if tag == "ID":
            stmt = self.parse_simple()
            self.expect(";")
            return stmt
        raise ParseError(f"unexpected '{t.lexeme or 'end of input'}' at start of statement", t.line, t.col)

    def parse_vardecl(self):
        t = self.expect("int")
        name = self.expect("ID", "an identifier").lexeme
        size = None
        init = None
        if self.at("["):
            size = self.parse_arrspec()
        elif self.at("="):
            self.advance()
            init = self.parse_expr()
        self.expect(";")
        return Node("VarDecl", t.line, t.col, name=name, size=size, init=init)

    def parse_simple(self):
        t = self.expect("ID", "an identifier")
        if self.at("=", "+=", "-=", "*="):
            op = self.advance().lexeme
            value = self.parse_expr()
            target = Node("Var", t.line, t.col, name=t.lexeme)
            return Node("Assign", t.line, t.col, target=target, op=op, value=value)
        if self.at("++", "--"):
            op = "+=" if self.advance().lexeme == "++" else "-="
            target = Node("Var", t.line, t.col, name=t.lexeme)
            one = Node("Num", t.line, t.col, value=1)
            return Node("Assign", t.line, t.col, target=target, op=op, value=one)
        if self.at("["):
            self.advance()
            index = self.parse_expr()
            self.expect("]")
            if not self.at("=", "+=", "-=", "*="):
                raise ParseError("expected an assignment operator after array element", self.tok.line, self.tok.col)
            op = self.advance().lexeme
            value = self.parse_expr()
            target = Node("Index", t.line, t.col, name=t.lexeme, index=index)
            return Node("Assign", t.line, t.col, target=target, op=op, value=value)
        if self.at("("):
            self.advance()
            args = self.parse_args()
            self.expect(")")
            call = Node("Call", t.line, t.col, name=t.lexeme, args=args)
            return Node("ExprStmt", t.line, t.col, expr=call)
        raise ParseError(f"expected '=', '++', '--', '[' or '(' after '{t.lexeme}'", self.tok.line, self.tok.col)

    def parse_args(self):
        args = []
        if not self.at(")"):
            args.append(self.parse_expr())
            while self.at(","):
                self.advance()
                args.append(self.parse_expr())
        return args

    # -- Expressions (one method per precedence level) -------------------
    def parse_expr(self):
        return self.parse_or()

    def _left_assoc(self, sub, ops):
        left = sub()
        while self.at(*ops):
            t = self.advance()
            right = sub()
            left = Node("Binary", t.line, t.col, op=t.lexeme, left=left, right=right)
        return left

    def parse_or(self):
        return self._left_assoc(self.parse_and, ("||",))

    def parse_and(self):
        return self._left_assoc(self.parse_eq, ("&&",))

    def parse_eq(self):
        return self._left_assoc(self.parse_rel, ("==", "!="))

    def parse_rel(self):
        left = self.parse_add()
        if self.at("<", "<=", ">", ">="):
            t = self.advance()
            right = self.parse_add()
            left = Node("Binary", t.line, t.col, op=t.lexeme, left=left, right=right)
        return left

    def parse_add(self):
        return self._left_assoc(self.parse_mul, ("+", "-"))

    def parse_mul(self):
        return self._left_assoc(self.parse_unary, ("*", "/", "%"))

    def parse_unary(self):
        if self.at("-", "!"):
            t = self.advance()
            operand = self.parse_unary()
            if t.lexeme == "-" and operand.kind == "Num":
                return Node("Num", t.line, t.col, value=-operand.value)
            return Node("Unary", t.line, t.col, op=t.lexeme, operand=operand)
        return self.parse_primary()

    def parse_primary(self):
        t = self.tok
        if self.at("NUM"):
            self.advance()
            return Node("Num", t.line, t.col, value=int(t.lexeme))
        if self.at("ID"):
            self.advance()
            if self.at("["):
                self.advance()
                index = self.parse_expr()
                self.expect("]")
                return Node("Index", t.line, t.col, name=t.lexeme, index=index)
            if self.at("("):
                self.advance()
                args = self.parse_args()
                self.expect(")")
                return Node("Call", t.line, t.col, name=t.lexeme, args=args)
            return Node("Var", t.line, t.col, name=t.lexeme)
        if self.at("("):
            self.advance()
            e = self.parse_expr()
            self.expect(")")
            return e
        if self.at("input"):
            self.advance()
            self.expect("(")
            self.expect(")")
            return Node("Input", t.line, t.col)
        raise ParseError(f"expected an expression but found '{t.lexeme or 'end of input'}'", t.line, t.col)


def parse(tokens):
    p = Parser(tokens)
    program = p.parse_program()
    return program, p.errors
