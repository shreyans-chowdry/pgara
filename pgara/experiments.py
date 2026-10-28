"""Extended evaluation for the revised manuscript (Draft 2).

    python3 -m pgara.experiments [study ...] [--out results/v2]

Studies (all by default):
  tuning    choose the hot-edge threshold theta on a held-out tuning suite
  main      original + independent suites, all allocators, k in KS
  inputs    several test inputs per benchmark at k = 4 (spread of results)
  errsweep  rare-branch: training error rate 1%..60%, test error rate 1%
  costs     sensitivity of PGARA to the model constants sigma and c_mv
  policy    forced (always-in-register) vs optimal-policy gains
  scaling   allocation time against function size on generated programs

Every simulated run is checked against the reference interpreter.
"""

import argparse
import json
import math
import os
import statistics
import sys
import time

from . import regalloc
from .bench import SUITE, load
from .pipeline import compile_source

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BENCH = os.path.join(ROOT, "benchmarks")

ALL = list(regalloc.ALLOCATORS) + list(regalloc.EXTRA_ALLOCATORS)
KS = [3, 4, 5, 6, 8, 16, 32]

# Independent programs translated from standard embedded suites into MiniC.
# (name, title, training input, test inputs; the first test input is primary)
EXTRA = [
    ("extra/e1_crc", "CRC-32 (MiBench)", [3, 120], [[5, 120], [9, 120], [11, 120], [17, 120], [23, 120]]),
    ("extra/e2_bitcount", "Bit counting (MiBench)", [3, 400], [[5, 400], [9, 400], [11, 400], [17, 400], [23, 400]]),
    ("extra/e3_dijkstra", "Dijkstra (MiBench)", [3, 30], [[5, 30], [9, 30], [11, 30], [17, 30], [23, 30]]),
    ("extra/e4_levenshtein", "Levenshtein (BEEBS)", [3, 4], [[5, 4], [9, 4], [11, 4], [17, 4], [23, 4]]),
    ("extra/e5_knapsack", "0/1 knapsack (DP)", [3, 20], [[5, 20], [9, 20], [11, 20], [17, 20], [23, 20]]),
    ("extra/e6_fir", "FIR filter (BEEBS)", [3, 10], [[5, 10], [9, 10], [11, 10], [17, 10], [23, 10]]),
    ("extra/e7_qsort", "Quicksort (MiBench)", [3, 500], [[5, 500], [9, 500], [11, 500], [17, 500], [23, 500]]),
]

# Extra test inputs for the original suite (first entry = the input of the paper).
ORIG_TESTS = {
    "01_straightline": [[5, 9], [3, 4], [20, 11], [8, 2], [15, 6]],
    "02_arraysum": [[13], [17], [19], [29], [31]],
    "03_matmul": [[5], [7], [9], [11], [13]],
    "04_recursion": [[17], [15], [18], [14], [19]],
    "05_rarebranch": [[13, 10], [17, 10], [19, 10], [29, 10], [31, 10]],
    "06_earlyexit": [[13], [17], [19], [29], [31]],
    "07_dispatch": [[13, 70], [17, 70], [19, 70], [29, 70], [31, 70]],
    "08_scanner": [[13, 10], [17, 10], [19, 10], [29, 10], [31, 10]],
    "09_sort": [[13], [17], [19], [29], [31]],
    "10_collatz": [[340], [320], [360], [310], [350]],
}

# Held-out suite used only to choose theta.
TUNING = [
    ("tuning/t1_bubble", [3], [7]),
    ("tuning/t2_primes", [6000], [7000]),
    ("tuning/t3_histogram", [3, 20], [7, 20]),
    ("tuning/t4_strmatch", [3, 4], [7, 4]),
    ("tuning/t5_gcdtable", [40], [44]),
]
THETAS = [0.05, 0.1, 0.25, 0.5, 0.75, 1.01]


def suite():
    """(name, title, train, [tests]) for the original and the independent suites."""
    out = [(n, t, tr, ORIG_TESTS[n]) for n, t, tr, _ in SUITE]
    out += [(n, t, tr, te) for n, t, tr, te in EXTRA]
    return out


def source(name):
    with open(os.path.join(BENCH, name + ".mc")) as f:
        return f.read()


def run(name, train, test, k, allocators=ALL):
    r = compile_source(source(name), {"k": k, "train_inputs": train, "test_inputs": test,
                                      "allocators": list(allocators),
                                      "interp_step_limit": 20_000_000, "sim_step_limit": 80_000_000})
    if not r["ok"]:
        raise RuntimeError(f"{name}: {r['diagnostics']}")
    out = {}
    for a in allocators:
        s = r["targets"][a]["stats"]
        out[a] = {"cycles": s["cycles"], "spill_memops": s["spill_memops"],
                  "code_size": s["code_size"], "utilization": s["register_utilization"],
                  "correct": s["matches_reference"]}
    meta = {"profiling_ms": r["timings"]["profiling_ms"],
            "per_allocator_ms": r["timings"]["per_allocator_ms"],
            "analysis_ms": r["timings"]["analysis_ms"],
            "ssa_values": sum(len(f["interference"]["nodes"]) for f in r["functions"].values()),
            "conceded": sum(len(f["allocations"]["pgara"]["conceded"]) for f in r["functions"].values())
            if "pgara" in allocators else 0}
    return out, meta


def geomean(xs):
    return math.exp(statistics.mean(math.log(x) for x in xs))


def study_tuning(out):
    prev = regalloc.CostModel.THETA
    res = {}
    for th in THETAS:
        regalloc.CostModel.THETA = th
        ratios = []
        for name, tr, te in TUNING:
            for k in (3, 4, 6):
                r, _ = run(name, tr, te, k, ["pgara", "linearscan"])
                assert all(v["correct"] for v in r.values())
                ratios.append(r["pgara"]["cycles"] / r["linearscan"]["cycles"])
        res[th] = geomean(ratios)
        print(f"theta={th}: geo-mean PGARA/LS on tuning suite = {res[th]:.4f}", flush=True)
    best = min(res, key=lambda t: (round(res[t], 4), abs(t - 0.25)))
    regalloc.CostModel.THETA = prev
    return {"geomean": res, "chosen": best}


def study_main(out, theta):
    regalloc.CostModel.THETA = theta
    rows, metas = [], []
    for name, title, train, tests in suite():
        for k in KS:
            r, meta = run(name, train, tests[0], k)
            for a, v in r.items():
                rows.append(dict(benchmark=name, title=title, k=k, allocator=a, **v))
            metas.append(dict(benchmark=name, k=k, **meta))
            print(f"{name:22s} k={k:2d} " + " ".join(f"{a}={r[a]['cycles']}" for a in ALL)
                  + f" ok={all(v['correct'] for v in r.values())}", flush=True)
    return {"rows": rows, "meta": metas}


def study_inputs(out, theta):
    regalloc.CostModel.THETA = theta
    rows = []
    for name, title, train, tests in suite():
        for i, te in enumerate(tests):
            r, _ = run(name, train, te, 4)
            for a, v in r.items():
                rows.append(dict(benchmark=name, test=i, k=4, allocator=a, **v))
        print("inputs", name, flush=True)
    return {"rows": rows}


def study_errsweep(out, theta):
    regalloc.CostModel.THETA = theta
    rows = []
    for thr in (10, 20, 50, 100, 150, 200, 300, 400, 500, 600):
        for k in (4, 8):
            r, _ = run("05_rarebranch", [7, thr], [13, 10], k)
            for a, v in r.items():
                rows.append(dict(train_error_permille=thr, k=k, allocator=a, **v))
            print(f"errsweep train={thr/10:.0f}% k={k}: pgara={r['pgara']['cycles']} static={r['static']['cycles']}", flush=True)
    return {"rows": rows}


def study_costs(out, theta):
    regalloc.CostModel.THETA = theta
    rows = []
    base_save, base_move = regalloc.CostModel.SAVE, regalloc.CostModel.MOVE
    for sigma in (0, 0.5, 1, 2):
        for cmv in (0, 1, 2):
            regalloc.CostModel.SAVE, regalloc.CostModel.MOVE = sigma, cmv
            ratios = {4: [], 8: []}
            ok = True
            for name, title, train, tests in suite():
                for k in (4, 8):
                    r, _ = run(name, train, tests[0], k, ["pgara", "linearscan"])
                    ok &= all(v["correct"] for v in r.values())
                    ratios[k].append(r["pgara"]["cycles"] / r["linearscan"]["cycles"])
            rows.append({"sigma": sigma, "c_mv": cmv, "gm_k4": geomean(ratios[4]),
                         "gm_k8": geomean(ratios[8]), "correct": ok})
            print(f"sigma={sigma} cmv={cmv}: k4={rows[-1]['gm_k4']:.4f} k8={rows[-1]['gm_k8']:.4f}", flush=True)
    regalloc.CostModel.SAVE, regalloc.CostModel.MOVE = base_save, base_move
    return {"rows": rows}


def study_policy(out, theta):
    """Per-value comparison of the two gain definitions, and cycles with each."""
    from . import lexer, parser, semantic, interp
    from .pipeline import build_ssa_module, optimize_module, frontend
    regalloc.CostModel.THETA = theta
    values = split = 0
    rel = []
    sum_opt = sum_forced = 0.0
    for name, title, train, tests in suite():
        _, program, _ = frontend(source(name))
        module, _ = build_ssa_module(program)
        optimize_module(module, 2)
        prof = interp.run(module, train, 20_000_000)
        for fname, fn in module.functions.items():
            fa = regalloc.FunctionAnalysis(fn)
            P = regalloc.profiled_probabilities(fa, prof.edge_counts.get(fname, {}))
            detail = {}
            regalloc.compute_gains(fa, P, detail=detail)
            for v, d in detail.items():
                values += 1
                split += d["splits"]
                if d["opt"] > 0:
                    sum_opt += d["opt"]
                    sum_forced += max(d["forced"], 0.0)
                if d["opt"] > 1.0:
                    rel.append((d["opt"] - d["forced"]) / d["opt"])
    cyc = {}
    for pol in ("optimal", "forced"):
        regalloc.CostModel.GAIN_POLICY = pol
        for name, title, train, tests in suite():
            for k in (3, 4, 8):
                r, _ = run(name, train, tests[0], k, ["pgara"])
                cyc[(pol, name, k)] = r["pgara"]["cycles"]
    regalloc.CostModel.GAIN_POLICY = "forced"
    diffs = [abs(cyc[("optimal", n, k)] - cyc[("forced", n, k)]) / cyc[("forced", n, k)]
             for (p, n, k) in cyc if p == "forced"]
    same = sum(1 for d in diffs if d == 0)
    return {"values": values, "values_policy_splits": split,
            "sum_gain_optimal": sum_opt, "sum_gain_forced": sum_forced,
            "values_forced_negative": None,
            "values_gain_above_one_cycle": len(rel),
            "mean_rel_diff": statistics.mean(rel) if rel else 0.0,
            "max_rel_diff": max(rel) if rel else 0.0,
            "values_with_diff_gt_1pct": sum(1 for x in rel if x > 0.01),
            "configs": len(diffs), "configs_identical_cycles": same,
            "max_cycle_diff": max(diffs),
            "cycles": {f"{p}|{n}|{k}": c for (p, n, k), c in cyc.items()}}


def synthetic(m):
    """A loop with m accumulators split over two data-dependent branches."""
    lines = ["int main() {", "  int n = input();"]
    lines += [f"  int v{i} = {i};" for i in range(m)]
    lines += ["  for (int i = 0; i < n; i++) {", "    int x = (i * 7 + 3) % 10;", "    if (x < 3) {"]
    lines += [f"      v{i} += x + v{(i + 1) % m};" for i in range(0, m, 2)]
    lines += ["    } else {"]
    lines += [f"      v{i} += x * {i % 5 + 1};" for i in range(1, m, 2)]
    lines += ["    }", "  }"]
    lines += [f"  print(v{i});" for i in range(m)]
    lines += ["  return 0;", "}"]
    return "\n".join(lines)


def synthetic_long(m):
    """A loop whose body is a chain of m data-dependent conditionals, each
    updating one of m accumulators: every accumulator is live across the
    whole body, so live ranges grow with m (|L_v| is about 3m blocks)."""
    lines = ["int main() {", "  int n = input();"]
    lines += [f"  int v{i} = {i};" for i in range(m)]
    lines += ["  for (int i = 0; i < n; i++) {", "    int x = (i * 7 + 3) % 10;"]
    lines += [f"    if (x < {i % 9 + 1}) v{i} += x + {i};" for i in range(m)]
    lines += ["  }"]
    lines += [f"  print(v{i});" for i in range(m)]
    lines += ["  return 0;", "}"]
    return "\n".join(lines)


def study_scaling(out, theta):
    regalloc.CostModel.THETA = theta
    rows = []
    allocs = ["pgara", "briggsprof", "loopdepth", "linearscan"]
    for family, gen, ms in (("wide", synthetic, (8, 16, 32, 64, 128, 256)),
                            ("long", synthetic_long, (4, 8, 16, 32, 64, 96))):
      for m in ms:
        r = compile_source(gen(m), {"k": 8, "train_inputs": [40], "test_inputs": [50],
                                          "allocators": allocs, "interp_step_limit": 50_000_000,
                                          "sim_step_limit": 80_000_000})
        assert r["ok"] and all(r["targets"][a]["stats"]["matches_reference"] for a in allocs)
        fn = r["functions"]["main"]
        lr = fn["allocations"]["pgara"]["live_range_blocks"]
        rows.append({"family": family, "m": m, "ssa_values": len(fn["interference"]["nodes"]),
                     "blocks": len(fn["blocks"]), "sum_live_range": sum(lr.values()),
                     "max_live_range": max(lr.values()),
                     "pi_rounds_mean": statistics.mean(fn["allocations"]["pgara"]["sweeps"].values()),
                     "pi_rounds_max": max(fn["allocations"]["pgara"]["sweeps"].values()),
                     "profiling_ms": r["timings"]["profiling_ms"],
                     "alloc_ms": r["timings"]["per_allocator_ms"]})
        print(f"scaling {family} m={m}: |V|={rows[-1]['ssa_values']} sumL={rows[-1]['sum_live_range']} maxL={rows[-1]['max_live_range']} "
              + " ".join(f"{a}={v:.1f}ms" for a, v in rows[-1]["alloc_ms"].items()), flush=True)
    return {"rows": rows}


CONFIG = {}


def apply_config(path):
    """Load a JSON configuration (configs/experiments.json) and apply it."""
    global KS
    with open(path) as f:
        cfg = json.load(f)
    CONFIG.update(cfg)
    if "k_values" in cfg:
        KS = [int(k) for k in cfg["k_values"]]
    cm = cfg.get("cost_model", {})
    for key, attr in (("load", "LOAD"), ("store", "STORE"), ("register_access_bonus", "SAVE"),
                      ("forwarded_move", "MOVE"), ("static_loop_stay", "STATIC_LOOP")):
        if key in cm:
            setattr(regalloc.CostModel, attr, cm[key])
    if "gain_policy" in cfg:
        regalloc.CostModel.GAIN_POLICY = cfg["gain_policy"]


STUDIES = ["tuning", "main", "inputs", "errsweep", "costs", "policy", "scaling"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("studies", nargs="*", default=STUDIES)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "v2"))
    ap.add_argument("--theta", type=float, default=None)
    ap.add_argument("--config", default=None,
                    help="JSON file overriding k_values, theta and the cost-model constants "
                         "(see configs/experiments.json)")
    args = ap.parse_args()
    if args.config:
        apply_config(args.config)
        if args.theta is None and "theta" in CONFIG:
            args.theta = CONFIG["theta"]
    os.makedirs(args.out, exist_ok=True)
    theta = args.theta
    if "tuning" in args.studies:
        res = study_tuning(args.out)
        with open(os.path.join(args.out, "tuning.json"), "w") as f:
            json.dump(res, f, indent=1)
        theta = res["chosen"]
    if theta is None:
        path = os.path.join(args.out, "tuning.json")
        theta = json.load(open(path))["chosen"] if os.path.exists(path) else 0.25
    print("theta =", theta, flush=True)
    for st in args.studies:
        if st == "tuning":
            continue
        t0 = time.time()
        res = globals()["study_" + st](args.out, theta)
        res["theta"] = theta
        with open(os.path.join(args.out, st + ".json"), "w") as f:
            json.dump(res, f, indent=1)
        print(f"== {st} done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
