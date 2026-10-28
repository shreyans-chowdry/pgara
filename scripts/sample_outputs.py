"""Compile one MiniC program and write sample outputs (or print them).

    python3 scripts/sample_outputs.py                      # writes results/sample_outputs/
    python3 scripts/sample_outputs.py --file prog.mc --k 4 --train "7 10" --test "13 10" --print
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pgara.pipeline import compile_source  # noqa: E402


def run(path, k, train, test):
    with open(path) as f:
        src = f.read()
    return compile_source(src, {"k": k, "train_inputs": train, "test_inputs": test,
                                "interp_step_limit": 20_000_000, "sim_step_limit": 80_000_000})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "benchmarks", "05_rarebranch.mc"))
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--train", default="7 10")
    ap.add_argument("--test", default="13 10")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    train = [int(x) for x in a.train.split()]
    test = [int(x) for x in a.test.split()]
    r = run(a.file, a.k, train, test)
    if not r["ok"]:
        for d in r["diagnostics"]:
            print(f"{d['phase']} {d['severity']} line {d['line']}:{d['col']}: {d['message']}")
        sys.exit(1)
    lines = [f"Program: {os.path.relpath(a.file, ROOT)}  k={a.k}  train={train}  test={test}",
             f"Reference output: {r['execution']['test']['output']}", "",
             f"{'Allocator':22s} {'cycles':>10s} {'spill memops':>13s} {'reg. util':>9s} {'code size':>9s} correct"]
    for name, t in r["targets"].items():
        s = t["stats"]
        lines.append(f"{name:22s} {s['cycles']:>10d} {s['spill_memops']:>13d} "
                     f"{s['register_utilization']:>9.3f} {s['code_size']:>9d} {s['matches_reference']}")
    asm = [i.get("text", "") for i in r["targets"]["pgara"]["asm"]]
    gains = r["functions"]["main"]["allocations"]["pgara"]
    if a.print:
        print("\n".join(lines))
        print("\nPGARA assembly (first 40 lines):")
        print("\n".join(asm[:40]))
        return
    out = os.path.join(ROOT, "results", "sample_outputs")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "rarebranch_k4_summary.txt"), "w").write("\n".join(lines) + "\n")
    open(os.path.join(out, "rarebranch_k4_pgara.asm"), "w").write("\n".join(asm) + "\n")
    json.dump({"gains": gains["gains"], "bids": gains["bids"], "registers": gains["registers"],
               "spilled": gains["spilled"], "coalitions": gains["coalitions"]},
              open(os.path.join(out, "rarebranch_k4_allocation.json"), "w"), indent=1)
    print("wrote", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
