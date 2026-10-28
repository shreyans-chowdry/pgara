# PGARA: Profile-Guided Adaptive Register Allocation

**Team 14 · Compiler Design (L43+L44) · Vellore Institute of Technology** · Release **v1.0.0**

**PGARA** is a complete compiler for **MiniC**, a small C subset, built around a new register allocator. A profiling run measures how often each branch is taken. Every SSA value is then modelled as a two-state Markov decision process (register or memory) to compute the cycles a register would save, and registers are sold in a sealed-bid auction on the chordal interference graph, settled by best-response dynamics into a Nash equilibrium. No graph colouring is used. A web interface, **PGARA Compiler Studio**, shows every phase of compilation as you type.

- **Manuscript (final, Draft 2):** [`manuscript/PGARA-FINAL.pdf`](manuscript/PGARA-FINAL.pdf)
- **LaTeX sources (Overleaf-ready zip):** [`manuscript/PGARA-Manuscript-LaTeX.zip`](manuscript/PGARA-Manuscript-LaTeX.zip)
- **Demo video:** [`docs/demo/`](docs/demo/) (4–7 minutes); script in [`docs/Demo-Video-Script.md`](docs/Demo-Video-Script.md)
- **Live interface:** https://pgara.vercel.app

---

## Repository contents

| # | Required item | Where |
|---|---|---|
| 1 | Manuscript LaTeX (zip, all images and class files, compiles on Overleaf) | `manuscript/PGARA-Manuscript-LaTeX.zip` (unzipped copy in `manuscript/latex/`) |
| 2 | Source code | `pgara/` (compiler and allocators), `web/` (GUI), `server.py`, `api/` (Vercel entry point) |
| 3 | README | this file |
| 4 | Dependencies | `requirements.txt` (standard library only), `requirements-dev.txt` (optional tools) |
| 5 | Datasets and preprocessing | `benchmarks/` (22 MiniC programs), `datasets/benchmark_inputs.json`, `scripts/prepare_datasets.py` |
| 6 | Trained models | none: PGARA learns nothing offline; its only "model" is the per-program profile, computed at compile time |
| 7 | Configuration files | `configs/experiments.json`, `configs/server.example.env`, `vercel.json` |
| 8 | Execution scripts | `scripts/` (setup, tests, GUI, experiments, benchmark, single compile; `.sh` and `.bat`) |
| 9 | Results, metrics, sample outputs | `results/` (see `results/README.md`) |
| 10 | Documentation | `manuscript/PGARA-FINAL.pdf`, `guide/PGARA-Project-Guide.pdf`, `docs/screenshots/` |
| 11 | Demo video | `docs/demo/` |

```
pgara/            compiler: lexer, parser, semantic, irgen, cfg, ssa, optimize, interp,
                  regalloc (PGARA + 6 baselines), codegen, simulator, pipeline, bench, experiments
tests/            27 unit and end-to-end tests
benchmarks/       original suite (10) · extra/ independent suite (7, MiBench/BEEBS) · tuning/ (5)
datasets/         inputs and reference outputs of every program (generated, verified)
configs/          experiment settings and GUI settings template
scripts/          setup and execution scripts
results/          experimental results (JSON), summary tables, sample outputs
manuscript/       final PDF and LaTeX sources
docs/             demo video and script, full GUI screenshots
web/, server.py   PGARA Compiler Studio (web GUI)
```

---

## System requirements

- **Python 3.8 or newer** (tested with 3.12 and 3.13) on macOS, Linux or Windows.
- **No third-party packages.** Everything uses the Python standard library.
- A modern web browser for the GUI.
- About 50 MB of disk space; a full reproduction of the experiments takes 15–25 minutes on a laptop.
- Optional: `coverage` and `playwright` (`requirements-dev.txt`) only to measure coverage or regenerate screenshots.

## Installation

```sh
git clone https://github.com/shreyans-chowdry/pgara.git
cd pgara
python3 -m pip install -r requirements.txt   # installs nothing: no runtime dependencies
scripts/setup.sh                             # checks Python and verifies all benchmark programs
```

On Windows use `python` instead of `python3`, and run the `.bat` scripts.

## Configuration

- `configs/experiments.json` holds every setting used for the manuscript: register budgets k = 3–32, hot-edge threshold θ = 0.75, gain policy and cost-model constants (load 4, store 2, σ = 1, c_mv = 1). Pass it with `--config`; `scripts/run_experiments.sh` does this for you.
- `configs/server.example.env`: copy it to `configs/server.env` to change the GUI port or stop the browser from opening.
- No passwords, API keys or network services are needed.

## Execution

| Task | Command | Time |
|---|---|---|
| Start the web GUI | `scripts/run_gui.sh` (or `start.sh`, `start.command`, `start.bat`, `python3 server.py`) → http://127.0.0.1:8765/ | instant |
| Run all tests | `scripts/run_tests.sh` (Windows: `scripts\run_tests.bat`) | 1–3 min |
| Reproduce every result of the paper | `scripts/run_experiments.sh` (Windows: `scripts\run_experiments.bat`) | 15–25 min |
| Run selected studies | `scripts/run_experiments.sh main inputs` | |
| Quick four-allocator study | `scripts/run_benchmark.sh` | 10 s |
| Compile one program | `scripts/compile_example.sh benchmarks/05_rarebranch.mc 4 "7 10" "13 10"` | 1 s |
| Rebuild sample outputs | `python3 scripts/sample_outputs.py` | 1 s |
| Summarise results | `python3 scripts/summarise_results.py` | 1 s |

There is no training step: PGARA's only learned quantity is the per-program profile, which is measured during compilation.

The studies of `python3 -m pgara.experiments` are:

| Study | What it does |
|---|---|
| `tuning` | chooses θ on the held-out suite `benchmarks/tuning` (never used in reported results) |
| `main` | 17 programs, seven allocators, k = 3, 4, 5, 6, 8, 16, 32 |
| `inputs` | five test inputs per program at k = 4 |
| `errsweep` | rare-branch, training error rate 1%–60% |
| `costs` | sensitivity to the model constants σ and c_mv |
| `policy` | realised (always-in-register) gain vs optimal-policy gain |
| `scaling` | allocation time on generated programs of growing size |

The allocators are PGARA, Static-Prior PGARA, profiled-frequency priority (ablation), loop-depth priority, Chaitin–Briggs with static and with profile-weighted spill costs, and linear scan.

### Verified in a fresh environment

A fresh clone was set up in a clean Python 3 environment with no extra packages. `scripts/setup.sh`, `scripts/run_tests.sh` (27 tests, OK) and `scripts/run_experiments.sh main` all ran successfully, and `results/v2/main.json` was reproduced exactly.

---

## Key results

At k = 4, over 17 programs (geometric mean), PGARA needs:
- **21.8%** fewer cycles than linear scan,
- **3.7%** fewer than Chaitin–Briggs with profiled spill costs,
- **3.3%** fewer than profiled-frequency priority,
- **2.6%** fewer than Static-Prior.

It also executes **50%** fewer spill memory operations than linear scan. All 1,428 compiled configurations match the reference output. See [`results/README.md`](results/README.md).

---

## Using the GUI

1. **Pick a program** from the *Program* list (ten benchmarks), or type your own MiniC in the editor.
2. Set **Registers k**, the number of allocatable registers (2–16).
3. Set the **Training input** used for profiling and the **Test input** used for measurement. Separate the numbers with spaces; each call to `input()` reads the next one.
4. With **Live compile** ticked, the program recompiles as you type. Otherwise press **Compile**.

Errors appear under the editor and in red in the gutter. Click an error to jump to its line.

| Tab | What it shows |
|---|---|
| **Tokens** | The token stream from the maximal-munch DFA lexer, colour-coded by kind: keywords purple, identifiers blue, numbers orange, operators pink. Hover a token to highlight it in the source. |
| **AST** | An interactive syntax tree. Drag to pan, scroll to zoom, click a node to fold it. Colours show declarations (indigo), control flow (violet), statements (green), expressions (orange) and leaves (blue). |
| **Symbols** | The scoped symbol table, one card per scope, with unique IR names, kinds, types and reference counts. |
| **TAC** | Three-address code. Use the step buttons or **Play** to emit it one instruction at a time. |
| **SSA & Optimiser** | Pruned SSA with φ-functions, then the optimised SSA, with a log of each optimisation pass. |
| **CFG** | The control-flow graph. Block headers are coloured by how often they ran (blue for rare, red for hot). Each edge shows its *profiled probability (static prior)*. Violet dashed edges are loop back edges. |
| **Allocation** | The interference graph, with each register in its own colour and spilled values in red dashed outline. A table lists each value's MDP gain G(v), coalition bid, live-range size and policy-iteration rounds. It also shows every sealed-bid auction round (winners green, losers red) and the perfect elimination ordering. |
| **Target Code** | PG-RISC assembly that you can step through. Spill loads and stores are tagged red, caller-save code amber, φ copies violet and forwarded loads green. Hover a line to see the IR it came from. |
| **Run & Metrics** | The output of the reference interpreter. It also compares all four allocators on cycles, instructions, loads and stores, spill memory operations, register utilisation, code size and realised gain, with bar charts. The best allocator is highlighted green. |
| **Grammar** | The LL(1) grammar (41 nonterminals, 94 productions), its FIRST and FOLLOW sets, and the predictive-table check. The only conflict is the dangling *else*. |

---

## The pipeline

1. **Lexer**: a maximal-munch DFA with line and column positions. It recovers from errors in panic mode.
2. **Parser**: hand-written recursive descent for an LL(1) grammar, building an abstract syntax tree. It recovers from errors in panic mode.
3. **Semantic analysis**: an L-attributed evaluation over a stack of hash-map scopes. It checks types, arity, arrays, `break`/`continue` placement and missing returns, and gives every symbol a unique IR name.
4. **TAC generation**: syntax-directed translation, with jumping code for `&&`, `||` and `!`.
5. **CFG and SSA**: basic blocks, critical-edge splitting, Cooper–Harvey–Kennedy dominators, dominance frontiers, natural loops, and pruned SSA (Cytron et al.).
6. **Optimiser**: SCCP, copy propagation, algebraic simplification and strength reduction, dominator-scoped GVN, DCE, block merging and compare-branch fusion.
7. **Profiling**: a reference interpreter runs the optimised SSA on the training input and counts how often each CFG edge is taken.
8. **PGARA allocation**:
   - Each SSA value is modelled as a two-state (register or memory) Markov decision process over its live range.
   - Policy iteration solves it exactly, giving the value's expected gain G(v).
   - φ-related values bid together as coalitions.
   - Registers are awarded by a sealed-bid auction in maximum-cardinality-search order on the chordal interference graph.
   - Best-response dynamics then settle the result into a Nash equilibrium.
9. **Code generation**: out-of-SSA translation with parallel copies, spill slots shared per φ-web, caller-save around calls, and a peephole pass.
10. **Simulator**: a cycle-counting PG-RISC machine. Each run is checked against the reference interpreter's output.

The GUI compares four allocators: **PGARA**, **Static-Prior PGARA** (no profile), **loop-depth priority** (Chow–Hennessy style) and **linear scan** (Poletto–Sarkar). The experiment harness adds **profiled-frequency priority** and **Chaitin–Briggs** with static and with profile-weighted spill costs.

---

## MiniC in brief

```c
int data[100];                 // global array
int sum(int a[], int n) {      // array parameters are passed by reference
  int s = 0;
  for (int i = 0; i < n; i++) s += a[i];
  return s;
}
int main() {
  int n = input();             // reads the next number from the input box
  for (int i = 0; i < n; i++) data[i] = i * i;
  if (n > 0 && sum(data, n) % 2 == 0) print(1); else print(0);
  return 0;
}
```

| Feature | Supported forms |
|---|---|
| Types | `int` scalars, `int` arrays, `void` functions |
| Control flow | `if`/`else`, `while`, `for`, `break`, `continue`, `return` |
| Operators | `+ - * / %`, `< <= > >= == !=`, `&& || !` (short-circuit) |
| Assignment | `= += -= *= ++ --` |
| Input and output | `input()` and `print(expr)` |

---

## Team

| Member | Registration No. | Role |
|---|---|---|
| Shreyans Chowdry | 24BDS0114 | Core pipeline design, lexical and syntax analysis, AST construction, intermediate code generation, web GUI; in the allocator: transition matrices, block frequencies, φ-web coalitions |
| Samrender Singh Saini | 24BCE2865 | Semantic analysis, scope resolution and symbol table management; in the allocator: interference graph, MCS order, sealed-bid auction and binding |
| Karthikeya Jami | 24BCE2136 | SSA, optimisation engine and PG-RISC code generation; in the allocator: residency MDP, policy iteration and gains |
| Abhishek Kumar | 24BCE0585 | Runtime environment, simulator, test suite and benchmarking; in the allocator: best response, coalition repair, baselines and ablations |
| Nishanth Kumar | 24BAI0194 | Documentation and interface testing support |

The `guide` folder holds **PGARA-Project-Guide.pdf**, a plain-language explanation of the project written for Draft 1; numbers in it predate the revised evaluation, which is in the manuscript.
