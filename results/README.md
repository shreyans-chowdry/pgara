# Results

All numbers come from the deterministic cycle-counting simulator, so re-running gives identical values on any machine.

| Path | Contents | Produced by |
|---|---|---|
| `v2/main.json` | 17 programs × 7 allocators × k ∈ {3, 4, 5, 6, 8, 16, 32} (833 configurations): cycles, spill memory operations, register utilisation, code size, correctness, timings | `python3 -m pgara.experiments main` |
| `v2/inputs.json` | five test inputs per program at k = 4 (595 runs) | `... inputs` |
| `v2/errsweep.json` | rare-branch, training error rate 1%–60% | `... errsweep` |
| `v2/costs.json` | sensitivity to the model constants σ and c_mv | `... costs` |
| `v2/policy.json` | realised (always-in-register) vs optimal-policy gain | `... policy` |
| `v2/scaling.json` | allocation time on generated programs of growing size | `... scaling` |
| `v2/tuning.json` | choice of θ on the held-out tuning suite | `... tuning` |
| `v2/summary.json` | geometric means and spill totals (from `scripts/summarise_results.py`) | `scripts/summarise_results.py` |
| `results.json`, `results.csv` | quick study with the four GUI allocators, k = 3..8 | `python3 -m pgara.bench` |
| `sample_outputs/` | compiler output for the rare-branch example at k = 4: summary table, PGARA assembly, gains/bids/registers | `scripts/sample_outputs.py` |

## Key metrics (manuscript, Draft 2)

Geometric-mean cycles relative to linear scan over the 17 programs (lower is better):

| k | PGARA | Static-Prior | Freq. priority | Loop-depth | Chaitin–Briggs (profiled) | Chaitin–Briggs | Linear scan |
|---|---|---|---|---|---|---|---|
| 3 | **0.795** | 0.821 | 0.824 | 0.846 | 0.804 | 0.824 | 1.000 |
| 4 | **0.782** | 0.803 | 0.808 | 0.825 | 0.812 | 0.830 | 1.000 |
| 5 | **0.804** | 0.813 | 0.836 | 0.852 | 0.842 | 0.853 | 1.000 |
| 6 | **0.805** | 0.820 | 0.846 | 0.861 | 0.842 | 0.852 | 1.000 |
| 8 | **0.807** | 0.819 | 0.842 | 0.848 | 0.837 | 0.841 | 1.000 |
| 16 | 0.843 | 0.843 | 0.843 | 0.843 | **0.841** | **0.841** | 1.000 |
| 32 | 0.891 | 0.891 | 0.891 | 0.891 | **0.888** | **0.888** | 1.000 |

- At k = 4, PGARA has 21.8% fewer cycles than linear scan, 3.7% fewer than Chaitin–Briggs with profiled spill costs, 3.3% fewer than profiled-frequency priority and 2.6% fewer than Static-Prior.
- It executes 50% fewer spill memory operations than linear scan at k = 4.
- All 1,428 compiled configurations (main study plus multiple inputs) reproduce the reference interpreter's output.
- 27 unit tests pass, with 94% statement coverage.

## Sample output (rare-branch, k = 4)

```
Allocator                  cycles  spill memops reg. util code size correct
pgara                      338389         28835     0.787       146 True
static                     358163         36772     0.770       138 True
loopdepth                  414979         52980     0.746       143 True
linearscan                 516434         82911     0.557       166 True
```
