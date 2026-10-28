"""Summarise results/v2/*.json into results/README.md-style tables (printed to stdout)
and results/v2/summary.json.

    python3 scripts/summarise_results.py
"""
import json
import math
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, "results", "v2")
A = ["pgara", "static", "freqprio", "loopdepth", "briggsprof", "briggs", "linearscan"]
AB = {"pgara": "PGARA", "static": "Static-Prior", "freqprio": "Freq. priority", "loopdepth": "Loop-depth",
      "briggsprof": "Chaitin-Briggs (prof.)", "briggs": "Chaitin-Briggs", "linearscan": "Linear scan"}


def gm(xs):
    return math.exp(st.mean(math.log(x) for x in xs))


def main():
    main_ = json.load(open(os.path.join(R, "main.json")))
    rows = main_["rows"]
    idx = {(r["benchmark"], r["k"], r["allocator"]): r for r in rows}
    B = sorted({r["benchmark"] for r in rows})
    Ks = sorted({r["k"] for r in rows})
    summary = {"configurations": len(rows), "all_correct": all(r["correct"] for r in rows),
               "theta": main_.get("theta"), "geomean_vs_linear_scan": {}, "spill_memops": {}}
    print("Geometric-mean cycles relative to linear scan (17 programs)\n")
    print("| k | " + " | ".join(AB[a] for a in A) + " |")
    print("|---|" + "---|" * len(A))
    for k in Ks:
        g = {a: gm([idx[(b, k, a)]["cycles"] / idx[(b, k, "linearscan")]["cycles"] for b in B]) for a in A}
        summary["geomean_vs_linear_scan"][k] = g
        summary["spill_memops"][k] = {a: sum(idx[(b, k, a)]["spill_memops"] for b in B) for a in A}
        print(f"| {k} | " + " | ".join(f"{g[a]:.3f}" for a in A) + " |")
    print(f"\n{len(rows)} configurations, all correct: {summary['all_correct']}")
    with open(os.path.join(R, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
