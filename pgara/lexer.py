"""Lexical analysis for MiniC.

The scanner is a hand-coded deterministic finite automaton driven by the
maximal-munch rule: at every position it consumes the longest prefix that
matches one of the regular definitions below, and keywords are separated
from identifiers by a reserved-word table lookup after the identifier DFA
accepts.

    letter  -> [A-Za-z_]
    digit   -> [0-9]
    ID      -> letter (letter | digit)*
    NUM     -> digit+
    OP      -> '+' | '-' | '*' | '/' | '%' | '<' | '<=' | '>' | '>=' | '==' | '!='
             | '&&' | '||' | '!' | '=' | '+=' | '-=' | '*=' | '++' | '--'
    PUNCT   -> '(' | ')' | '{' | '}' | '[' | ']' | ';' | ','
    COMMENT -> '//' [^\\n]* | '/*' .*? '*/'
"""

from dataclasses import dataclass

KEYWORDS = {
    "int", "void", "if", "else", "while", "for", "return",
    "break", "continue", "print", "input",
}

# Longest operators first so that maximal munch is a simple prefix test.
OPERATORS = [
    "<=", ">=", "==", "!=", "&&", "||", "+=", "-=", "*=", "++", "--",
    "+", "-", "*", "/", "%", "<", ">", "!", "=",
]
PUNCTUATION = ["(", ")", "{", "}", "[", "]", ";", ","]

INT_MAX = 2 ** 31 - 1


@dataclass
class Token:
    kind: str      # 'ID', 'NUM', 'KW', 'OP', 'PUNCT', 'EOF'
    lexeme: str
    line: int
    col: int

    @property
    def tag(self):
        """Terminal symbol used by the grammar (keywords and symbols are their own terminals)."""
        if self.kind in ("KW", "OP", "PUNCT"):
            return self.lexeme
        if self.kind == "EOF":
            return "$"
        return self.kind

    def to_dict(self):
        return {"kind": self.kind, "lexeme": self.lexeme, "line": self.line, "col": self.col}


class LexError(Exception):
    def __init__(self, message, line, col):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


def tokenize(source):
    """Return (tokens, errors). Lexical errors are recorded and the offending
    character is skipped so that scanning can continue (panic-mode recovery)."""
    tokens = []
    errors = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    def advance(count):
        nonlocal i, line, col
        for _ in range(count):
            if source[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            advance(1)
            continue
        if source.startswith("//", i):
            while i < n and source[i] != "\n":
                advance(1)
            continue
        if source.startswith("/*", i):
            start_line, start_col = line, col
            end = source.find("*/", i + 2)
            if end < 0:
                errors.append(LexError("unterminated block comment", start_line, start_col))
                advance(n - i)
            else:
                advance(end + 2 - i)
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            lexeme = source[i:j]
            kind = "KW" if lexeme in KEYWORDS else "ID"
            tokens.append(Token(kind, lexeme, line, col))
            advance(j - i)
            continue
        if ch.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            lexeme = source[i:j]
            if j < n and (source[j].isalpha() or source[j] == "_"):
                k = j
                while k < n and (source[k].isalnum() or source[k] == "_"):
                    k += 1
                errors.append(LexError(f"malformed number '{source[i:k]}'", line, col))
                advance(k - i)
                continue
            if int(lexeme) > INT_MAX:
                errors.append(LexError(f"integer literal {lexeme} exceeds 32-bit range", line, col))
            tokens.append(Token("NUM", lexeme, line, col))
            advance(j - i)
            continue
        matched = None
        for op in OPERATORS:
            if source.startswith(op, i):
                matched = ("OP", op)
                break
        if matched is None and ch in PUNCTUATION:
            matched = ("PUNCT", ch)
        if matched is None:
            errors.append(LexError(f"unexpected character '{ch}'", line, col))
            advance(1)
            continue
        tokens.append(Token(matched[0], matched[1], line, col))
        advance(len(matched[1]))

    tokens.append(Token("EOF", "", line, col))
    return tokens, errors
