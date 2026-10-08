"""Cycle-counting simulator for PG-RISC target code.

It executes the code produced by codegen.py with the same memory model and
arithmetic semantics as the TAC interpreter, so that every allocation can be
checked end-to-end (the printed output must match the interpreter's) and
measured: dynamic instruction count, cycles under the cost model below,
loads, stores, and the subset of memory traffic caused by spilling and by
caller-saved registers around calls.
"""

from .ir import eval_binop, wrap32, RuntimeFault
from .regalloc import CostModel

ALU_OPS = {"add": "add", "sub": "sub", "mul": "mul", "div": "div", "rem": "mod",
           "slt": "lt", "sle": "le", "sgt": "gt", "sge": "ge", "seq": "eq", "sne": "ne"}
BRANCHES = {"blt": "lt", "ble": "le", "bgt": "gt", "bge": "ge", "beq": "eq", "bne": "ne"}

CYCLES = {
    "alu": 1, "mul": 3, "div": 12, "li": 1, "mv": 1, "la": 1,
    "load": CostModel.LOAD, "store": CostModel.STORE,
    "branch_taken": 2, "branch_not_taken": 1, "j": 1,
    "call": 3, "ret": 3, "enter": 1, "leave": 1, "io": 1,
}


class SimStats:
    def __init__(self):
        self.instructions = 0
        self.cycles = 0
        self.loads = 0
        self.stores = 0
        self.spill_loads = 0
        self.spill_stores = 0
        self.save_restore = 0
        self.value_accesses = 0
        self.output = []
        self.error = None
        self.return_value = None

    def to_dict(self):
        mem_served = self.spill_loads + self.spill_stores
        util = 1.0 - mem_served / self.value_accesses if self.value_accesses else 1.0
        return {
            "instructions": self.instructions,
            "cycles": self.cycles,
            "loads": self.loads,
            "stores": self.stores,
            "spill_loads": self.spill_loads,
            "spill_stores": self.spill_stores,
            "spill_memops": mem_served,
            "save_restore": self.save_restore,
            "value_accesses": self.value_accesses,
            "register_utilization": util,
            "output": self.output,
            "error": self.error,
            "return_value": self.return_value,
        }


class Simulator:
    def __init__(self, program, functions, globals_, inputs=None, step_limit=20_000_000):
        self.code = program
        self.functions = functions
        self.inputs = list(inputs or [])
        self.input_pos = 0
        self.step_limit = step_limit
        self.labels = {}
        for pc, ins in enumerate(program):
            if ins.op == "label":
                self.labels[ins.args[0]] = pc
        self.mem = []
        self.alloc = {}
        self.global_addr = {}
        for name, size in globals_.items():
            base = len(self.mem)
            n = size if size is not None else 1
            self.mem.extend([0] * n)
            if size is not None:
                self.alloc[base] = n
            self.global_addr[name] = base
        self.stats = SimStats()

    def run(self):
        st = self.stats
        regs = {"rv": 0, "t0": 0, "t1": 0, "t2": 0, "fp": 0}
        regs.update({f"r{i}": 0 for i in range(64)})
        mem = self.mem
        out_args = {}
        call_stack = []
        fp = len(mem)
        frame_fn = self.functions["main"]
        mem.extend([0] * frame_fn.frame_size)
        self.register_arrays(frame_fn, fp)
        pc = self.labels["main"]
        code = self.code
        try:
            while True:
                ins = code[pc]
                pc += 1
                op = ins.op
                if op == "label":
                    continue
                st.instructions += 1
                if st.instructions > self.step_limit:
                    raise RuntimeFault(f"step limit of {self.step_limit} instructions exceeded")
                st.value_accesses += ins.acc
                tag = ins.tag
                a = ins.args
                if op in ALU_OPS:
                    regs[a[0]] = eval_binop(ALU_OPS[op], regs[a[1]], regs[a[2]])
                    st.cycles += CYCLES["mul"] if op == "mul" else CYCLES["div"] if op in ("div", "rem") else CYCLES["alu"]
                elif op == "addi":
                    regs[a[0]] = wrap32(regs[a[1]] + a[2])
                    st.cycles += CYCLES["alu"]
                elif op == "li":
                    regs[a[0]] = a[1]
                    st.cycles += CYCLES["li"]
                elif op == "mv":
                    regs[a[0]] = regs[a[1]]
                    st.cycles += CYCLES["mv"]
                elif op == "neg":
                    regs[a[0]] = wrap32(-regs[a[1]])
                    st.cycles += CYCLES["alu"]
                elif op == "seqz":
                    regs[a[0]] = int(regs[a[1]] == 0)
                    st.cycles += CYCLES["alu"]
                elif op == "lw":
                    regs[a[0]] = mem[fp + a[1]]
                    st.loads += 1
                    st.cycles += CYCLES["load"]
                    if tag == "spill_load":
                        st.spill_loads += 1
                    elif tag == "restore":
                        st.save_restore += 1
                elif op == "sw":
                    mem[fp + a[1]] = regs[a[0]]
                    st.stores += 1
                    st.cycles += CYCLES["store"]
                    if tag == "spill_store":
                        st.spill_stores += 1
                    elif tag == "save":
                        st.save_restore += 1
                elif op == "lwg":
                    regs[a[0]] = mem[self.global_addr[a[1]]]
                    st.loads += 1
                    st.cycles += CYCLES["load"]
                elif op == "swg":
                    mem[self.global_addr[a[1]]] = regs[a[0]]
                    st.stores += 1
                    st.cycles += CYCLES["store"]
                elif op == "la":
                    regs[a[0]] = fp + a[1] if isinstance(a[1], int) else self.global_addr[a[1]]
                    st.cycles += CYCLES["la"]
                elif op == "lwx":
                    regs[a[0]] = mem[self.check(regs[a[1]], regs[a[2]])]
                    st.loads += 1
                    st.cycles += CYCLES["load"]
                elif op == "swx":
                    mem[self.check(regs[a[1]], regs[a[2]])] = regs[a[0]]
                    st.stores += 1
                    st.cycles += CYCLES["store"]
                elif op in BRANCHES:
                    if eval_binop(BRANCHES[op], regs[a[0]], regs[a[1]]):
                        pc = self.labels[a[2]]
                        st.cycles += CYCLES["branch_taken"]
                    else:
                        st.cycles += CYCLES["branch_not_taken"]
                elif op == "bnez":
                    if regs[a[0]] != 0:
                        pc = self.labels[a[1]]
                        st.cycles += CYCLES["branch_taken"]
                    else:
                        st.cycles += CYCLES["branch_not_taken"]
                elif op == "j":
                    pc = self.labels[a[0]]
                    st.cycles += CYCLES["j"]
                elif op == "arg":
                    out_args[a[0]] = regs[a[1]]
                    st.stores += 1
                    st.cycles += CYCLES["store"]
                elif op == "call":
                    callee = self.functions[a[0]]
                    if len(call_stack) > 2000:
                        raise RuntimeFault("call stack overflow")
                    call_stack.append((pc, fp, frame_fn))
                    new_fp = len(mem)
                    mem.extend([0] * callee.frame_size)
                    for i in range(callee.nparams):
                        mem[new_fp + i] = out_args.get(i, 0)
                    out_args = {}
                    fp = new_fp
                    frame_fn = callee
                    self.register_arrays(callee, fp)
                    pc = self.labels[a[0]]
                    st.cycles += CYCLES["call"]
                elif op == "enter":
                    st.cycles += CYCLES["enter"]
                elif op == "leave":
                    st.cycles += CYCLES["leave"]
                elif op == "ret":
                    st.cycles += CYCLES["ret"]
                    for off, _ in frame_fn.arrays.values():
                        self.alloc.pop(fp + off, None)
                    del mem[fp:]
                    if not call_stack:
                        st.return_value = regs["rv"]
                        break
                    pc, fp, frame_fn = call_stack.pop()
                elif op == "print":
                    st.output.append(regs[a[0]])
                    st.cycles += CYCLES["io"]
                elif op == "input":
                    if self.input_pos < len(self.inputs):
                        regs[a[0]] = self.inputs[self.input_pos]
                        self.input_pos += 1
                    else:
                        regs[a[0]] = 0
                    st.cycles += CYCLES["io"]
                else:
                    raise RuntimeFault(f"unknown target instruction {op}")
        except RuntimeFault as exc:
            st.error = str(exc)
        except KeyError as exc:
            st.error = f"invalid register or label {exc}"
        return st

    def register_arrays(self, fc, fp):
        for off, size in fc.arrays.values():
            self.alloc[fp + off] = size

    def check(self, base, idx):
        size = self.alloc.get(base)
        if size is None:
            raise RuntimeFault(f"invalid array base address {base}")
        if not 0 <= idx < size:
            raise RuntimeFault(f"array index {idx} out of bounds [0, {size})")
        return base + idx


def simulate(program, functions, globals_, inputs=None, step_limit=20_000_000):
    return Simulator(program, functions, globals_, inputs, step_limit).run()
