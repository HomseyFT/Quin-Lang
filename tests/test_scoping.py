"""Name resolution and frame layout.

Sema resolves every identifier to a Symbol and records the frame's symbols in
order; codegen only maps those Symbols onto slots. These tests pin the
behavior that used to depend on sema and codegen implementing scoping
identically and agreeing by hand.
"""

import unittest

from compiler.resolver import ImportResolver
from compiler.sema import SemanticAnalyzer
from tests.harness import QuinTestCase, STD_PATH, compile_source, run_source

from pathlib import Path
import tempfile


def analyze(source: str):
    """Compile far enough to inspect the semantic Context."""
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        resolved = ImportResolver(STD_PATH).resolve(entry)
        return SemanticAnalyzer().analyze(resolved.program)


class TestShadowing(QuinTestCase):
    def test_inner_block_shadows_outer(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1;
                if (true) { let x: int = 2; println(x); }
                println(x);
                return 0;
            }
            """,
            "2", "1",
        )

    def test_shadowed_outer_is_restored_after_the_block(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1;
                if (true) { let x: int = 2; x = x + 10; }
                println(x);
                return 0;
            }
            """,
            "1",
        )

    def test_initializer_sees_the_outer_binding(self):
        # `let x = x + 1` inside a block reads the outer x, because sema
        # resolves the initializer before defining the new name.
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 5;
                if (true) { let x: int = x + 1; println(x); }
                println(x);
                return 0;
            }
            """,
            "6", "5",
        )

    def test_parameter_can_be_shadowed(self):
        self.assertPrints(
            """
            fn f(n: int): int {
                if (true) { let n: int = 99; println(n); }
                return n;
            }
            fn main(): int { println(f(7)); return 0; }
            """,
            "99", "7",
        )

    def test_while_body_shadows(self):
        self.assertPrints(
            """
            fn main(): int {
                let t: int = 100;
                let i: int;
                while (i < 2) { let t: int = i; println(t); i = i + 1; }
                println(t);
                return 0;
            }
            """,
            "0", "1", "100",
        )


class TestSiblingScopes(QuinTestCase):
    def test_same_name_in_sibling_blocks_gets_distinct_storage(self):
        self.assertPrints(
            """
            fn main(): int {
                if (true) { let v: int = 10; println(v); }
                if (true) { let v: int; println(v); }
                return 0;
            }
            """,
            "10", "0",
        )

    def test_sibling_arrays_do_not_overlap(self):
        self.assertPrints(
            """
            fn main(): int {
                if (true) { let a: int[3]; a[0] = 1; a[2] = 3; println(a[0]); }
                if (true) { let a: int[2]; println(a[0]); println(a[1]); }
                return 0;
            }
            """,
            "1", "0", "0",
        )

    def test_declaration_in_a_branch_that_does_not_run(self):
        # The slot is still reserved, so the frame size must account for it.
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 7;
                if (false) { let y: int[4]; y[3] = 1; }
                println(x);
                return 0;
            }
            """,
            "7",
        )


class TestFrameLayout(QuinTestCase):
    def test_parameters_lead_the_frame(self):
        # CALL drops arguments into the leading locals, so parameters must be
        # the first symbols sema records.
        ctx = analyze(
            "fn f(a: int, b: int): int { let c: int; return a + b + c; } "
            "fn main(): int { return f(1, 2); }"
        )
        names = [s.name for s in ctx.frame_symbols["f"]]
        self.assertEqual(names[:2], ["a", "b"])
        self.assertEqual(names, ["a", "b", "c"])

    def test_nested_declarations_are_recorded_in_source_order(self):
        ctx = analyze(
            """
            fn main(): int {
                let a: int;
                if (true) { let b: int; } else { let c: int; }
                while (false) { let d: int; }
                return 0;
            }
            """
        )
        self.assertEqual(
            [s.name for s in ctx.frame_symbols["main"]], ["a", "b", "c", "d"]
        )

    def test_shadowed_names_are_distinct_symbols(self):
        ctx = analyze(
            "fn main(): int { let x: int; if (true) { let x: int; } return 0; }"
        )
        symbols = ctx.frame_symbols["main"]
        self.assertEqual([s.name for s in symbols], ["x", "x"])
        self.assertIsNot(symbols[0], symbols[1])

    def test_arrays_reserve_consecutive_slots(self):
        # Two 3-element arrays plus two scalars need 8 locals.
        code, functions, _, _ = compile_source(
            "fn main(): int { let a: int[3]; let b: int[3]; let i: int; let j: int; return 0; }"
        )
        main = next(f for f in functions if f.name == "main")
        self.assertEqual(main.num_locals, 8)

    def test_every_identifier_gets_a_binding(self):
        ctx = analyze(
            """
            fn f(n: int): int { return n; }
            fn main(): int {
                let x: int = 1;
                let a: int[2];
                let p: ptr;
                x = x + f(x);
                a[x] = x;
                p = @a[0];
                return x;
            }
            """
        )
        # Bindings cover parameters, declarations, reads, assignment targets,
        # and address-of targets alike.
        self.assertTrue(ctx.binding)
        self.assertTrue(all(sym is not None for sym in ctx.binding.values()))


class TestVmAsmScope(QuinTestCase):
    def test_resolves_a_local(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 5;
                vm_asm { load_local x; push_int 1; add; store_local x; }
                println(x);
                return 0;
            }
            """,
            "6",
        )

    def test_resolves_a_parameter(self):
        self.assertPrints(
            """
            fn f(a: int): int {
                vm_asm { load_local a; push_int 1; add; store_local a; }
                return a;
            }
            fn main(): int { println(f(41)); return 0; }
            """,
            "42",
        )

    def test_resolves_the_innermost_shadowing_binding(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1;
                if (true) {
                    let x: int = 40;
                    vm_asm { load_local x; push_int 2; add; store_local x; }
                    println(x);
                }
                println(x);
                return 0;
            }
            """,
            "42", "1",
        )

    def test_unknown_local(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { load_local nope; } return 0; }",
            "unknown local 'nope'",
        )

    def test_array_must_be_indexed_explicitly(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; vm_asm { load_local a; } return 0; }",
            "is an array; index it explicitly",
        )

    def test_unknown_instruction(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { frobnicate; } return 0; }",
            "Unknown or malformed vm_asm instruction",
        )

    def test_mod_is_not_in_the_vm_asm_subset(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 7; vm_asm { load_local x; push_int 2; mod; } return 0; }",
            "Unknown or malformed vm_asm instruction",
        )

    def test_push_int_requires_an_integer(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { push_int abc; } return 0; }",
            "push_int expects an integer literal",
        )


class TestVmAsmStackBalance(QuinTestCase):
    """A vm_asm block has no jumps, so its stack effect is the sum of its
    instructions and is decided at compile time. This used to survive codegen
    and surface as 'Unbalanced operand stack at RET', pointing at the function
    rather than at the block that caused it.
    """

    def test_a_leftover_value_is_a_compile_error(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { push_int 1; } return 0; }",
            "leaves 1 value(s) on the operand stack",
        )

    def test_the_error_points_at_the_block(self):
        self.assertCompileError(
            "fn main(): int {\n    vm_asm { push_int 1; }\n    return 0;\n}",
            "[2:5]",
        )

    def test_a_binary_op_short_one_operand_is_a_compile_error(self):
        # `add` nets -1, so a net-effect check would accept this. It needs two
        # operands and only one is there, so the second would come from the
        # enclosing frame.
        self.assertCompileError(
            "fn main(): int { let x: int; vm_asm { push_int 1; add; } return 0; }",
            "'add' needs 2 value(s) on the operand stack but the block has 1",
        )

    def test_a_bare_store_is_a_compile_error(self):
        self.assertCompileError(
            "fn main(): int { let x: int; vm_asm { store_local x; } return 0; }",
            "needs 1 value(s) on the operand stack but the block has 0",
        )

    def test_a_unary_op_on_an_empty_stack_is_a_compile_error(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { neg; } return 0; }",
            "'neg' needs 1 value(s) on the operand stack but the block has 0",
        )

    def test_a_balanced_block_still_compiles_and_runs(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 5;
                vm_asm {
                    load_local x;
                    push_int 1;
                    add;
                    store_local x;
                }
                println(x);
                return 0;
            }
            """,
            "6",
        )

    def test_unary_ops_do_not_change_the_depth(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 5;
                vm_asm { load_local x; neg; store_local x; }
                println(x);
                return 0;
            }
            """,
            "-5",
        )

    def test_a_comparison_consumes_two_and_pushes_one(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 3;
                vm_asm { load_local x; push_int 3; cmp_eq; store_local x; }
                println(x);
                return 0;
            }
            """,
            "1",
        )

    def test_an_empty_block_is_balanced(self):
        self.assertCompiles("fn main(): int { vm_asm { } return 0; }")

    def test_depth_may_rise_and_fall_within_the_block(self):
        # Balance is about the ends, not about every intermediate step.
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1;
                let y: int = 2;
                vm_asm {
                    load_local x;
                    load_local y;
                    load_local x;
                    add;
                    add;
                    store_local x;
                }
                println(x);
                return 0;
            }
            """,
            "4",
        )


class TestForLoopScoping(QuinTestCase):
    def test_loop_variable_does_not_leak(self):
        self.assertCompileError(
            "fn main(): int { for (let i = 0; i < 2; i = i + 1) { } println(i); return 0; }",
            "Undeclared variable 'i'",
        )

    def test_two_loops_may_reuse_the_name(self):
        self.assertPrints(
            """
            fn main(): int {
                for (let i = 0; i < 1; i = i + 1) { println(i); }
                for (let i = 5; i < 6; i = i + 1) { println(i); }
                return 0;
            }
            """,
            "0", "5",
        )

    def test_loop_variable_shadows_an_outer_name(self):
        self.assertPrints(
            """
            fn main(): int {
                let i: int = 99;
                for (let i = 0; i < 2; i = i + 1) { println(i); }
                println(i);
                return 0;
            }
            """,
            "0", "1", "99",
        )

    def test_body_may_shadow_the_loop_variable(self):
        self.assertPrints(
            """
            fn main(): int {
                for (let i = 0; i < 2; i = i + 1) {
                    let i: int = 7;
                    println(i);
                }
                return 0;
            }
            """,
            "7", "7",
        )

    def test_sibling_loop_variables_get_distinct_slots(self):
        ctx = analyze(
            """
            fn main(): int {
                for (let i = 0; i < 1; i = i + 1) { }
                for (let i = 0; i < 1; i = i + 1) { }
                return 0;
            }
            """
        )
        frame = ctx.frame_symbols["main"]
        loop_vars = [s for s in frame if s.name == "i"]
        self.assertEqual(len(loop_vars), 2)
        self.assertIsNot(loop_vars[0], loop_vars[1])


class TestScopeReleaseDoesNotDisturbScoping(QuinTestCase):
    """Releasing a scope's slots must not change what any name means.

    The clears are emitted from the symbols sema recorded per scope, so a
    shadowing or sibling declaration must have its own slot cleared and not
    somebody else's.
    """

    def test_releasing_an_inner_scope_leaves_the_outer_binding_alone(self):
        self.assertPrints(
            "struct Node { v: int }\n"
            """
            fn main(): int {
                let n: Node = Node { v: 1 };
                { let n: Node = Node { v: 2 }; println(n.v); }
                println(n.v);
                return 0;
            }
            """,
            "2", "1",
        )

    def test_a_shadowed_reference_survives_the_inner_scope(self):
        self.assertPrints(
            "struct Node { v: int }\n"
            """
            fn main(): int {
                let outer: Node = Node { v: 7 };
                for (let i = 0; i < 3; i = i + 1) {
                    let outer: Node = Node { v: i };
                }
                gc();
                println(outer.v);
                return 0;
            }
            """,
            "7",
        )

    def test_sibling_scopes_release_their_own_slots(self):
        ctx = analyze(
            "struct Node { v: int }\n"
            """
            fn main(): int {
                { let a: Node = Node { v: 1 }; }
                { let a: Node = Node { v: 2 }; }
                return 0;
            }
            """
        )
        frame = ctx.frame_symbols["main"]
        both = [s for s in frame if s.name == "a"]
        self.assertEqual(len(both), 2)
        self.assertIsNot(both[0], both[1], "siblings must be distinct symbols")
        # Each scope records exactly its own symbol.
        recorded = [syms for syms in ctx.scope_refs.values()]
        self.assertIn([both[0]], recorded)
        self.assertIn([both[1]], recorded)

    def test_only_reference_typed_declarations_are_recorded(self):
        ctx = analyze(
            "struct Node { v: int }\n"
            """
            fn main(): int {
                {
                    let count: int = 1;
                    let flag: bool = true;
                    let n: Node = Node { v: 1 };
                }
                return 0;
            }
            """
        )
        recorded = [s.name for syms in ctx.scope_refs.values() for s in syms]
        self.assertEqual(recorded, ["n"], "ints and bools are not roots")

    def test_a_scope_with_no_references_records_nothing(self):
        ctx = analyze(
            "fn main(): int { { let a: int = 1; } return 0; }"
        )
        self.assertEqual(ctx.scope_refs, {})

    def test_frame_layout_is_unchanged_by_releasing(self):
        # Clears reuse existing slots; they must not allocate new ones.
        ctx = analyze(
            "struct Node { v: int }\n"
            """
            fn main(): int {
                for (let i = 0; i < 3; i = i + 1) { let n: Node = Node { v: i }; }
                return 0;
            }
            """
        )
        names = [s.name for s in ctx.frame_symbols["main"]]
        self.assertEqual(names, ["i", "n"])


class TestBlockScoping(QuinTestCase):
    def test_bare_block_introduces_a_scope(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1;
                { let x: int = 2; println(x); }
                println(x);
                return 0;
            }
            """,
            "2", "1",
        )

    def test_declaration_does_not_escape_a_bare_block(self):
        self.assertCompileError(
            "fn main(): int { { let x: int = 1; } println(x); return 0; }",
            "Undeclared variable 'x'",
        )

    def test_bare_block_declarations_reach_the_frame(self):
        ctx = analyze("fn main(): int { { let x: int = 1; } return 0; }")
        self.assertIn("x", [s.name for s in ctx.frame_symbols["main"]])


if __name__ == "__main__":
    unittest.main()
