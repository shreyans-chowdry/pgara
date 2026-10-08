"""Benchmark harness.

    python3 -m pgara.bench [--k 3,4,5,6,8] [--out results]

For every benchmark the program is profiled on its training input and
measured on a different test input, under all four allocators and every
register budget k.  Every simulated run is checked against the reference
interpreter.  Results are written as JSON and CSV, plus a sensitivity study
in which the training input is deliberately unrepresentative.
"""

import argparse
import csv
import json
import os
import statistics
import time

from .pipeline import compile_source
from .regalloc import ALLOCATORS, ALLOCATOR_NAMES

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH_DIR = os.path.join(os.path.dirname(HERE), "benchmarks")

SUITE = [
    ("01_straightline", "Straight-line arithmetic", [12, 7], [5, 9]),
    ("02_arraysum", "Array-sum loop", [7], [13]),
    ("03_matmul", "Nested loops (matmul)", [3], [5]),
    ("04_recursion", "Recursion (fib/gcd/pow)", [16], [17]),
    ("05_rarebranch", "Rare error branch", [7, 10], [13, 10]),
    ("06_earlyexit", "Early-exit search", [7], [13]),
    ("07_dispatch", "Switch-heavy dispatch", [7, 70], [13, 70]),
    ("08_scanner", "Token scanner", [7, 10], [13, 10]),
    ("09_sort", "Insertion sort + bsearch", [7], [13]),
    ("10_collatz", "Collatz + sieve", [300], [340]),
]

# Training inputs that misrepresent the test distribution (sensitivity study).
MISMATCHED = {
    "05_rarebranch": [7, 600],
    "07_dispatch": [7, 10],
    "08_scanner": [7, 80],
}


def load(name):
    with open(os.path.join(BENCH_DIR, name + ".mc")) as f:
        return f.read()


def run_one(name, train, test, k):
    t0 = time.perf_counter()
    report = compile_source(load(name), {"k": k, "train_inputs": train, "test_inputs": test,
                                         "interp_step_limit": 20_000_000, "sim_step_limit": 60_000_000})
    elapsed = time.perf_counter() - t0
    if not report["ok"]:
        raise RuntimeError(f"{name}: {report['diagnostics']}")
    rows = []
    sweeps = []
    for fn in report["functions"].values():
        sweeps.extend(fn["allocations"]["pgara"]["sweeps"].values())
    max_clique = max(fn["chordal"]["max_clique"] for fn in report["functions"].values())
    chordal = all(fn["chordal"]["is_chordal"] for fn in report["functions"].values())
    values = sum(len(fn["interference"]["nodes"]) for fn in report["functions"].values())
    for a in ALLOCATORS:
        s = report["targets"][a]["stats"]
        rows.append({
            "benchmark": name, "k": k, "allocator": a,
            "cycles": s["cycles"], "instructions": s["instructions"],
            "loads": s["loads"], "stores": s["stores"],
            "spill_memops": s["spill_memops"], "save_restore": s["save_restore"],
            "static_spills": s["static_spills"], "code_size": s["code_size"],
            "utilization": round(s["register_utilization"], 6),
            "realised_gain": round(s["realised_gain"], 3),
            "correct": s["matches_reference"],
        })
    meta = {"benchmark": name, "k": k, "ssa_values": values, "max_clique": max_clique,
            "all_chordal": chordal, "mdp_sweeps_mean": statistics.mean(sweeps) if sweeps else 0,
            "mdp_sweeps_max": max(sweeps) if sweeps else 0,
            "compile_seconds": round(elapsed, 3),
            "alloc_ms": round(report["timings"]["allocation_ms"], 2),
            "reference_steps": report["execution"]["test"]["steps"],
            "phis": sum(v["phis"] for v in report["ssa"].values())}
    return rows, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", default="3,4,5,6,8")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "results"))
    args = ap.parse_args()
    ks = [int(x) for x in args.k.split(",")]
    os.makedirs(args.out, exist_ok=True)
    all_rows, metas = [], []
    for name, title, train, test in SUITE:
        for k in ks:
            rows, meta = run_one(name, train, test, k)
            meta["title"] = title
            all_rows.extend(rows)
            metas.append(meta)
            best = {r["allocator"]: r["cycles"] for r in rows}
            ok = all(r["correct"] for r in rows)
            print(f"{name:16s} k={k}  " + "  ".join(f"{a}={best[a]}" for a in ALLOCATORS) + f"  correct={ok}", flush=True)
    sensitivity = []
    for name, train_bad in MISMATCHED.items():
        title, train, test = next((t, tr, te) for n, t, tr, te in SUITE if n == name)
        for label, tr in (("representative", train), ("mismatched", train_bad)):
            rows, _ = run_one(name, tr, test, 4)
            for r in rows:
                r["training"] = label
                sensitivity.append(r)
            print(f"sensitivity {name} {label}: " + ", ".join(f"{r['allocator']}={r['cycles']}" for r in rows), flush=True)
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump({"rows": all_rows, "meta": metas, "sensitivity": sensitivity,
                   "allocators": ALLOCATOR_NAMES}, f, indent=1)
    with open(os.path.join(args.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print("all runs correct:", all(r["correct"] for r in all_rows + sensitivity))


if __name__ == "__main__":
    main()
