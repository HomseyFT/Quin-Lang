"""Grammar: precedence, associativity, and what the parser refuses."""

import unittest

from tests.harness import QuinTestCase


class TestPrecedence(QuinTestCase):
    def test_multiplication_binds_tighter_than_addition(self):
        self.assertExprPrints("2 + 3 * 4", "14")

    def test_modulo_binds_like_multiplication(self):
        self.assertExprPrints("1 + 7 % 4", "4")

    def test_unary_minus_binds_tighter_than_multiplication(self):
        self.assertExprPrints("0 - 2 * 3", "-6")

    def test_parentheses_override(self):
        self.assertExprPrints("(2 + 3) * 4", "20")

    def test_relational_binds_tighter_than_equality(self):
        # Parsed as (1 < 2) == true, not 1 < (2 == true), which would not typecheck.
        self.assertExprPrints("1 < 2 == true", "true")

    def test_comparison_binds_tighter_than_and(self):
        self.assertExprPrints("1 < 2 && 3 < 4", "true")

    def test_and_binds_tighter_than_or(self):
        # false && false || true  ==  (false && false) || true
        self.assertExprPrints("false && false || true", "true")

    def test_not_binds_tighter_than_and(self):
        self.assertExprPrints("!false && true", "true")

    def test_arithmetic_is_left_associative(self):
        self.assertExprPrints("10 - 3 - 2", "5")

    def test_division_is_left_associative(self):
        self.assertExprPrints("100 / 5 / 2", "10")


class TestShortCircuit(QuinTestCase):
    def test_and_skips_right_side(self):
        self.assertPrints(
            """
            fn boom(): bool { println(999); return true; }
            fn main(): int {
                if (false && boom()) { println(1); }
                println(0);
                return 0;
            }
            """,
            "0",
        )

    def test_or_skips_right_side(self):
        self.assertPrints(
            """
            fn boom(): bool { println(999); return false; }
            fn main(): int {
                if (true || boom()) { println(1); }
                return 0;
            }
            """,
            "1",
        )


class TestPostfix(QuinTestCase):
    def test_call_then_index_chain(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                let i: int;
                a[0] = 5;
                i = 0;
                println(a[i]);
                return 0;
            }
            """,
            "5",
        )

    def test_index_expression_may_be_computed(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                a[2] = 7;
                println(a[1 + 1]);
                return 0;
            }
            """,
            "7",
        )


class TestSyntaxErrors(QuinTestCase):
    def test_missing_semicolon(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 1 return 0; }", "Expected ';'"
        )

    def test_assignment_is_not_an_expression(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let y: int; x = y = 0; return 0; }",
            "Expected ';' after assignment",
        )

    def test_if_requires_braces(self):
        self.assertCompileError(
            "fn main(): int { if (true) println(1); return 0; }",
            "Expected '{' to start block",
        )

    def test_if_requires_parens(self):
        self.assertCompileError(
            "fn main(): int { if true { println(1); } return 0; }", "Expected '('"
        )

    def test_include_must_precede_functions(self):
        self.assertCompileError(
            'fn main(): int { return 0; }\ninclude "std/math.ql";',
            "Expected 'fn' at function start",
        )

    def test_unterminated_vm_asm_block_does_not_hang(self):
        self.assertCompileError(
            "fn main(): int { vm_asm { push_int 1;", "Expected '}' after vm_asm block"
        )

    def test_vm_asm_instruction_without_a_semicolon_is_rejected(self):
        # It used to be dropped: the pending tokens were never flushed at '}',
        # so the block compiled to nothing and the program ran as if the
        # instruction had not been written.
        self.assertCompileError(
            "fn main(): int { vm_asm { push_int 5 } return 0; }",
            "Expected ';' after vm_asm instruction 'push_int 5'",
        )

    def test_vm_asm_semicolon_is_required_on_the_last_instruction_too(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 5; vm_asm { load_local x; push_int 1; add } return 0; }",
            "Expected ';' after vm_asm instruction 'add'",
        )

    def test_empty_vm_asm_block_is_allowed(self):
        self.assertPrints("fn main(): int { vm_asm { } println(1); return 0; }", "1")

    def test_missing_function_name(self):
        self.assertCompileError("fn (): int { return 0; }", "Expected function name")

    def test_array_size_must_be_literal(self):
        self.assertCompileError(
            "fn main(): int { let n: int = 3; let a: int[n]; return 0; }",
            "Expected array size after '['",
        )

    def test_expression_expected(self):
        self.assertCompileError(
            "fn main(): int { let x: int = ; return 0; }", "Expected expression"
        )

    def test_error_reports_location(self):
        message = self.assertCompileError(
            "fn main(): int {\n    let x: int = 1\n    return 0;\n}", "Expected ';'"
        )
        self.assertIn(":3:", message)


class TestForLoopForms(QuinTestCase):
    def test_declaring_init(self):
        self.assertPrints(
            "fn main(): int { for (let i: int = 0; i < 2; i = i + 1) { println(i); } return 0; }",
            "0", "1",
        )

    def test_inferred_init_type(self):
        self.assertPrints(
            "fn main(): int { for (let i = 0; i < 2; i = i + 1) { println(i); } return 0; }",
            "0", "1",
        )

    def test_assigning_init(self):
        self.assertPrints(
            "fn main(): int { let i: int; for (i = 0; i < 2; i = i + 1) { println(i); } return 0; }",
            "0", "1",
        )

    def test_empty_init(self):
        self.assertPrints(
            "fn main(): int { let i: int = 0; for (; i < 2; i = i + 1) { println(i); } return 0; }",
            "0", "1",
        )

    def test_empty_step(self):
        self.assertPrints(
            "fn main(): int { let i: int = 0; for (; i < 2;) { println(i); i = i + 1; } return 0; }",
            "0", "1",
        )

    def test_no_clauses_at_all_needs_a_break(self):
        self.assertPrints(
            "fn main(): int { let i: int = 0; for (;;) { i = i + 1; if (i == 2) { break; } } "
            "println(i); return 0; }",
            "2",
        )

    def test_call_as_step(self):
        self.assertPrints(
            "fn bump(): void { println(9); }\n"
            "fn main(): int { for (let i = 0; i < 2; bump()) { i = i + 1; } return 0; }",
            "9", "9",
        )

    def test_empty_body(self):
        self.assertPrints(
            "fn main(): int { let i: int = 0; for (; i < 3; i = i + 1) { } println(i); return 0; }",
            "3",
        )


class TestBlockStatement(QuinTestCase):
    def test_bare_block_runs_its_statements(self):
        self.assertPrints(
            "fn main(): int { { println(1); println(2); } return 0; }", "1", "2"
        )

    def test_empty_block(self):
        self.assertPrints("fn main(): int { { } println(1); return 0; }", "1")

    def test_nested_blocks(self):
        self.assertPrints(
            "fn main(): int { { { println(1); } } return 0; }", "1"
        )


class TestControlFlowSyntaxErrors(QuinTestCase):
    def test_for_requires_parens(self):
        self.assertCompileError(
            "fn main(): int { for let i = 0; i < 2; i = i + 1 { } return 0; }",
            "Expected '(' after 'for'",
        )

    def test_for_requires_braces(self):
        self.assertCompileError(
            "fn main(): int { for (let i = 0; i < 2; i = i + 1) println(i); return 0; }",
            "Expected '{' to start block",
        )

    def test_for_requires_condition_semicolon(self):
        self.assertCompileError(
            "fn main(): int { for (let i = 0; i < 2) { } return 0; }",
            "Expected ';' after for-loop condition",
        )

    def test_for_requires_init_semicolon(self):
        self.assertCompileError(
            "fn main(): int { let i: int; for (i = 0 i < 2; i = i + 1) { } return 0; }",
            "Expected ';' after for-loop initializer",
        )

    def test_for_requires_closing_paren(self):
        self.assertCompileError(
            "fn main(): int { for (let i = 0; i < 2; i = i + 1 { } return 0; }",
            "Expected ')' after for-loop clauses",
        )

    def test_break_requires_semicolon(self):
        self.assertCompileError(
            "fn main(): int { while (true) { break } return 0; }",
            "Expected ';' after 'break'",
        )

    def test_continue_requires_semicolon(self):
        self.assertCompileError(
            "fn main(): int { while (true) { continue } return 0; }",
            "Expected ';' after 'continue'",
        )

    def test_keywords_are_not_identifiers(self):
        self.assertCompileError(
            "fn main(): int { let for: int = 1; return 0; }", "Expected variable name"
        )


if __name__ == "__main__":
    unittest.main()
