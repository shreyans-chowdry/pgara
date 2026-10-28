# PGARA — Demo Video Script (about 6 minutes 30 seconds)

**Team 14 · Compiler Design · L43+L44**

## How to record it on Google Meet

1. **Joining.** All five join the Meet, cameras on. One person starts **Record** (Activities → Recording); a Workspace account such as your VIT account is needed for this.
2. **Screen.** One screen-sharer, the **driver** (Shreyans), shares the browser tab for the whole video. Each speaker talks in turn while the driver does the action written in *italics*. Speakers don't need to share their own screens.
3. **Before you start,** the driver opens three things:
   - https://pgara.vercel.app, or http://127.0.0.1:8765 after `scripts/run_gui.sh`,
   - the GitHub repository in a second tab,
   - a terminal in the project folder, for parts 2 and 6. Share the whole screen, or switch the shared tab, when the terminal is needed.
4. **Settings used throughout:** Program **Rare error branch**, Registers **k = 4**, Training input **7 10**, Test input **13 10**. Zoom the browser to 110–125% so the text is readable in the recording.
5. **During the recording:**
   - Everyone stays muted except the current speaker.
   - Each speaker ends with a short hand-off, e.g. "Over to Samrender."
   - Do a quick rehearsal first, so the total stays between 4 and 7 minutes.
6. **After the meeting,** the recording arrives in the organiser's Google Drive (Meet Recordings folder). Download it as MP4 and share it so it can be added to `docs/demo/` in the repository.

Times are approximate.

---

## 1. Introduction — Shreyans Chowdry (0:00 – 0:45)

**Driver shows:** the home page of the Compiler Studio.

> "Hello, we are Team 14. I'm Shreyans Chowdry, and with me are Samrender Singh Saini, Karthikeya Jami, Abhishek Kumar and Nishanth Kumar. Our project is PGARA, Profile-Guided Adaptive Register Allocation.
>
> A processor has only a few registers, so the compiler must decide which values stay in registers and which go to slower memory. Classic allocators guess how often each branch runs. PGARA measures it instead: it runs the program once, builds a small Markov decision process for every value to compute the cycles it would save, and then auctions the registers among the values. We built a complete compiler around it, with this website that shows every phase. Let's walk you through it."

---

## 2. Setup and the Studio — Nishanth Kumar (0:45 – 1:35)

**Driver shows:** the GitHub README, then the terminal, then the website.

> "I'll show how anyone can run the project. The README lists the requirements: only Python 3.8 or newer, with no extra packages.
>
> *(Run `scripts/setup.sh`.)* The setup script checks the Python version and verifies all 22 benchmark programs.
>
> *(Run `scripts/run_gui.sh`; the browser opens.)* This is PGARA Compiler Studio. On the left is the MiniC editor. At the top are the controls:
> - **Program** loads one of our benchmarks.
> - **Registers k** sets how many CPU registers the allocator can use.
> - **Training input** is the run we profile.
> - **Test input** is a different run that we measure, so the comparison is fair.
>
> *(Select Rare error branch, k = 4, inputs 7 10 and 13 10.)* With Live compile on, the program recompiles as I type. Each tab on the right is one phase of the compiler, in order."

---

## 3. Front end — Shreyans Chowdry (1:35 – 2:30)

**Driver shows:** the Tokens, AST, TAC and Grammar tabs.

> "**Tokens:** the lexer is a maximal-munch DFA, so it always takes the longest token. `<=` and `++` become single tokens, each colour-coded by kind.
>
> **AST:** the recursive-descent LL(1) parser builds this tree. Multiplication sits below addition, which is how precedence is encoded.
>
> **TAC:** we translate the tree into three-address code, one operation per line. `&&` and `||` become jumps, so short-circuiting is exact.
>
> **Grammar:** the tool computes FIRST and FOLLOW sets and the LL(1) table for our 41 nonterminals and 94 rules. The only conflict is the dangling else, which we resolve by attaching it to the nearest if."

---

## 4. Semantic analysis — Samrender Singh Saini (2:30 – 3:10)

**Driver shows:** the Symbols tab, then the editor.

> "This is the Symbols tab. Semantic analysis keeps a stack of scopes. Every variable gets a unique IR name, so the `i` of an inner loop becomes `i#1` and never clashes with an outer `i`. Types, function arity and array use are all checked here.
>
> *(Delete a semicolon, or use an undeclared variable.)* The error appears immediately, with its line and column, and clicking it jumps to the line. *(Undo the change.)* Fixed again."

---

## 5. Optimiser, profile and the PGARA allocator — Karthikeya Jami (3:10 – 4:25)

**Driver shows:** the SSA & Optimiser tab, then CFG, then Allocation.

> "**SSA & Optimiser:** the code is converted into SSA form, with φ-functions at the loop head, and then optimised with constant propagation, GVN and dead-code elimination.
>
> **CFG:** blocks are coloured from blue (rare) to red (hot). Each edge shows the measured probability and, in brackets, the static guess. Here the error branch runs about 1% of the time, but the static guess says 50%. That difference is exactly what PGARA exploits.
>
> **Allocation:** for every value we solve a two-state MDP, register or memory, which gives G(v), the expected cycles saved per call. The hot counters such as `cnt` and `weighted` are worth about 20,000 cycles; the error counters are worth about 180. Loop variables bid together as a coalition: `i#1.3` alone is worth 12,288, but it bids 94,223 with its partner and shares register r1.
>
> *(Scroll to the auction rounds.)* Whenever more values are alive than there are registers, the highest bids win (green) and the rest are spilled (red). Best-response dynamics then settle the result into a Nash equilibrium."

---

## 6. Results and testing — Abhishek Kumar (4:25 – 5:40)

**Driver shows:** the Run & Metrics tab, then the terminal, then `results/README.md` on GitHub.

> "I worked on the simulator, the tests and the benchmarking. **Run & Metrics** runs the generated PG-RISC code on our cycle-counting simulator and compares the allocators. On this program PGARA needs 338,000 cycles against 516,000 for linear scan, and every allocator's output matches the reference interpreter.
>
> *(Run `scripts/run_tests.sh`; show it ending with OK.)* Our 27 unit tests cover every phase, including a hand-computed gain, the Nash property and end-to-end correctness. They cover 94% of the code.
>
> *(Open the results summary.)* Across 17 programs, seven of them translated from MiBench and BEEBS, and register budgets from 3 to 32, all 1,428 runs are correct. At four registers PGARA uses:
> - 21.8% fewer cycles than linear scan,
> - 3.7% fewer than Chaitin–Briggs with profiled costs,
> - 2.6% fewer than the same engine without a profile.
>
> We also tested a misleading training input: PGARA keeps the same allocation up to a 20% error rate, so the profile must be representative."

---

## 7. Limitations, repository and conclusion — Nishanth Kumar (5:40 – 6:20)

**Driver shows:** the GitHub repository front page.

> "To be honest about the limits:
> - the benefit appears when registers are scarce, eight or fewer;
> - at three registers Chaitin–Briggs packs some programs better;
> - very long live ranges make allocation slower.
>
> Everything needed to reproduce our work is in this repository: the source code, the benchmarks and inputs, configuration files, setup and run scripts, the raw results, the manuscript with its LaTeX sources, and this video. Running `scripts/run_experiments.sh` regenerates every result in the paper."

---

## 8. Closing — Shreyans Chowdry (6:20 – 6:30)

> "So PGARA measures instead of guessing, prices every value with an exact MDP, and auctions the registers, all without graph colouring. Thank you for watching."

---

### Hand-offs (say at the end of each part)
1 → "Nishanth will show how to set it up."
2 → "Back to Shreyans for the front end."
3 → "Samrender will explain semantic analysis."
4 → "Karthikeya will take you through the allocator."
5 → "Abhishek will show the results and tests."
6 → "Nishanth will cover the limitations and the repository."
7 → "Shreyans will close."
