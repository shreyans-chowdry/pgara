"""PGARA register allocation: stochastic dynamic programming plus a
game-theoretic auction over the chordal SSA interference graph.

Pipeline for one function:
  1. liveness on SSA form and the interference graph;
  2. Maximum Cardinality Search (Tarjan & Yannakakis) giving a perfect
     elimination ordering, verified with the zero-fill test;
  3. a transition matrix P over CFG edges, either from the edge profile
     (PGARA) or from static branch heuristics (Static-Prior), and the
     expected block frequencies f = e_entry + P^T f;
  4. for every SSA value, a two-state (REG/MEM) Markov decision process over
     its live range solved exactly by Howard policy iteration, yielding its
     expected gain G(v) = f(def) * (V*(def, REG) - V_mem(def));
  5. coalitions: phi-related values joined over hot edges bid the sum of
     their gains;
  6. a sealed-bid auction processed along the MCS order: whenever a value's
     already-decided register-holding neighbours (always a clique in a chordal
     graph) would exceed k, the k highest bidders keep a register;
  7. register binding along the same order, preferring a register already
     held by a phi partner;
  8. best-response dynamics to a Nash equilibrium, with coalition repair.

Two reference allocators share steps 1-2 and 6: a loop-depth priority
allocator (Chow-Hennessy-style 10^depth weights) and Poletto-Sarkar linear
scan over live intervals.
"""

from .cfg import natural_loops, reverse_postorder
from .ssa import liveness


class CostModel:
    """Cycle costs shared by the MDP and the target simulator."""
    LOAD = 4
    STORE = 2
    SAVE = 1           # cycles saved per access served from a register
    MOVE = 1           # register-to-register move
    GAMMA = 0.999      # discount used only if a chain is not transient
    STATIC_LOOP = 0.9  # static prior: probability of staying inside a loop
    THETA = 0.75       # hot-edge threshold for phi-web coalitions (tuned on
                       # the held-out suite benchmarks/tuning, see experiments.py)
    GAIN_POLICY = "forced"  # "forced": always-in-register policy (what code
                            # generation realises); "optimal": V* of the MDP


# ---------------------------------------------------------------- analyses
class FunctionAnalysis:
    def __init__(self, fn):
        self.fn = fn
        self.live_in, self.live_out, self.liveness_iterations = liveness(fn)
        self.values = []
        self.def_block = {}
        self.def_order = {}
        for b in fn.blocks:
            for ins in b.instrs:
                if ins.dst is not None and ins.dst not in self.def_block:
                    self.def_block[ins.dst] = b.name
                    self.def_order[ins.dst] = len(self.values)
                    self.values.append(ins.dst)
        self.build_interference()
        self.count_accesses()
        self.back_edges, self.loops, self.depth = natural_loops(fn)

    def live_after(self, block):
        """List parallel to block.instrs: the set live immediately after each one."""
        live = set(self.live_out[block.name])
        out = [None] * len(block.instrs)
        for idx in range(len(block.instrs) - 1, -1, -1):
            ins = block.instrs[idx]
            out[idx] = set(live)
            if ins.op == "phi":
                continue
            if ins.dst is not None:
                live.discard(ins.dst)
            live.update(ins.uses())
        return out

    def build_interference(self):
        adj = {v: set() for v in self.values}
        for b in self.fn.blocks:
            live = set(self.live_out[b.name])
            for ins in reversed(b.instrs):
                if ins.op == "phi":
                    continue
                if ins.dst is not None:
                    for w in live:
                        if w != ins.dst:
                            adj[ins.dst].add(w)
                            adj[w].add(ins.dst)
                    live.discard(ins.dst)
                live.update(ins.uses())
            phis = [i.dst for i in b.phis()]
            for d in phis:
                for w in live | set(phis):
                    if w != d:
                        adj[d].add(w)
                        adj[w].add(d)
        self.adj = adj

    def count_accesses(self):
        """acc_use[v][b] and acc_def[v][b] count real (non-phi) uses and
        definitions; phi operands and results are excluded because a phi web
        is allocated as a coalition (see phi_webs).  calls[v][b] counts calls
        that v is live across; param[v] marks incoming parameters, whose
        memory home is the parameter slot itself."""
        self.acc_use = {v: {} for v in self.values}
        self.acc_fwd = {v: {} for v in self.values}
        self.acc_def = {v: {} for v in self.values}
        self.calls = {v: {} for v in self.values}
        self.param = set()
        for b in self.fn.blocks:
            after = self.live_after(b)
            prev = None
            for idx, ins in enumerate(b.instrs):
                if ins.op == "phi":
                    continue
                if ins.op == "param":
                    self.param.add(ins.dst)
                elif ins.dst is not None:
                    self.acc_def[ins.dst][b.name] = self.acc_def[ins.dst].get(b.name, 0) + 1
                for u in set(ins.uses()):
                    if u not in self.acc_use:
                        continue
                    n = ins.uses().count(u)
                    if prev is not None and prev.dst == u:
                        # The reload right after the spill store is forwarded
                        # by the code generator (store-to-load forwarding).
                        self.acc_fwd[u][b.name] = self.acc_fwd[u].get(b.name, 0) + 1
                        n -= 1
                    if n:
                        self.acc_use[u][b.name] = self.acc_use[u].get(b.name, 0) + n
                prev = ins
                if ins.op == "call":
                    for v in after[idx] - {ins.dst}:
                        if v in self.calls:
                            self.calls[v][b.name] = self.calls[v].get(b.name, 0) + 1
        self.webs = phi_webs(self.fn, self.values)

    def live_range(self, v):
        return {b for b, s in self.live_in.items() if v in s} | {self.def_block[v]}


def phi_webs(fn, values):
    """Phi-congruence classes: union-find over every phi result and its
    variable operands.  Returns {value: tuple(members)}."""
    parent = {v: v for v in values}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for b in fn.blocks:
        for phi in b.phis():
            for a in phi.phi.values():
                if isinstance(a, str) and a in parent:
                    ra, rb = find(a), find(phi.dst)
                    if ra != rb:
                        parent[ra] = rb
    groups = {}
    for v in values:
        groups.setdefault(find(v), []).append(v)
    return {v: tuple(groups[find(v)]) for v in values}


# ------------------------------------------------- chordal structure (MCS)
def maximum_cardinality_search(values, adj, order_key):
    """Return the MCS visit order sigma.  reversed(sigma) is a perfect
    elimination ordering whenever the graph is chordal."""
    weight = {v: 0 for v in values}
    buckets = {0: set(values)}
    remaining = set(values)
    order = []
    top = 0
    while remaining:
        while top > 0 and not buckets.get(top):
            top -= 1
        v = min(buckets[top], key=order_key)
        buckets[top].discard(v)
        remaining.discard(v)
        order.append(v)
        for w in adj[v]:
            if w in remaining:
                buckets[weight[w]].discard(w)
                weight[w] += 1
                buckets.setdefault(weight[w], set()).add(w)
                if weight[w] > top:
                    top = weight[w]
    return order


def verify_peo(order, adj):
    """Zero-fill test: for every v, its earlier-visited neighbours minus the
    latest of them must all be earlier-visited neighbours of that latest one.
    Returns (is_chordal, max_clique_size)."""
    pos = {v: i for i, v in enumerate(order)}
    ok = True
    max_clique = 1 if order else 0
    for v in order:
        earlier = [w for w in adj[v] if pos[w] < pos[v]]
        max_clique = max(max_clique, len(earlier) + 1)
        if not earlier:
            continue
        u = max(earlier, key=lambda w: pos[w])
        for w in earlier:
            if w != u and w not in adj[u]:
                ok = False
    return ok, max_clique


# -------------------------------------------------- transition probabilities
def static_probabilities(fa):
    """Static branch prediction: loop branches stay in the loop with
    probability 0.9 (Ball-Larus/Wu-Larus loop heuristic), other two-way
    branches are 50/50."""
    P = {}
    for b in fa.fn.blocks:
        succs = b.succs
        if not succs:
            P[b.name] = {}
            continue
        if len(succs) == 1:
            P[b.name] = {succs[0]: 1.0}
            continue
        exits = []
        for s in succs:
            leaves = any(b.name in body and s not in body for body in fa.loops.values())
            exits.append(leaves)
        if sum(exits) == 1:
            p_stay = CostModel.STATIC_LOOP
            P[b.name] = {s: (1 - p_stay if e else p_stay) for s, e in zip(succs, exits)}
        else:
            P[b.name] = {s: 1.0 / len(succs) for s in succs}
    return P


def profiled_probabilities(fa, edge_counts):
    """P(b -> s) = count(b, s) / sum_s' count(b, s'); blocks that never executed
    in the training run fall back to the static prior."""
    static = static_probabilities(fa)
    P = {}
    for b in fa.fn.blocks:
        total = sum(edge_counts.get((b.name, s), 0) for s in b.succs)
        if total == 0:
            P[b.name] = static[b.name]
        else:
            P[b.name] = {s: edge_counts.get((b.name, s), 0) / total for s in b.succs}
    return P


# ------------------------------------------------------------- MDP solver
def solve_linear(rows, rhs):
    """Solve A x = b for a sparse system given as rows[i] = {j: a_ij}.
    Gaussian elimination in index order; the systems solved here have the
    form (I - Q) x = r with Q substochastic and transient, i.e. non-singular
    M-matrices, so no pivoting is needed.  Returns None if a pivot vanishes."""
    n = len(rhs)
    rows = [dict(r) for r in rows]
    rhs = list(rhs)
    for i in range(n):
        piv = rows[i].get(i, 0.0)
        if abs(piv) < 1e-12:
            return None
        ri = rows[i]
        for j in range(i + 1, n):
            f = rows[j].get(i)
            if not f:
                continue
            f /= piv
            rj = rows[j]
            for c, val in ri.items():
                rj[c] = rj.get(c, 0.0) - f * val
            rj.pop(i, None)
            rhs[j] -= f * rhs[i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = rhs[i]
        for c, val in rows[i].items():
            if c > i:
                acc -= val * x[c]
        x[i] = acc / rows[i][i]
    return x


class ValueMDP:
    """Two-state (REG / MEM) Markov decision process over the live range of
    one SSA value.  State (b, s): control is in block b and the value is
    resident in a register (s = R) or in its memory slot (s = M).

        V(b,R) = r_R(b) + max( sum_b' P(b,b') V(b',R),  -c_st + sum_b' P(b,b') V(b',M) )
        V(b,M) = r_M(b) + max( sum_b' P(b,b') V(b',M),  -c_ld + sum_b' P(b,b') V(b',R) )

    with r_R(b) = sigma * acc(b) - calls(b) * (c_st + c_ld) and
    r_M(b) = -(uses(b) * c_ld + defs(b) * c_st).  Transitions leaving the live
    range are absorbing with value 0.
    """

    def __init__(self, fa, v, P, rpo_index):
        cm = CostModel
        self.blocks = sorted(fa.live_range(v), key=lambda b: rpo_index.get(b, 0))
        bm = fa.fn.block_map()
        in_range = set(self.blocks)
        self.trans = {}
        for b in self.blocks:
            out = []
            for s in bm[b].succs:
                if s in in_range and v in fa.live_in[s]:
                    p = P[b].get(s, 0.0)
                    if p > 0:
                        out.append((s, p))
            self.trans[b] = out
        use, dfn, calls = fa.acc_use[v], fa.acc_def[v], fa.calls[v]
        self.r_reg = {b: (use.get(b, 0) + dfn.get(b, 0)) * cm.SAVE
                      - calls.get(b, 0) * (cm.STORE + cm.LOAD) for b in self.blocks}
        if v in fa.param:
            # A parameter held in a register must first be loaded from its slot.
            self.r_reg[fa.def_block[v]] -= cm.LOAD
        fwd = fa.acc_fwd[v]
        for b in self.blocks:
            self.r_reg[b] += fwd.get(b, 0) * cm.SAVE
        self.r_mem = {b: -(use.get(b, 0) * cm.LOAD + dfn.get(b, 0) * cm.STORE + fwd.get(b, 0) * cm.MOVE)
                      for b in self.blocks}
        self.def_block = fa.def_block[v]

    def q(self, VR, VM, b, gamma=1.0):
        er = sum(p * VR[s] for s, p in self.trans[b])
        em = sum(p * VM[s] for s, p in self.trans[b])
        return {
            ("R", "stay"): self.r_reg[b] + gamma * er,
            ("R", "spill"): self.r_reg[b] - CostModel.STORE + gamma * em,
            ("M", "stay"): self.r_mem[b] + gamma * em,
            ("M", "reload"): self.r_mem[b] - CostModel.LOAD + gamma * er,
        }

    def evaluate(self, policy, gamma):
        """Exact policy evaluation: solve (I - gamma P_pi) V = r_pi."""
        index = {}
        for b in self.blocks:
            index[(b, "R")] = len(index)
            index[(b, "M")] = len(index)
        rows, rhs = [], []
        for b in self.blocks:
            for st in ("R", "M"):
                act = policy[(b, st)]
                nxt = "R" if (st == "R" and act == "stay") or (st == "M" and act == "reload") else "M"
                row = {index[(b, st)]: 1.0}
                for s, p in self.trans[b]:
                    j = index[(s, nxt)]
                    row[j] = row.get(j, 0.0) - gamma * p
                rows.append(row)
                base = self.r_reg[b] if st == "R" else self.r_mem[b]
                if act == "spill":
                    base -= CostModel.STORE
                elif act == "reload":
                    base -= CostModel.LOAD
                rhs.append(base)
        x = solve_linear(rows, rhs)
        if x is None:
            return None
        VR = {b: x[index[(b, "R")]] for b in self.blocks}
        VM = {b: x[index[(b, "M")]] for b in self.blocks}
        return VR, VM

    def policy_iteration(self, gamma=1.0, max_rounds=50):
        """Howard's policy iteration.  Returns (VR, VM, policy, rounds)."""
        policy = {(b, st): "stay" for b in self.blocks for st in ("R", "M")}
        for rounds in range(1, max_rounds + 1):
            res = self.evaluate(policy, gamma)
            if res is None:
                return None
            VR, VM = res
            changed = False
            for b in self.blocks:
                q = self.q(VR, VM, b, gamma)
                for st, alt in (("R", "spill"), ("M", "reload")):
                    cur = policy[(b, st)]
                    best = max(("stay", alt), key=lambda a: q[(st, a)])
                    if best != cur and q[(st, best)] > q[(st, cur)] + 1e-9:
                        policy[(b, st)] = best
                        changed = True
            if not changed:
                return VR, VM, policy, rounds
        return VR, VM, policy, max_rounds

    def value_iteration(self, gamma, epsilon=1e-9, max_sweeps=1_000_000):
        """Bellman value iteration (Gauss-Seidel sweeps) to a fixpoint."""
        VR = {b: 0.0 for b in self.blocks}
        VM = {b: 0.0 for b in self.blocks}
        order = list(reversed(self.blocks))
        for sweep in range(1, max_sweeps + 1):
            delta = 0.0
            for b in order:
                q = self.q(VR, VM, b, gamma)
                nr = max(q[("R", "stay")], q[("R", "spill")])
                nm = max(q[("M", "stay")], q[("M", "reload")])
                delta = max(delta, abs(nr - VR[b]), abs(nm - VM[b]))
                VR[b], VM[b] = nr, nm
            if delta < epsilon:
                return VR, VM, sweep
        return VR, VM, max_sweeps

    def memory_only(self, gamma):
        """Value of the losing outcome: the value never holds a register, so
        every block is in state M under the forced action 'stay'."""
        policy = {(b, st): "stay" for b in self.blocks for st in ("R", "M")}
        res = self.evaluate(policy, gamma)
        return None if res is None else res[1]

    def register_only(self, gamma):
        """Value of the policy the code generator actually realises for an
        auction winner: the value never leaves its register inside the live
        range (no live-range splitting), i.e. state R under the forced action
        'stay' in every block."""
        policy = {(b, st): "stay" for b in self.blocks for st in ("R", "M")}
        res = self.evaluate(policy, gamma)
        return None if res is None else res[0]

    def solve_both(self):
        """Return (g_opt, g_forced, rounds, policy, splits): the per-entry gain
        under the optimal policy V* and under the forced always-in-register
        policy, and whether the optimal policy spills or reloads anywhere
        inside the live range (i.e. would need live-range splitting)."""
        for gamma in (1.0, CostModel.GAMMA):
            res = self.policy_iteration(gamma)
            mem = self.memory_only(gamma) if res is not None else None
            reg = self.register_only(gamma) if mem is not None else None
            if res is not None and mem is not None and reg is not None:
                break
        VR, VM, policy, rounds = res
        d = self.def_block
        splits = any(a != "stay" for a in policy.values())
        return VR[d] - mem[d], reg[d] - mem[d], rounds, policy, splits

    def solve(self):
        """Per-entry gain G = V*(def,R) - V_mem(def): the optimal expected
        reward of entering the live range with a register, minus the reward
        of the memory-only policy an auction loser is left with.  Undiscounted
        (total expected reward) unless the chain is not transient, in which
        case gamma = CostModel.GAMMA."""
        for gamma in (1.0, CostModel.GAMMA):
            res = self.policy_iteration(gamma)
            mem = self.memory_only(gamma) if res is not None else None
            if res is not None and mem is not None:
                break
        VR, VM, policy, rounds = res
        d = self.def_block
        return VR[d] - mem[d], rounds, policy


def block_frequencies(fa, P):
    """Expected executions of each block per invocation of the function:
    f = e_entry + P^T f, solved exactly (Markov chain over the CFG)."""
    blocks = [b.name for b in fa.fn.blocks]
    index = {b: i for i, b in enumerate(blocks)}
    for gamma in (1.0, CostModel.GAMMA):
        rows = [{i: 1.0} for i in range(len(blocks))]
        for b in blocks:
            for s, p in P[b].items():
                if p > 0:
                    rows[index[s]][index[b]] = rows[index[s]].get(index[b], 0.0) - gamma * p
        rhs = [1.0 if i == 0 else 0.0 for i in range(len(blocks))]
        x = solve_linear(rows, rhs)
        if x is not None:
            return {b: max(0.0, x[index[b]]) for b in blocks}
    return {b: 1.0 for b in blocks}


def compute_gains(fa, P, policy=None, detail=None):
    """G(v) = f(def(v)) * (V_pi(def,R) - V_mem(def)): the expected
    register-residency gain of v per invocation of its function, where pi is
    the forced always-in-register policy that code generation realises
    (default) or the optimal MDP policy V* (policy="optimal").  If `detail`
    is a dict it receives, per value, both gains and whether V* would split
    the live range."""
    policy = policy or CostModel.GAIN_POLICY
    rpo = reverse_postorder(fa.fn)
    rpo_index = {b: i for i, b in enumerate(rpo)}
    freq = block_frequencies(fa, P)
    gains, rounds, sizes = {}, {}, {}
    for v in fa.values:
        mdp = ValueMDP(fa, v, P, rpo_index)
        g_opt, g_forced, r, _, splits = mdp.solve_both()
        f = freq[fa.def_block[v]]
        gains[v] = f * (g_forced if policy == "forced" else g_opt)
        rounds[v] = r
        sizes[v] = len(mdp.blocks)
        if detail is not None:
            detail[v] = {"opt": f * g_opt, "forced": f * g_forced, "splits": splits}
    return gains, rounds, sizes


def loop_depth_weights(fa):
    """Chow-Hennessy-style static priority: accesses weighted by 10^depth."""
    w = {}
    for v in fa.values:
        total = 0.0
        for b, c in fa.acc_use[v].items():
            total += c * 10 ** fa.depth.get(b, 0)
        for b, c in fa.acc_def[v].items():
            total += c * 10 ** fa.depth.get(b, 0)
        for b, c in fa.acc_fwd[v].items():
            total += c * 10 ** fa.depth.get(b, 0)
        w[v] = total
    return w


def frequency_weights(fa, P):
    """Profile-weighted spill cost (ablation): the 10^depth weight of the
    loop-depth allocator replaced by the block frequency phi(b) of
    (I - P^T) phi = e_entry under the given transition matrix."""
    freq = block_frequencies(fa, P)
    w = {}
    for v in fa.values:
        total = 0.0
        for table in (fa.acc_use[v], fa.acc_def[v], fa.acc_fwd[v]):
            for b, c in table.items():
                total += c * freq.get(b, 0.0)
        w[v] = total
    return w


def spill_costs(fa, P=None):
    """Chaitin-style spill cost: (load per use + store per def) weighted by
    10^depth (static) or by profiled block frequency (when P is given)."""
    freq = block_frequencies(fa, P) if P is not None else None
    cost = {}
    for v in fa.values:
        total = 0.0
        for table, c_acc in ((fa.acc_use[v], CostModel.LOAD), (fa.acc_def[v], CostModel.STORE),
                             (fa.acc_fwd[v], CostModel.MOVE)):
            for b, c in table.items():
                wgt = freq.get(b, 0.0) if freq is not None else 10 ** fa.depth.get(b, 0)
                total += c * c_acc * wgt
        if v in fa.param:
            total -= CostModel.LOAD * (freq.get(fa.def_block[v], 0.0) if freq is not None else 1)
        cost[v] = total
    return cost


def chaitin_briggs(fa, k, cost):
    """Chaitin-Briggs graph colouring with conservative (Briggs) coalescing
    of phi-related values and optimistic spilling.  Phi operands and results
    that do not interfere are merged when the merged node has fewer than k
    neighbours of significant degree; simplify then removes nodes of degree
    < k, and when none remains pushes the node with the smallest
    cost/degree as a potential spill; select assigns colours in reverse
    order, and potential spills that find no colour become actual spills
    (with all members of their coalesced node).  Spilled values live in
    memory and use scratch registers, so no rebuild is needed."""
    order_key = lambda v: fa.def_order[v]
    rep = {v: v for v in fa.values}

    def find(x):
        while rep[x] != x:
            rep[x] = rep[rep[x]]
            x = rep[x]
        return x

    nadj = {v: set(fa.adj[v]) for v in fa.values}
    members = {v: [v] for v in fa.values}
    pairs = []
    for blk in fa.fn.blocks:
        for phi in blk.phis():
            for a in phi.phi.values():
                if isinstance(a, str) and a in rep:
                    pairs.append((phi.dst, a))
    changed = True
    while changed:
        changed = False
        for x, y in pairs:
            rx, ry = find(x), find(y)
            if rx == ry or ry in nadj[rx]:
                continue
            union = (nadj[rx] | nadj[ry]) - {rx, ry}
            significant = sum(1 for w in union if len(nadj[w]) >= k)
            if significant >= k:
                continue
            keep, drop = (rx, ry) if order_key(rx) <= order_key(ry) else (ry, rx)
            rep[drop] = keep
            for w in nadj[drop]:
                nadj[w].discard(drop)
                if w != keep:
                    nadj[w].add(keep)
                    nadj[keep].add(w)
            del nadj[drop]
            members[keep].extend(members.pop(drop))
            changed = True
    nodes = list(nadj)
    ncost = {n: sum(cost[v] for v in members[n]) for n in nodes}
    degree = {n: len(nadj[n]) for n in nodes}
    removed, stack = set(), []
    remaining = set(nodes)
    while remaining:
        low = [n for n in remaining if degree[n] < k]
        if low:
            n = min(low, key=order_key)
        else:
            n = min(remaining, key=lambda u: (ncost[u] / max(degree[u], 1), order_key(u)))
        remaining.discard(n)
        removed.add(n)
        stack.append(n)
        for w in nadj[n]:
            if w not in removed:
                degree[w] -= 1
    colour = {}
    for n in reversed(stack):
        taken = {colour[w] for w in nadj[n] if w in colour}
        free = [r for r in range(k) if r not in taken]
        if free:
            # Biased colouring: prefer a colour already held by a phi-web
            # partner that could not be coalesced.
            partners = {find(w) for v in members[n] for w in fa.webs[v]} - {n}
            hinted = [colour[p] for p in sorted(partners, key=order_key) if p in colour and colour[p] in free]
            colour[n] = hinted[0] if hinted else free[0]
    return {v: colour[n] for n in colour for v in members[n]}


# ----------------------------------------------------------- the auction
def auction(order, adj, gains, k, order_key):
    """Gain-maximising sealed-bid auction along the MCS order.  Returns
    (decided, rounds) where rounds records every contested clique."""
    decided = {}
    rounds = []
    for v in order:
        rivals = [w for w in adj[v] if decided.get(w)]
        if len(rivals) < k:
            decided[v] = True
            continue
        contenders = rivals + [v]
        ranked = sorted(contenders, key=lambda u: (-gains[u], order_key(u)))
        winners = set(ranked[:k])
        for u in contenders:
            decided[u] = u in winners
        rounds.append({
            "value": v,
            "contenders": [{"value": u, "bid": round(gains[u], 3), "wins": u in winners} for u in ranked],
        })
    return decided, rounds


def bind_registers(order, adj, winners, k, webs=None):
    """Give every winner a register unused by its earlier-visited winning
    neighbours, preferring one already held by a member of its phi web (so
    the phi copy disappears), else the lowest free index."""
    reg = {}
    demoted = []
    for v in order:
        if not winners.get(v):
            continue
        taken = {reg[w] for w in adj[v] if w in reg}
        free = [r for r in range(k) if r not in taken]
        if not free:
            demoted.append(v)
            continue
        hinted = [reg[w] for w in (webs or {}).get(v, ()) if w in reg and reg[w] in free]
        reg[v] = hinted[0] if hinted else free[0]
    return reg, demoted


def best_response(order, adj, reg, bids, k, webs, order_key, groups=None, excluded=frozenset()):
    """Best-response dynamics after the auction: a spilled coalition whose
    members all find a register left unused by their winning neighbours
    deviates and takes them (highest bid first), repeated until no spilled
    coalition can improve its payoff unilaterally, i.e. the allocation is a
    pure Nash equilibrium of the register game.  Coalitions in `excluded`
    (those that conceded in coalition repair) have left the game and are
    never reconsidered.  Returns the number of deviations."""
    groups = groups or {v: (v,) for v in order}
    deviations = 0
    changed = True
    while changed:
        changed = False
        losers = sorted({groups[v] for v in order if v not in reg and groups[v] not in excluded},
                        key=lambda g: (-bids[g[0]], min(order_key(v) for v in g)))
        for g in losers:
            if bids[g[0]] <= 0:
                continue
            tentative = {}
            ok = True
            for v in g:
                if v in reg:
                    continue
                taken = {reg[w] for w in adj[v] if w in reg} | {tentative[w] for w in adj[v] if w in tentative}
                free = [r for r in range(k) if r not in taken]
                if not free:
                    ok = False
                    break
                partner = [reg.get(w, tentative.get(w)) for w in webs.get(v, ())]
                hinted = [r for r in partner if r is not None and r in free]
                tentative[v] = hinted[0] if hinted else free[0]
            if ok and tentative:
                reg.update(tentative)
                deviations += 1
                changed = True
    return deviations


def repair_coalitions(fa, P, reg, gains, groups):
    """A coalition left split between registers and memory pays a copy
    through memory on every hot phi edge joining a winner and a loser.  When
    that expected penalty exceeds the winners' own gain, the winners concede
    (the coalition leaves the game together).  Returns the values demoted;
    their coalitions are excluded from any later best-response pass."""
    freq = block_frequencies(fa, P)
    demoted = []
    for g in {groups[v] for v in fa.values}:
        winners = [v for v in g if v in reg]
        if not winners or len(winners) == len(g):
            continue
        members = set(g)
        penalty = 0.0
        for b in fa.fn.blocks:
            for phi in b.phis():
                if phi.dst not in members:
                    continue
                for pred, a in phi.phi.items():
                    if isinstance(a, str) and a in members and ((a in reg) != (phi.dst in reg)):
                        f_edge = freq.get(pred, 0.0) * P[pred].get(b.name, 0.0)
                        penalty += f_edge * (CostModel.LOAD if phi.dst in reg else CostModel.STORE)
        if penalty >= sum(gains[w] for w in winners):
            for w in winners:
                del reg[w]
                demoted.append(w)
    return demoted


def coalitions(fa, P, theta=None):
    """Coalitions of SSA values that bid together: phi-related values are
    merged only across *hot* phi edges, i.e. edges that carry at least theta
    of the executions of the more frequent of the two definitions.  A loop-
    carried variable thus forms one coalition around its back edge, while a
    copy made once on loop entry (or on a rare path) does not drag a cold
    value into a hot coalition."""
    theta = CostModel.THETA if theta is None else theta
    freq = block_frequencies(fa, P)
    parent = {v: v for v in fa.values}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for b in fa.fn.blocks:
        for phi in b.phis():
            for pred, a in phi.phi.items():
                if not isinstance(a, str) or a not in parent:
                    continue
                f_edge = freq.get(pred, 0.0) * P[pred].get(b.name, 0.0)
                f_max = max(freq.get(fa.def_block[a], 0.0), freq.get(b.name, 0.0))
                if f_max > 0 and f_edge >= theta * f_max:
                    ra, rb = find(a), find(phi.dst)
                    if ra != rb:
                        parent[ra] = rb
    groups = {}
    for v in fa.values:
        groups.setdefault(find(v), []).append(v)
    return {v: tuple(groups[find(v)]) for v in fa.values}


def coalition_bids(fa, gains, P):
    """Members of a coalition bid as one: each bids the coalition's total
    gain, so a loop-carried variable wins or loses its register as a whole."""
    groups = coalitions(fa, P)
    total = {}
    for v in fa.values:
        g = groups[v]
        if g not in total:
            total[g] = sum(gains[w] for w in g)
    return {v: total[groups[v]] for v in fa.values}, groups


def linear_scan(fa, k):
    """Poletto & Sarkar linear scan over live intervals in layout order."""
    pos = 0
    start = {}
    end = {}

    def touch(v, p):
        if v not in start or p < start[v]:
            start[v] = p
        if v not in end or p > end[v]:
            end[v] = p

    for b in fa.fn.blocks:
        bstart = pos
        for v in fa.live_in[b.name]:
            touch(v, bstart)
        for ins in b.instrs:
            pos += 1
            if ins.op != "phi":
                for u in ins.uses():
                    touch(u, pos)
            if ins.dst is not None:
                touch(ins.dst, bstart if ins.op == "phi" else pos)
        pos += 1
        for v in fa.live_out[b.name]:
            touch(v, pos)
    intervals = sorted(fa.values, key=lambda v: (start.get(v, 0), fa.def_order[v]))
    active = []
    reg = {}
    free = list(range(k))
    spilled = set()
    for v in intervals:
        s = start.get(v, 0)
        active.sort(key=lambda w: end[w])
        while active and end[active[0]] < s:
            w = active.pop(0)
            free.append(reg[w])
        if free:
            free.sort()
            hinted = [reg[w] for w in fa.webs[v] if w in reg and reg[w] in free]
            r = hinted[0] if hinted else free[0]
            free.remove(r)
            reg[v] = r
            active.append(v)
        else:
            active.sort(key=lambda w: end[w])
            victim = active[-1]
            if end[victim] > end.get(v, s):
                reg[v] = reg.pop(victim)
                spilled.add(victim)
                active.remove(victim)
                active.append(v)
            else:
                spilled.add(v)
    return reg, {"intervals": {v: [start.get(v, 0), end.get(v, 0)] for v in fa.values}}


# ----------------------------------------------------------- driver
ALLOCATORS = ("pgara", "static", "loopdepth", "linearscan")
# Additional baselines used by the benchmark harness (not shown in the GUI).
EXTRA_ALLOCATORS = ("freqprio", "briggs", "briggsprof")
ALLOCATOR_NAMES = {
    "pgara": "PGARA (profiled)",
    "static": "Static-Prior PGARA",
    "loopdepth": "Loop-depth priority",
    "linearscan": "Linear scan",
    "freqprio": "Profiled-frequency priority",
    "briggs": "Chaitin-Briggs (static costs)",
    "briggsprof": "Chaitin-Briggs (profiled costs)",
}


class Allocation:
    def __init__(self, fn_name, allocator, k):
        self.fn_name = fn_name
        self.allocator = allocator
        self.k = k
        self.reg = {}
        self.spilled = []
        self.gains = {}
        self.bids = {}
        self.sweeps = {}
        self.rounds = []
        self.demoted = []
        self.extra = {}


def allocate_function(fa, allocator, k, edge_counts=None, chordal_info=None):
    key = lambda v: fa.def_order[v]
    order = chordal_info["order"] if chordal_info else maximum_cardinality_search(fa.values, fa.adj, key)
    alloc = Allocation(fa.fn.name, allocator, k)
    if allocator in ("pgara", "static"):
        if allocator == "pgara" and edge_counts is not None:
            P = profiled_probabilities(fa, edge_counts)
        else:
            P = static_probabilities(fa)
        gains, rounds, sizes = compute_gains(fa, P)
        bids, groups = coalition_bids(fa, gains, P)
        alloc.extra["coalitions"] = sorted({g for g in groups.values() if len(g) > 1})
        alloc.gains = gains
        alloc.bids = bids
        alloc.sweeps = rounds
        alloc.extra["live_range_blocks"] = sizes
        alloc.extra["P"] = P
        decided, auction_rounds = auction(order, fa.adj, bids, k, key)
        alloc.rounds = auction_rounds
        reg, demoted = bind_registers(order, fa.adj, decided, k, fa.webs)
        alloc.extra["deviations"] = best_response(order, fa.adj, reg, bids, k, fa.webs, key, groups)
        alloc.extra["conceded"] = repair_coalitions(fa, P, reg, gains, groups)
        if alloc.extra["conceded"]:
            left = frozenset(groups[v] for v in alloc.extra["conceded"])
            alloc.extra["deviations"] += best_response(order, fa.adj, reg, bids, k, fa.webs, key,
                                                       groups, excluded=left)
    elif allocator in ("loopdepth", "freqprio"):
        if allocator == "loopdepth":
            Pc = static_probabilities(fa)
            gains = loop_depth_weights(fa)
        else:
            Pc = profiled_probabilities(fa, edge_counts or {})
            gains = frequency_weights(fa, Pc)
        bids, groups = coalition_bids(fa, gains, Pc)
        alloc.extra["coalitions"] = sorted({g for g in groups.values() if len(g) > 1})
        alloc.gains = gains
        alloc.bids = bids
        decided, auction_rounds = auction(order, fa.adj, bids, k, key)
        alloc.rounds = auction_rounds
        reg, demoted = bind_registers(order, fa.adj, decided, k, fa.webs)
        alloc.extra["deviations"] = best_response(order, fa.adj, reg, bids, k, fa.webs, key, groups)
    elif allocator in ("briggs", "briggsprof"):
        P = profiled_probabilities(fa, edge_counts or {}) if allocator == "briggsprof" else None
        cost = spill_costs(fa, P)
        alloc.gains = cost
        reg = chaitin_briggs(fa, k, cost)
        demoted = []
    elif allocator == "linearscan":
        reg, extra = linear_scan(fa, k)
        alloc.extra.update(extra)
        demoted = []
    else:
        raise ValueError(allocator)
    alloc.reg = reg
    alloc.demoted = demoted
    alloc.spilled = [v for v in fa.values if v not in reg]
    return alloc


def chordal_structure(fa):
    key = lambda v: fa.def_order[v]
    order = maximum_cardinality_search(fa.values, fa.adj, key)
    is_chordal, max_clique = verify_peo(order, fa.adj)
    return {"order": order, "peo": list(reversed(order)), "is_chordal": is_chordal,
            "max_clique": max_clique}
