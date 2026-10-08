"""The MiniC context-free grammar in LL(1) form, with mechanical FIRST/FOLLOW
computation and predictive-table construction.

The recursive-descent parser in parser.py is a direct transcription of these
productions; this module lets the toolchain (and the GUI) verify that the
grammar is LL(1).  The only table conflict is the classical dangling-else on
(ElsePart, 'else'), which is resolved in favour of ElsePart -> else Stmt so
that an 'else' binds to the nearest unmatched 'if'.
"""

import re

EPS = "ε"
END = "$"

GRAMMAR_TEXT = """
Program    -> DeclList
DeclList   -> Decl DeclList | ε
Decl       -> Type ID DeclTail
Type       -> int | void
DeclTail   -> ( Params ) Block | ArrSpec ;
ArrSpec    -> [ NUM ] | ε
Params     -> Param ParamRest | ε
ParamRest  -> , Param ParamRest | ε
Param      -> int ID ParamArr
ParamArr   -> [ ] | ε
Block      -> { StmtList }
StmtList   -> Stmt StmtList | ε
Stmt       -> VarDecl | if ( Expr ) Stmt ElsePart | while ( Expr ) Stmt | for ( ForInit ; OptExpr ; ForStep ) Stmt | return OptExpr ; | break ; | continue ; | print ( Expr ) ; | Block | Simple ;
VarDecl    -> int ID VarTail ;
VarTail    -> [ NUM ] | = Expr | ε
ElsePart   -> else Stmt | ε
ForInit    -> int ID = Expr | Simple | ε
ForStep    -> Simple | ε
OptExpr    -> Expr | ε
Simple     -> ID SimpleTail
SimpleTail -> AssignOp Expr | ++ | -- | [ Expr ] AssignOp Expr | ( Args )
AssignOp   -> = | += | -= | *=
Args       -> Expr ArgRest | ε
ArgRest    -> , Expr ArgRest | ε
Expr       -> Or
Or         -> And OrRest
OrRest     -> || And OrRest | ε
And        -> Eq AndRest
AndRest    -> && Eq AndRest | ε
Eq         -> Rel EqRest
EqRest     -> == Rel EqRest | != Rel EqRest | ε
Rel        -> Add RelRest
RelRest    -> RelOp Add | ε
RelOp      -> < | <= | > | >=
Add        -> Mul AddRest
AddRest    -> + Mul AddRest | - Mul AddRest | ε
Mul        -> Unary MulRest
MulRest    -> * Unary MulRest | / Unary MulRest | % Unary MulRest | ε
Unary      -> - Unary | ! Unary | Primary
Primary    -> NUM | ID PrimTail | ( Expr ) | input ( )
PrimTail   -> [ Expr ] | ( Args ) | ε
"""


def parse_grammar(text=GRAMMAR_TEXT):
    productions = []          # list of (lhs, [symbols])
    order = []
    for raw in text.strip().splitlines():
        lhs, rhs = raw.split("->")
        lhs = lhs.strip()
        order.append(lhs)
        for alt in re.split(r"\s\|\s", " " + rhs + " "):
            symbols = alt.split()
            if symbols == [EPS]:
                symbols = []
            productions.append((lhs, symbols))
    return order, productions


def compute_first_follow(order, productions):
    nonterminals = set(order)
    first = {a: set() for a in nonterminals}

    def first_of_seq(seq):
        out = set()
        for sym in seq:
            if sym not in nonterminals:
                out.add(sym)
                return out
            out |= first[sym] - {EPS}
            if EPS not in first[sym]:
                return out
        out.add(EPS)
        return out

    changed = True
    while changed:
        changed = False
        for lhs, rhs in productions:
            f = first_of_seq(rhs)
            if not f <= first[lhs]:
                first[lhs] |= f
                changed = True

    follow = {a: set() for a in nonterminals}
    follow[order[0]].add(END)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in productions:
            for i, sym in enumerate(rhs):
                if sym not in nonterminals:
                    continue
                tail = first_of_seq(rhs[i + 1:])
                add = (tail - {EPS}) | (follow[lhs] if EPS in tail else set())
                if not add <= follow[sym]:
                    follow[sym] |= add
                    changed = True
    return first, follow, first_of_seq


def build_ll1_table():
    order, productions = parse_grammar()
    first, follow, first_of_seq = compute_first_follow(order, productions)
    table = {}
    conflicts = []
    for idx, (lhs, rhs) in enumerate(productions):
        f = first_of_seq(rhs)
        lookaheads = (f - {EPS}) | (follow[lhs] if EPS in f else set())
        for a in lookaheads:
            key = (lhs, a)
            if key in table and table[key] != idx:
                conflicts.append({
                    "nonterminal": lhs,
                    "lookahead": a,
                    "productions": [fmt_production(productions[table[key]]), fmt_production((lhs, rhs))],
                })
                # Dangling else: keep the production that consumes 'else'.
                if rhs and rhs[0] == a:
                    table[key] = idx
            else:
                table[key] = idx
    return {
        "order": order,
        "productions": productions,
        "first": first,
        "follow": follow,
        "table": table,
        "conflicts": conflicts,
    }


def fmt_production(prod):
    lhs, rhs = prod
    return f"{lhs} -> {' '.join(rhs) if rhs else EPS}"


def grammar_report():
    """JSON-friendly summary for the GUI and the test-suite."""
    g = build_ll1_table()
    nts = g["order"]
    terminals = sorted({s for _, rhs in g["productions"] for s in rhs if s not in nts} | {END})
    return {
        "productions": [fmt_production(p) for p in g["productions"]],
        "nonterminals": nts,
        "terminals": terminals,
        "first": {a: sorted(g["first"][a]) for a in nts},
        "follow": {a: sorted(g["follow"][a]) for a in nts},
        "table": [
            {"nonterminal": a, "lookahead": t, "production": fmt_production(g["productions"][i])}
            for (a, t), i in sorted(g["table"].items())
        ],
        "conflicts": g["conflicts"],
        "is_ll1_modulo_dangling_else": all(
            c["nonterminal"] == "ElsePart" and c["lookahead"] == "else" for c in g["conflicts"]
        ),
    }
