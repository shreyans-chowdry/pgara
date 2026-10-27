"""End-to-end driver: source text -> tokens -> AST -> symbol table -> TAC ->
CFG -> SSA -> optimised SSA -> profile -> PGARA allocation -> PG-RISC code
-> simulation.  `compile_source` returns a JSON-serialisable report that the
web GUI renders and the benchmark harness consumes."""

import time

from . import lexer, parser, semantic, irgen, cfg, ssa, optimize, interp, regalloc, codegen, simulator
from .grammar import grammar_report
from .ir import format_instr

DEFAULT_OPTIONS = {
    "k": 4,
    "opt_level": 2,
    "train_inputs": [],
    "test_inputs": [],
    "allocators": list(regalloc.ALLOCATORS),
    "primary": "pgara",
    "interp_step_limit": 3_000_000,
    "sim_step_limit": 12_000_000,
}


def _diag(phase, severity, message, line, col):
    return {"phase": phase, "severity": severity, "message": message, "line": line, "col": col}


def frontend(source):
    """Lexing, parsing and semantic analysis.  Returns (report, ast, analyzer)."""
    report = {"diagnostics": []}
    t0 = time.perf_counter()
    tokens, lex_errors = lexer.tokenize(source)
    report["tokens"] = [t.to_dict() for t in tokens]
    for e in lex_errors:
        report["diagnostics"].append(_diag("lexical", "error", e.message, e.line, e.col))
    program, parse_errors = parser.parse(tokens)
    for e in parse_errors:
        report["diagnostics"].append(_diag("syntax", "error", e.message, e.line, e.col))
    report["ast"] = program.to_dict()
    analyzer = None
    if not lex_errors and not parse_errors:
        analyzer = semantic.analyze(program)
        report["diagnostics"].extend(d.to_dict() for d in analyzer.diags)
        report["symbols"] = [s.to_dict() for s in analyzer.table.scopes]
        report["ast"] = program.to_dict()      # now decorated with types
    else:
        report["symbols"] = []
    report["timings"] = {"frontend_ms": (time.perf_counter() - t0) * 1000}
    return report, program, analyzer


def has_errors(report):
    return any(d["severity"] == "error" for d in report["diagnostics"])


def build_ssa_module(program):
    """TAC, CFG and SSA construction.  Returns (module, stages)."""
    module = irgen.generate(program)
    stages = {"tac": {}, "ssa": {}}
    for name, fn in module.functions.items():
        stages["tac"][name] = fn.linear_listing()
        cfg.build_cfg(fn)
        info = ssa.construct_ssa(fn)
        stages["ssa"][name] = {"listing": fn.listing(), "phis": info["phis"]}
    return module, stages


def optimize_module(module, level):
    logs = {}
    for name, fn in module.functions.items():
        before = sum(len(b.instrs) for b in fn.blocks)
        log = optimize.optimize_function(fn, level)
        after = sum(len(b.instrs) for b in fn.blocks)
        logs[name] = {"passes": log, "instrs_before": before, "instrs_after": after}
    return logs


def evaluate_gain(fa, alloc, P):
    """Realised expected gain of an allocation, scored by the MDP under P."""
    gains, _, _ = regalloc.compute_gains(fa, P)
    return sum(gains[v] for v in alloc.reg), gains


def compile_source(source, options=None):
    opts = dict(DEFAULT_OPTIONS)
    opts.update(options or {})
    k = int(opts["k"])
    report, program, analyzer = frontend(source)
    report["grammar"] = grammar_report()
    report["options"] = {key: opts[key] for key in ("k", "opt_level", "train_inputs", "test_inputs", "primary")}
    if has_errors(report):
        report["ok"] = False
        return report

    t0 = time.perf_counter()
    module, stages = build_ssa_module(program)
    report.update(stages)
    report["opt_log"] = optimize_module(module, int(opts["opt_level"]))
    report["optimized"] = {name: {"listing": fn.listing()} for name, fn in module.functions.items()}
    report["timings"]["middle_ms"] = (time.perf_counter() - t0) * 1000

    # Reference execution of the optimised SSA program on the training input = profile.
    t_prof = time.perf_counter()
    train = interp.run(module, opts["train_inputs"], opts["interp_step_limit"])
    report["timings"]["profiling_ms"] = (time.perf_counter() - t_prof) * 1000
    test = interp.run(module, opts["test_inputs"] or opts["train_inputs"], opts["interp_step_limit"])
    report["execution"] = {"train": train.to_dict(), "test": test.to_dict()}

    t0 = time.perf_counter()
    analyses = {}
    chordal = {}
    for name, fn in module.functions.items():
        fa = regalloc.FunctionAnalysis(fn)
        analyses[name] = fa
        chordal[name] = regalloc.chordal_structure(fa)

    report["timings"]["analysis_ms"] = (time.perf_counter() - t0) * 1000
    allocations = {a: {} for a in opts["allocators"]}
    report["timings"]["per_allocator_ms"] = {}
    for a in opts["allocators"]:
        ta = time.perf_counter()
        for name, fa in analyses.items():
            allocations[a][name] = regalloc.allocate_function(
                fa, a, k, train.edge_counts.get(name, {}), chordal[name])
        report["timings"]["per_allocator_ms"][a] = (time.perf_counter() - ta) * 1000
    report["timings"]["allocation_ms"] = (time.perf_counter() - t0) * 1000

    # Per-function analysis report (interference graph, liveness, MDP gains).
    functions = {}
    for name, fa in analyses.items():
        fn = fa.fn
        static_P = regalloc.static_probabilities(fa)
        prof_P = regalloc.profiled_probabilities(fa, train.edge_counts.get(name, {}))
        test_P = regalloc.profiled_probabilities(fa, test.edge_counts.get(name, {}))
        edges = []
        for b in fn.blocks:
            for s in b.succs:
                edges.append({
                    "from": b.name, "to": s,
                    "count": train.edge_counts.get(name, {}).get((b.name, s), 0),
                    "p_static": round(static_P[b.name].get(s, 0.0), 4),
                    "p_profile": round(prof_P[b.name].get(s, 0.0), 4),
                })
        ch = chordal[name]
        functions[name] = {
            "blocks": [{"name": b.name, "instrs": [format_instr(i) for i in b.instrs],
                        "live_in": sorted(fa.live_in[b.name]), "live_out": sorted(fa.live_out[b.name]),
                        "loop_depth": fa.depth[b.name],
                        "count": train.block_counts.get(name, {}).get(b.name, 0)} for b in fn.blocks],
            "edges": edges,
            "back_edges": [list(e) for e in fa.back_edges],
            "interference": {
                "nodes": fa.values,
                "edges": sorted({tuple(sorted((v, w))) for v in fa.values for w in fa.adj[v]}),
            },
            "chordal": {"is_chordal": ch["is_chordal"], "max_clique": ch["max_clique"],
                        "mcs_order": ch["order"], "peo": ch["peo"]},
            "allocations": {},
        }
        for a in opts["allocators"]:
            al = allocations[a][name]
            realised, _ = evaluate_gain(fa, al, test_P)
            functions[name]["allocations"][a] = {
                "registers": {v: f"r{r}" for v, r in al.reg.items()},
                "spilled": al.spilled,
                "gains": {v: round(g, 4) for v, g in al.gains.items()},
                "bids": {v: round(g, 4) for v, g in al.bids.items()},
                "coalitions": [list(g) for g in al.extra.get("coalitions", [])],
                "deviations": al.extra.get("deviations", 0),
                "sweeps": al.sweeps,
                "auction": al.rounds,
                "conceded": al.extra.get("conceded", []),
                "realised_gain": realised,
                "live_range_blocks": al.extra.get("live_range_blocks", {}),
                "intervals": al.extra.get("intervals", {}),
            }
    report["functions"] = functions

    # Code generation and simulation for every allocator.
    targets = {}
    for a in opts["allocators"]:
        program_code, fcode = codegen.generate_module(module, analyses, allocations[a], k)
        sim = simulator.simulate(program_code, fcode, module.globals,
                                 opts["test_inputs"] or opts["train_inputs"], opts["sim_step_limit"])
        stats = sim.to_dict()
        stats["matches_reference"] = (stats["output"] == test.output and stats["error"] == test.error)
        stats["code_size"] = sum(1 for i in program_code if i.op != "label")
        stats["static_spills"] = sum(len(allocations[a][n].spilled) for n in analyses)
        stats["realised_gain"] = sum(functions[n]["allocations"][a]["realised_gain"] for n in analyses)
        targets[a] = {
            "asm": [i.to_dict() for i in program_code],
            "stats": stats,
        }
    report["targets"] = targets
    report["ok"] = True
    return report
