"""Abstract syntax tree for MiniC.

Every node carries its kind, source position and a small set of named
fields.  Fields that hold nodes (or lists of nodes) are the node's children;
scalar fields are attributes.  Semantic analysis decorates nodes with
synthesized attributes (`type`) and resolved symbols (`symbol`).
"""


class Node:
    __slots__ = ("kind", "line", "col", "fields", "type", "symbol", "uid")
    _counter = 0

    def __init__(self, kind, line, col, **fields):
        self.kind = kind
        self.line = line
        self.col = col
        self.fields = fields
        self.type = None
        self.symbol = None
        Node._counter += 1
        self.uid = Node._counter

    def __getattr__(self, name):
        try:
            return self.fields[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def children(self):
        out = []
        for key, value in self.fields.items():
            if isinstance(value, Node):
                out.append((key, value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        out.append((key, item))
        return out

    def label(self):
        k = self.kind
        f = self.fields
        if k == "Program":
            return "Program"
        if k == "GlobalVar":
            return f"global int {f['name']}" + (f"[{f['size']}]" if f["size"] is not None else "")
        if k == "Function":
            return f"function {f['ret_type']} {f['name']}"
        if k == "Param":
            return f"param int {f['name']}" + ("[]" if f["is_array"] else "")
        if k == "VarDecl":
            return f"int {f['name']}" + (f"[{f['size']}]" if f["size"] is not None else "")
        if k == "Assign":
            return f"assign {f['op']}"
        if k in ("Binary", "Unary"):
            return f["op"]
        if k == "Num":
            return str(f["value"])
        if k == "Var":
            return f["name"]
        if k == "Index":
            return f"{f['name']}[ ]"
        if k == "Call":
            return f"call {f['name']}"
        return k

    def to_dict(self):
        return {
            "id": self.uid,
            "kind": self.kind,
            "label": self.label(),
            "line": self.line,
            "col": self.col,
            "type": self.type,
            "children": [dict(child.to_dict(), edge=key) for key, child in self.children()],
        }
