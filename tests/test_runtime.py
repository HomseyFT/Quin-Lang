"""VM execution semantics: 16-bit arithmetic, control flow, and faults."""

import unittest

from tests.harness import QuinTestCase, compile_source, run_source


class TestArithmetic(QuinTestCase):
    def test_basic_operators(self):
        self.assertExprPrints("2 + 3", "5")
        self.assertExprPrints("10 - 4", "6")
        self.assertExprPrints("6 * 7", "42")
        self.assertExprPrints("84 / 2", "42")
        self.assertExprPrints("7 % 4", "3")

    def test_division_truncates_toward_zero(self):
        self.assertExprPrints("7 / 2", "3")
        self.assertExprPrints("(0 - 7) / 2", "-3")
        self.assertExprPrints("7 / (0 - 2)", "-3")

    def test_modulo_takes_the_sign_of_the_dividend(self):
        self.assertExprPrints("7 % 2", "1")
        self.assertExprPrints("(0 - 7) % 2", "-1")
        self.assertExprPrints("7 % (0 - 2)", "1")

    def test_addition_wraps_at_16_bits(self):
        self.assertPrints(
            "fn main(): int { let x: int = 32767; x = x + 1; println(x); return 0; }",
            "-32768",
        )

    def test_multiplication_wraps(self):
        self.assertPrints(
            "fn main(): int { let x: int = 256; println(x * 256); return 0; }", "0"
        )

    def test_large_literals_are_signed(self):
        self.assertExprPrints("65535", "-1")
        self.assertExprPrints("0xFFFF", "-1")
        self.assertExprPrints("0x8000", "-32768")

    def test_negation(self):
        self.assertPrints(
            "fn main(): int { let x: int = 5; println(0 - x); return 0; }", "-5"
        )

    def test_division_by_zero(self):
        self.assertRuntimeError(
            "fn main(): int { let z: int; println(1 / z); return 0; }", "Division by zero"
        )

    def test_modulo_by_zero(self):
        self.assertRuntimeError(
            "fn main(): int { let z: int; println(1 % z); return 0; }", "Modulo by zero"
        )


class TestComparisons(QuinTestCase):
    def test_signed_ordering(self):
        # Comparing raw words would make -1 (0xFFFF) the largest int.
        self.assertPrints(
            "fn main(): int { let n: int = 0 - 1; if (n < 1) { println(1); } else { println(0); } return 0; }",
            "1",
        )

    def test_equality_and_inequality(self):
        self.assertExprPrints("1 == 1", "true")
        self.assertExprPrints("1 != 1", "false")

    def test_all_relational_operators(self):
        self.assertExprPrints("1 < 2", "true")
        self.assertExprPrints("2 <= 2", "true")
        self.assertExprPrints("3 > 2", "true")
        self.assertExprPrints("2 >= 3", "false")

    def test_bool_equality(self):
        self.assertExprPrints("true == true", "true")
        self.assertExprPrints("true != false", "true")

    def test_string_equality_uses_interning(self):
        # Equal literals intern to the same id, so == is meaningful.
        self.assertExprPrints('"abc" == "abc"', "true")
        self.assertExprPrints('"abc" == "xyz"', "false")


class TestControlFlow(QuinTestCase):
    def test_if_else(self):
        self.assertPrints(
            "fn main(): int { if (1 > 2) { println(1); } else { println(2); } return 0; }",
            "2",
        )

    def test_if_without_else_skips(self):
        self.assertPrints(
            "fn main(): int { if (false) { println(1); } println(2); return 0; }", "2"
        )

    def test_while_counts(self):
        self.assertPrints(
            """
            fn main(): int {
                let i: int;
                while (i < 3) { println(i); i = i + 1; }
                return 0;
            }
            """,
            "0", "1", "2",
        )

    def test_while_body_may_not_run(self):
        self.assertPrints(
            "fn main(): int { while (false) { println(1); } println(2); return 0; }", "2"
        )

    def test_nested_loops(self):
        self.assertPrints(
            """
            fn main(): int {
                let i: int;
                while (i < 2) {
                    let j: int;
                    while (j < 2) { println(i * 10 + j); j = j + 1; }
                    i = i + 1;
                }
                return 0;
            }
            """,
            "0", "1", "10", "11",
        )

    def test_early_return_from_a_loop(self):
        self.assertPrints(
            """
            fn f(): int {
                let i: int;
                while (true) { if (i == 3) { return i; } i = i + 1; }
                return 0;
            }
            fn main(): int { println(f()); return 0; }
            """,
            "3",
        )


class TestCallingConvention(QuinTestCase):
    def test_void_call_result_is_discarded(self):
        self.assertPrints(
            "fn f(): void { println(1); } fn main(): int { f(); f(); println(2); return 0; }",
            "1", "1", "2",
        )

    def test_nested_calls(self):
        self.assertPrints(
            """
            fn inc(n: int): int { return n + 1; }
            fn main(): int { println(inc(inc(inc(0)))); return 0; }
            """,
            "3",
        )

    def test_arguments_evaluated_left_to_right(self):
        self.assertPrints(
            """
            fn note(n: int): int { println(n); return n; }
            fn add(a: int, b: int): int { return a + b; }
            fn main(): int { println(add(note(1), note(2))); return 0; }
            """,
            "1", "2", "3",
        )

    def test_deep_recursion(self):
        self.assertPrints(
            """
            fn sum(n: int): int {
                if (n <= 0) { return 0; }
                return n + sum(n - 1);
            }
            fn main(): int { println(sum(100)); return 0; }
            """,
            "5050",
        )

    def test_frame_locals_are_per_call(self):
        self.assertPrints(
            """
            fn f(n: int): int {
                let local: int;
                local = n * 2;
                if (n > 0) { f(n - 1); }
                return local;
            }
            fn main(): int { println(f(3)); return 0; }
            """,
            "6",
        )

    def test_recursion_restores_the_callers_locals(self):
        self.assertPrints(
            """
            fn count(n: int): int {
                if (n <= 0) { return 0; }
                let mine: int = n;
                count(n - 1);
                return mine;
            }
            fn main(): int { println(count(5)); return 0; }
            """,
            "5",
        )


class TestArrayBounds(QuinTestCase):
    """Indexing is checked against the array's own length, not the frame's size.

    Before BOUNDS_CHECK existed, an index was validated only against the number
    of locals in the frame, so running off the end of an int[N] quietly landed
    on whatever variable was declared next.
    """

    def test_constant_overrun_is_a_compile_error(self):
        self.assertCompileError(
            """
            fn main(): int {
                let a: int[2];
                let neighbor: int = 77;
                println(a[2]);
                return 0;
            }
            """,
            "out of bounds for length 2",
        )

    def test_dynamic_overrun_faults_at_runtime(self):
        self.assertRuntimeError(
            """
            fn main(): int {
                let a: int[2];
                let neighbor: int = 77;
                let i: int = 2;
                println(a[i]);
                return 0;
            }
            """,
            "Array index out of bounds",
        )

    def test_overrun_cannot_clobber_a_neighbor(self):
        # The regression this check exists for: a[2] on an int[2] used to write
        # straight into 'neighbor' and report success.
        self.assertRuntimeError(
            """
            fn main(): int {
                let a: int[2];
                let neighbor: int = 77;
                let i: int = 2;
                a[i] = 9999;
                return 0;
            }
            """,
            "Array index out of bounds",
        )

    def test_leaving_the_frame_is_a_compile_error(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; println(a[50]); return 0; }",
            "out of bounds for length 2",
        )

    def test_negative_index_faults(self):
        self.assertRuntimeError(
            "fn main(): int { let a: int[2]; println(a[0 - 50]); return 0; }",
            "Array index out of bounds",
        )

    def test_taking_an_out_of_range_address_faults(self):
        # Address-of still validates at runtime; the static check reaches it in
        # the follow-up that de-duplicates index validation.
        self.assertRuntimeError(
            "fn main(): int { let a: int[2]; let p: ptr; p = @a[2]; return 0; }",
            "Array index out of bounds",
        )

    def test_dynamic_out_of_range_address_faults_at_runtime(self):
        self.assertRuntimeError(
            "fn main(): int { let a: int[2]; let p: ptr; let i: int = 2; p = @a[i]; return 0; }",
            "Array index out of bounds",
        )

    def test_valid_indices_are_unaffected(self):
        self.assertPrints(
            "fn main(): int { let a: int[3]; a[0]=5; a[2]=7; println(a[0]); println(a[2]); return 0; }",
            "5", "7",
        )


class TestStrings(QuinTestCase):
    def test_printed_verbatim(self):
        self.assertOutput('fn main(): int { print("a$b"); return 0; }', "a$b")

    def test_interning_reuses_ids(self):
        _, _, strings = compile_source(
            'fn main(): int { print("dup"); print("dup"); print("other"); return 0; }'
        )
        self.assertEqual(sorted(strings.values()), ["dup", "other"])

    def test_empty_string(self):
        self.assertOutput('fn main(): int { print(""); print("x"); return 0; }', "x")


class TestExitValue(QuinTestCase):
    def test_returned_value(self):
        self.assertEqual(run_source("fn main(): int { return 7; }").exit_value, 7)

    def test_void_main_yields_zero(self):
        self.assertEqual(run_source("fn main(): void { }").exit_value, 0)


if __name__ == "__main__":
    unittest.main()
