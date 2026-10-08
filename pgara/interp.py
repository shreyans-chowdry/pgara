"""Reference interpreter for the TAC/SSA representation, doubling as the
edge profiler.

It defines the run-time environment of MiniC: a flat word-addressed memory,
globals allocated statically at the bottom, and a stack of activation
records whose local arrays are allocated on entry and released on return.
Array accesses are bounds-checked.  While executing, it counts how often
every CFG edge is taken; these counts become the transition probabilities
of PGARA's Markov decision processes.
"""

from .ir import eval_binop, eval_unop, BINOPS, UNOPS, RuntimeFault

MAX_CALL_DEPTH = 2000


class ExecutionResult:
    def __init__(self):
        self.output = []
        self.return_value = None
        self.error = None
        self.steps = 0
        self.edge_counts = {}     # fn -> {(src, dst): count}
        self.block_counts = {}    # fn -> {block: count}
        self.calls = {}           # fn -> count

    def to_dict(self):
        return {
            "output": self.output,
            "return_value": self.return_value,
            "error": self.error,
            "steps": self.steps,
        }


class Interpreter:
    def __init__(self, module, inputs=None, step_limit=5_000_000):
        self.module = module
        self.inputs = list(inputs or [])
        self.input_pos = 0
        self.step_limit = step_limit
        self.mem = []
        self.alloc = {}           # base address -> size
        self.global_addr = {}
        self.result = ExecutionResult()
        self.depth = 0
        for name, size in module.globals.items():
            self.global_addr[name] = self.allocate(size if size is not None else 1)
        self.prepared = {}
        for fname, fn in module.functions.items():
            self.prepared[fname] = {b.name: b for b in fn.blocks}

    def allocate(self, size):
        base = len(self.mem)
        self.mem.extend([0] * size)
        self.alloc[base] = size
        return base

    def check(self, base, idx):
        size = self.alloc.get(base)
        if size is None:
            raise RuntimeFault(f"invalid array base address {base}")
        if not 0 <= idx < size:
            raise RuntimeFault(f"array index {idx} out of bounds [0, {size})")
        return base + idx

    def run(self):
        try:
            if "main" not in self.module.functions:
                raise RuntimeFault("no main function")
            self.result.return_value = self.call("main", [])
        except RuntimeFault as exc:
            self.result.error = str(exc)
        except RecursionError:
            self.result.error = "call stack overflow"
        return self.result

    def call(self, fname, args):
        fn = self.module.functions[fname]
        blocks = self.prepared[fname]
        self.depth += 1
        if self.depth > MAX_CALL_DEPTH:
            raise RuntimeFault("call stack overflow")
        r = self.result
        r.calls[fname] = r.calls.get(fname, 0) + 1
        edges = r.edge_counts.setdefault(fname, {})
        bcounts = r.block_counts.setdefault(fname, {})
        mark = len(self.mem)
        arrays = {name: self.allocate(size) for name, size in fn.local_arrays.items()}
        env = {}
        prev = None
        bname = fn.blocks[0].name
        mem = self.mem
        while True:
            block = blocks[bname]
            bcounts[bname] = bcounts.get(bname, 0) + 1
            if prev is not None:
                key = (prev, bname)
                edges[key] = edges.get(key, 0) + 1
            instrs = block.instrs
            # Phi functions read their operands simultaneously on block entry.
            phi_vals = []
            for ins in instrs:
                if ins.op != "phi":
                    break
                v = ins.phi.get(prev, 0)
                phi_vals.append((ins.dst, env.get(v, 0) if isinstance(v, str) else v))
            for d, v in phi_vals:
                env[d] = v
            next_block = None
            for ins in instrs:
                op = ins.op
                if op == "phi":
                    continue
                r.steps += 1
                if r.steps > self.step_limit:
                    raise RuntimeFault(f"step limit of {self.step_limit} instructions exceeded")
                a = [env[x] if isinstance(x, str) else x for x in ins.args]
                if op in BINOPS:
                    env[ins.dst] = eval_binop(op, a[0], a[1])
                elif op == "const" or op == "copy":
                    env[ins.dst] = a[0]
                elif op in UNOPS:
                    env[ins.dst] = eval_unop(op, a[0])
                elif op == "aload":
                    env[ins.dst] = mem[self.check(a[0], a[1])]
                elif op == "astore":
                    mem[self.check(a[0], a[1])] = a[2]
                elif op == "addr":
                    env[ins.dst] = arrays[ins.sym] if ins.sym in arrays else self.global_addr[ins.sym]
                elif op == "gload":
                    env[ins.dst] = mem[self.global_addr[ins.sym]]
                elif op == "gstore":
                    mem[self.global_addr[ins.sym]] = a[0]
                elif op == "param":
                    env[ins.dst] = args[ins.args[0]]
                elif op == "call":
                    v = self.call(ins.sym, a)
                    if ins.dst is not None:
                        env[ins.dst] = v if v is not None else 0
                elif op == "input":
                    if self.input_pos < len(self.inputs):
                        env[ins.dst] = self.inputs[self.input_pos]
                        self.input_pos += 1
                    else:
                        env[ins.dst] = 0
                elif op == "print":
                    r.output.append(a[0])
                elif op == "jmp":
                    next_block = ins.targets[0]
                elif op == "br":
                    next_block = ins.targets[0] if a[0] != 0 else ins.targets[1]
                elif op == "cbr":
                    next_block = ins.targets[0] if eval_binop(ins.relop, a[0], a[1]) else ins.targets[1]
                elif op == "ret":
                    del self.mem[mark:]
                    for base in arrays.values():
                        self.alloc.pop(base, None)
                    self.depth -= 1
                    return a[0] if a else None
                else:
                    raise RuntimeFault(f"unknown opcode {op}")
            prev = bname
            bname = next_block


def run(module, inputs=None, step_limit=5_000_000):
    return Interpreter(module, inputs, step_limit).run()
