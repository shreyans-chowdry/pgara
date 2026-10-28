"""Dataset preparation for PGARA.

The "datasets" of this project are MiniC benchmark programs (benchmarks/)
together with their training and test inputs.  The programs generate their
own data with a seeded linear congruential generator, so no external
download is needed.  This script

  1. collects every program of the original, independent and tuning suites
     with its training input and test inputs,
  2. checks that each one compiles without diagnostics and runs to
     completion in the reference interpreter on every input, and
  3. writes datasets/benchmark_inputs.json (program, suite, inputs, SSA
     values, reference output of the primary test input).

    python3 scripts/prepare_datasets.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pgara import interp  # noqa: E402
from pgara.experiments import EXTRA, ORIG_TESTS, TUNING, source  # noqa: E402
from pgara.bench import SUITE  # noqa: E402
from pgara.pipeline import frontend, build_ssa_module, optimize_module, has_errors  # noqa: E402


def check(name, inputs):
    report, program, _ = frontend(source(name))
    if has_errors(report):
        raise SystemExit(f"{name}: {report['diagnostics']}")
    module, _ = build_ssa_module(program)
    optimize_module(module, 2)
    outs = []
    for inp in inputs:
        r = interp.run(module, inp, 20_000_000)
        if r.error:
            raise SystemExit(f"{name} {inp}: {r.error}")
        outs.append(r.output)
    return outs


def main():
    entries = []
    for name, title, train, _ in SUITE:
        entries.append(("original", name, title, train, ORIG_TESTS[name]))
    for name, title, train, tests in EXTRA:
        entries.append(("independent", name, title, train, tests))
    for name, train, test in TUNING:
        entries.append(("tuning", name, name.split("_", 1)[1], train, [test]))
    data = []
    for suite, name, title, train, tests in entries:
        outs = check(name, [train] + tests)
        data.append({"suite": suite, "program": f"benchmarks/{name}.mc", "title": title,
                     "train_input": train, "test_inputs": tests,
                     "reference_output_primary_test": outs[1]})
        print(f"ok  {suite:12s} {name}")
    os.makedirs(os.path.join(ROOT, "datasets"), exist_ok=True)
    path = os.path.join(ROOT, "datasets", "benchmark_inputs.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
    print(f"{len(data)} programs verified; wrote {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
