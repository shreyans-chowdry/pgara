# PGARA Compiler Studio

**PGARA (Profile-Guided Adaptive Register Allocation)** is a complete compiler for **MiniC**, a small C subset. Its register allocator learns from a profiling run which paths of the program are hot, then gives registers to the values that save the most cycles. It does this with stochastic dynamic programming and a game-theoretic auction instead of graph colouring. A web interface shows every phase of compilation as it happens.

You need only **Python 3.8 or newer**. There are no packages to install and no build step.

---

## Start it

| System | What to do |
|---|---|
| **macOS** | Double-click **`start.command`**. If macOS says it is from an unidentified developer, right-click it, choose **Open**, then **Open** again. You only need to do this the first time. |
| **macOS / Linux terminal** | `./start.sh` |
| **Windows** | Double-click **`start.bat`** |
| **Any system** | `python3 server.py` |

Your browser opens **http://127.0.0.1:8765/** automatically. If port 8765 is taken, the next free port is used and printed in the terminal. Press **Ctrl+C** in that terminal window to stop the server.

Optional flags: `--port 9000` picks another port, and `--no-browser` stops the browser from opening.

If macOS reports that `python3` is missing, run `xcode-select --install` once, or install Python from python.org.

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

The compiler also includes three baseline allocators for comparison: **Static-Prior PGARA** (no profile), **loop-depth priority** (Chow–Hennessy style) and **linear scan** (Poletto–Sarkar).

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

## Command line

```sh
python3 -m pgara.bench                 # full benchmark study; writes results/results.json and results.csv
python3 -m pgara.bench --k 4           # a single register budget
python3 -m unittest -v tests.test_compiler   # 23 tests, about 30 seconds
```

---

## Team

| Member | Registration No. | Role |
|---|---|---|
| Shreyans Chowdry | 24BDS0114 | Core pipeline design, lexical and syntax analysis, AST construction, intermediate code generation |
| Samrender Singh Saini | 24BCE2865 | Semantic analysis, scope resolution and symbol table management |
| Karthikeya Jami | 24BCE2136 | Code optimisation engine and target assembly / machine code generation |
| Abhishek Kumar | 24BCE0585 | Runtime environment, test suite and benchmarking |
| Nishanth Kumar | 24BAI0194 | Web GUI, pipeline visualisation interface and documentation |

The `paper` folder holds the IEEE manuscript (`pgara.tex`, its compiled PDF and the files needed to rebuild it with `pdflatex pgara.tex`, run twice). The `guide` folder holds **PGARA-Project-Guide.pdf**, a plain-language explanation of the whole project, the research behind it, the code and the website.
