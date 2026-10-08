"""Test-suite for the PGARA compiler (standard library unittest only).

    python3 -m unittest discover -s tests -v
"""

import itertools
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pgara import lexer, parser, irgen, cfg, ssa, interp, regalloc  # noqa: E402
from pgara.grammar import grammar_report  # noqa: E402
from pgara.pipeline import compile_source, frontend, build_ssa_module, optimize_module  # noqa: E402
from pgara.bench import SUITE, load  # noqa: E402


def front(src):
    report, program, analyzer = frontend(src)
    return report, program


def ssa_module(src, opt=True):
    report, program = front(src)
    errors = [d for d in report["diagnostics"] if d["severity"] == "error"]
    assert not errors, errors
    module, _ = build_ssa_module(program)
    if opt:
        optimize_module(module, 2)
    return module


class LexerTests(unittest.TestCase):
    def test_maximal_munch_and_keywords(self):
        toks, errs = lexer.tokenize("int x<=y; if(a==b&&c!=d) x+=1; x++;")
        self.assertEqual(errs, [])
        lex = [t.lexeme for t in toks if t.kind != "EOF"]
        self.assertIn("<=", lex)
        self.assertIn("==", lex)
        self.assertIn("&&", lex)
        self.assertIn("+=", lex)
        self.assertIn("++", lex)
        self.assertEqual(toks[0].kind, "KW")
        self.assertEqual(toks[1].kind, "ID")

    def test_comments_and_positions(self):
        toks, errs = lexer.tokenize("// line\n/* block\n */ int a;")
        self.assertEqual(errs, [])
        self.assertEqual((toks[0].lexeme, toks[0].line, toks[0].col), ("int", 3, 5))

    def test_errors_are_recovered(self):
        toks, errs = lexer.tokenize("int a = 3 $ 4; int 9x;")
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("unexpected character" in e.message for e in errs))
        self.assertTrue(any("malformed number" in e.message for e in errs))


class GrammarTests(unittest.TestCase):
    def test_grammar_is_ll1_except_dangling_else(self):
        g = grammar_report()
        self.assertTrue(g["is_ll1_modulo_dangling_else"])
        self.assertEqual(len(g["conflicts"]), 1)
        self.assertEqual(g["conflicts"][0]["nonterminal"], "ElsePart")

    def test_first_follow_samples(self):
        g = grammar_report()
        self.assertIn("(", g["first"]["Primary"])
        self.assertIn("NUM", g["first"]["Expr"])
        self.assertIn(";", g["follow"]["Expr"])
        self.assertIn("ε", g["first"]["StmtList"])


class ParserTests(unittest.TestCase):
    def parse(self, src):
        toks, _ = lexer.tokenize(src)
        return parser.parse(toks)

    def test_precedence_and_associativity(self):
        prog, errs = self.parse("int main(){ return 1 - 2 - 3 * 4; }")
        self.assertEqual(errs, [])
        ret = prog.decls[0].body.stmts[0].value
        self.assertEqual(ret.op, "-")              # (1 - 2) - (3 * 4)
        self.assertEqual(ret.left.op, "-")
        self.assertEqual(ret.right.op, "*")

    def test_dangling_else_binds_to_nearest_if(self):
        prog, errs = self.parse("int main(){ if (1) if (0) print(1); else print(2); return 0; }")
        self.assertEqual(errs, [])
        outer = prog.decls[0].body.stmts[0]
        self.assertIsNone(outer.other)
        self.assertIsNotNone(outer.then.other)

    def test_panic_mode_reports_several_errors(self):
        prog, errs = self.parse("int main(){ int x = ; x = 3 + ; return 0; }")
        self.assertGreaterEqual(len(errs), 2)


class SemanticTests(unittest.TestCase):
    def diags(self, src):
        report, _ = front(src)
        return [d["message"] for d in report["diagnostics"] if d["severity"] == "error"]

    def test_scope_and_shadowing(self):
        report, program = front("int x; int main(){ int x = 1; { int x = 2; print(x); } print(x); return 0; }")
        self.assertEqual([d for d in report["diagnostics"] if d["severity"] == "error"], [])
        unames = {s["uname"] for sc in report["symbols"] for s in sc["symbols"] if s["name"] == "x"}
        self.assertEqual(len(unames), 3)

    def test_errors(self):
        msgs = self.diags("""
            int f(int a, int b[]) { return a; }
            void g() { }
            int main() {
              int y; int y;
              z = 1;
              f(1);
              int arr[4];
              f(arr, 2);
              y = g();
              break;
              return;
            }""")
        text = "\n".join(msgs)
        self.assertIn("redeclaration of 'y'", text)
        self.assertIn("undeclared variable 'z'", text)
        self.assertIn("expects 2 argument(s)", text)
        self.assertIn("must be an int", text)
        self.assertIn("must be an array name", text)
        self.assertIn("void function 'g' used in an expression", text)
        self.assertIn("'break' outside of a loop", text)
        self.assertIn("must return a value", text)

    def test_missing_main(self):
        self.assertIn("program has no 'main' function", self.diags("int f() { return 1; }"))


class SSATests(unittest.TestCase):
    def test_single_assignment_and_dominance(self):
        for name, _, train, _ in SUITE:
            module = ssa_module(load(name), opt=False)
            for fn in module.functions.values():
                defs = [i.dst for b in fn.blocks for i in b.instrs if i.dst is not None]
                self.assertEqual(len(defs), len(set(defs)), f"{name}:{fn.name} not single-assignment")
                idom = cfg.dominators(fn)
                def_block = {i.dst: b.name for b in fn.blocks for i in b.instrs if i.dst is not None}
                for b in fn.blocks:
                    for i in b.instrs:
                        if i.op == "phi":
                            for p, v in i.phi.items():
                                if isinstance(v, str):
                                    self.assertTrue(cfg.dominates(idom, def_block[v], p))
                        else:
                            for v in i.uses():
                                self.assertTrue(cfg.dominates(idom, def_block[v], b.name),
                                                f"{name}: use of {v} in {b.name} not dominated")

    def test_ssa_and_optimisation_preserve_semantics(self):
        for name, _, train, _ in SUITE:
            report, program = front(load(name))
            module = irgen.generate(program)
            for fn in module.functions.values():
                cfg.build_cfg(fn)
            before = interp.run(module, train, 20_000_000)
            for fn in module.functions.values():
                ssa.construct_ssa(fn)
            after_ssa = interp.run(module, train, 20_000_000)
            optimize_module(module, 2)
            after_opt = interp.run(module, train, 20_000_000)
            self.assertIsNone(before.error)
            self.assertEqual(before.output, after_ssa.output, name)
            self.assertEqual(before.output, after_opt.output, name)
            self.assertLessEqual(after_opt.steps, before.steps, name)


class OptimizerTests(unittest.TestCase):
    def test_constant_folding_and_dead_branches(self):
        module = ssa_module("int main(){ int a = 6; int b = a * 7; if (b == 42) print(b); else print(0); return 0; }")
        main = module.functions["main"]
        text = [str(i) for b in main.blocks for i in b.instrs]
        self.assertIn("print 42", text)
        self.assertNotIn("print 0", text)
        self.assertEqual(len(main.blocks), 1)

    def test_gvn_removes_common_subexpressions(self):
        module = ssa_module("int main(){ int a = input(); int b = input(); print(a*b + a*b); return 0; }")
        muls = [i for b in module.functions["main"].blocks for i in b.instrs if i.op == "mul"]
        self.assertEqual(len(muls), 1)


class ChordalTests(unittest.TestCase):
    def test_mcs_on_chordal_and_non_chordal_graphs(self):
        tri = {"a": {"b", "c"}, "b": {"a", "c", "d"}, "c": {"a", "b", "d"}, "d": {"b", "c"}}
        order = regalloc.maximum_cardinality_search(list(tri), tri, lambda v: v)
        ok, clique = regalloc.verify_peo(order, tri)
        self.assertTrue(ok)
        self.assertEqual(clique, 3)
        c4 = {"a": {"b", "d"}, "b": {"a", "c"}, "c": {"b", "d"}, "d": {"a", "c"}}
        order = regalloc.maximum_cardinality_search(list(c4), c4, lambda v: v)
        self.assertFalse(regalloc.verify_peo(order, c4)[0])

    def test_ssa_interference_graphs_are_chordal(self):
        for name, _, _, _ in SUITE:
            module = ssa_module(load(name))
            for fn in module.functions.values():
                fa = regalloc.FunctionAnalysis(fn)
                self.assertTrue(regalloc.chordal_structure(fa)["is_chordal"], f"{name}:{fn.name}")


class MDPTests(unittest.TestCase):
    def build(self, src):
        module = ssa_module(src)
        return regalloc.FunctionAnalysis(module.functions["main"])

    def test_policy_iteration_matches_value_iteration(self):
        fa = self.build(load("05_rarebranch"))
        P = regalloc.static_probabilities(fa)
        rpo = {b: i for i, b in enumerate(cfg.reverse_postorder(fa.fn))}
        for v in fa.values:
            mdp = regalloc.ValueMDP(fa, v, P, rpo)
            VR, VM, _, _ = mdp.policy_iteration(0.95)
            VR2, VM2, _ = mdp.value_iteration(0.95, epsilon=1e-10)
            for b in mdp.blocks:
                self.assertAlmostEqual(VR[b], VR2[b], places=5)
                self.assertAlmostEqual(VM[b], VM2[b], places=5)

    def test_hand_computed_single_block_gain(self):
        # x is defined once and used twice in straight-line code.
        fa = self.build("int main(){ int x = input(); print(x); print(x + 1); return 0; }")
        P = regalloc.static_probabilities(fa)
        gains, _, _ = regalloc.compute_gains(fa, P)
        cm = regalloc.CostModel
        # def: sigma vs store; first use forwarded? no (print follows input directly -> forwarded)
        expected = (1 * cm.SAVE + cm.STORE) + (1 * cm.SAVE + cm.MOVE) + (1 * cm.SAVE + cm.LOAD)
        self.assertAlmostEqual(gains["x"], expected)

    def test_hot_values_outbid_cold_ones(self):
        module = ssa_module(load("05_rarebranch"))
        counts = interp.run(module, [7, 10]).edge_counts["main"]
        fa = regalloc.FunctionAnalysis(module.functions["main"])
        P = regalloc.profiled_probabilities(fa, counts)
        gains, _, _ = regalloc.compute_gains(fa, P)
        hot = [v for v in gains if v.startswith("sum.")]
        cold = [v for v in gains if v.startswith("errSpan.")]
        self.assertGreater(max(gains[v] for v in hot), 10 * max(gains[v] for v in cold))


class AuctionTests(unittest.TestCase):
    def test_capacity_binding_and_nash_property(self):
        for name, _, train, _ in SUITE:
            module = ssa_module(load(name))
            counts = interp.run(module, train, 20_000_000).edge_counts
            for fn in module.functions.values():
                fa = regalloc.FunctionAnalysis(fn)
                ch = regalloc.chordal_structure(fa)
                for k in (2, 3, 5):
                    al = regalloc.allocate_function(fa, "pgara", k, counts.get(fn.name, {}), ch)
                    # No two interfering values share a register, and r < k.
                    for v, r in al.reg.items():
                        self.assertLess(r, k)
                        for w in fa.adj[v]:
                            self.assertFalse(w in al.reg and al.reg[w] == r)
                    # Nash property: a spilled singleton with a positive bid has
                    # no register left free by its neighbours.
                    in_coalition = {v for g in al.extra.get("coalitions", []) for v in g}
                    for v in al.spilled:
                        if al.bids.get(v, 0) > 0 and v not in in_coalition:
                            free = set(range(k)) - {al.reg[w] for w in fa.adj[v] if w in al.reg}
                            self.assertFalse(free, f"{name}:{fn.name}: {v} could deviate")


class EndToEndTests(unittest.TestCase):
    def test_all_allocators_match_reference_output(self):
        for (name, _, train, test), k in itertools.product(SUITE, (2, 3, 4, 6)):
            r = compile_source(load(name), {"k": k, "train_inputs": train, "test_inputs": test,
                                            "interp_step_limit": 20_000_000, "sim_step_limit": 60_000_000})
            self.assertTrue(r["ok"])
            for a, t in r["targets"].items():
                self.assertTrue(t["stats"]["matches_reference"], f"{name} k={k} {a}: {t['stats']['error']}")

    def test_runtime_errors_are_reported_identically(self):
        src = "int a[10]; int main(){ int i = input(); a[i] = 1; print(10 / (i - 5)); return 0; }"
        for inputs, msg in (([12], "out of bounds"), ([5], "division by zero"), ([7], None)):
            r = compile_source(src, {"k": 3, "train_inputs": inputs})
            ref = r["execution"]["test"]["error"]
            if msg:
                self.assertIn(msg, ref)
            for t in r["targets"].values():
                self.assertEqual(t["stats"]["error"], ref)
        r = compile_source("int main(){ int z = input(); print(1 / z); return 0; }", {"k": 3, "train_inputs": [0]})
        self.assertIn("division by zero", r["execution"]["test"]["error"])
        for t in r["targets"].values():
            self.assertTrue(t["stats"]["matches_reference"])


if __name__ == "__main__":
    unittest.main()
