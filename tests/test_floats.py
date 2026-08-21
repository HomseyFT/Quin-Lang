"""The float type: 32 bits, two slots, one operand-stack entry.

float is the only type wider than a word, so most of what is worth testing here
is the seam between those two facts. The storage width shows up in frame
layout, struct layout, and the calling convention; the single stack entry is
what lets POP, DUP, SWAP and the RET balance check stay unchanged. A bug in
either usually reads back as a value truncated to its low 16 bits, which is why
several tests below assert on a specific number rather than just on success.
"""

import unittest

from compiler.compiler_types import Float, Int, word_count
from runtime.vm import VMError, bits_to_float, float_to_bits, format_float
from tests.harness import QuinTestCase, compile_source


class TestFloatLiterals(QuinTestCase):
    def test_a_literal_round_trips(self):
        self.assertPrints("fn main(): int { println(1.5); return 0; }", "1.5")

    def test_a_whole_float_keeps_its_point(self):
        # Otherwise 3.0 would print as 3 and read as an int.
        self.assertPrints("fn main(): int { println(3.0); return 0; }", "3.0")

    def test_zero(self):
        self.assertPrints("fn main(): int { println(0.0); return 0; }", "0.0")

    def test_a_literal_needs_digits_after_the_point(self):
        self.assertCompileError(
            "fn main(): int { println(1.); return 0; }",
            "Float literal needs at least one digit after '.'",
        )

    def test_there_is_no_exponent_notation(self):
        # `1e5` would otherwise lex as `1` followed by the identifier `e5`,
        # which parses as two things and means neither.
        self.assertCompileError(
            "fn main(): int { println(1e5); return 0; }",
            "Unexpected character 'e' after numeric literal",
        )

    def test_a_literal_too_large_for_a_float_is_rejected(self):
        self.assertCompileError(
            "fn main(): int { println(999999999999999999999999999999999999999999.0); return 0; }",
            "does not fit in a 32-bit float",
        )

    def test_an_int_literal_is_still_an_int(self):
        self.assertPrints("fn main(): int { println(3); return 0; }", "3")


class TestFloatArithmetic(QuinTestCase):
    def test_the_four_operators(self):
        self.assertPrints(
            """
            fn main(): int {
                println(1.5 + 0.25);
                println(1.5 - 0.25);
                println(1.5 * 0.25);
                println(1.5 / 0.25);
                return 0;
            }
            """,
            "1.75", "1.25", "0.375", "6.0",
        )

    def test_negation(self):
        self.assertPrints("fn main(): int { println(-1.5); return 0; }", "-1.5")

    def test_division_by_zero_faults(self):
        # Integer division already does. Returning inf instead would make every
        # later comparison quietly wrong.
        self.assertRuntimeError(
            "fn main(): int { let z: float; println(1.0 / z); return 0; }",
            "Float division by zero",
        )

    def test_overflow_faults_rather_than_becoming_infinity(self):
        self.assertRuntimeError(
            """
            fn main(): int {
                let big: float = 300000000000000000000.0;
                println(big * big);
                return 0;
            }
            """,
            "Float overflow",
        )

    def test_arithmetic_is_single_precision(self):
        # The point of the type: not a double. If this printed 0.3 exactly, or
        # printed double-precision digits, the representation would be wrong.
        self.assertPrints("fn main(): int { println(0.1 + 0.2); return 0; }", "0.3")
        self.assertPrints("fn main(): int { println(1.0 / 3.0); return 0; }", "0.33333334")


class TestFloatComparison(QuinTestCase):
    def test_all_six_operators(self):
        self.assertPrints(
            """
            fn main(): int {
                println(1.5 == 1.5); println(1.5 != 1.5);
                println(1.5 < 2.5);  println(1.5 <= 1.5);
                println(2.5 > 1.5);  println(1.5 >= 2.5);
                return 0;
            }
            """,
            "true", "false", "true", "true", "true", "false",
        )

    def test_negative_values_order_correctly(self):
        # The int comparison opcodes sign-extend a 16-bit word. FCMP reduces
        # the pair first, so the float's sign never reaches that path.
        self.assertPrints(
            "fn main(): int { println((0.0 - 2.0) < (0.0 - 1.0)); return 0; }",
            "true",
        )


class TestIntAndFloatDoNotMix(QuinTestCase):
    def test_arithmetic_between_them_is_rejected(self):
        self.assertCompileError(
            "fn main(): int { let x: float = 1.5; println(x + 1); return 0; }",
            "Cannot mix int and float",
        )

    def test_an_int_does_not_initialise_a_float(self):
        self.assertCompileError(
            "fn main(): int { let x: float = 1; return 0; }", "Type mismatch"
        )

    def test_a_float_does_not_initialise_an_int(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 1.5; return 0; }", "Type mismatch"
        )

    def test_comparison_between_them_is_rejected(self):
        self.assertCompileError(
            "fn main(): int { println(1.5 == 1); return 0; }",
            "Comparison requires operands of same type",
        )

    def test_modulo_and_bitwise_operators_reject_float(self):
        for op in ("%", "^", "&", "|", "<<", ">>"):
            with self.subTest(op=op):
                self.assertCompileError(
                    f"fn main(): int {{ println(1.5 {op} 2.0); return 0; }}",
                    "does not apply to float",
                )

    def test_conversion_makes_the_choice_explicit(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: float = 1.5;
                println(x + int_to_float(1));
                println(float_to_int(x) + 1);
                return 0;
            }
            """,
            "2.5", "2",
        )

    def test_float_to_int_truncates_toward_zero(self):
        # Matching integer division, which truncates rather than flooring.
        self.assertPrints(
            """
            fn main(): int {
                println(float_to_int(3.75));
                println(float_to_int(0.0 - 3.75));
                return 0;
            }
            """,
            "3", "-3",
        )

    def test_float_to_int_outside_the_int_range_faults(self):
        self.assertRuntimeError(
            "fn main(): int { println(float_to_int(99999.0)); return 0; }",
            "does not fit in a 16-bit int",
        )


class TestFloatStorage(QuinTestCase):
    """The two-slot half of the design."""

    def test_a_float_local_reserves_two_slots(self):
        code, functions, _, _ = compile_source(
            "fn main(): int { let a: float; let b: float; let i: int; return 0; }"
        )
        main = next(f for f in functions if f.name == "main")
        self.assertEqual(main.num_locals, 5)

    def test_an_uninitialised_float_is_zero(self):
        self.assertPrints(
            "fn main(): int { let x: float; println(x); return 0; }", "0.0"
        )

    def test_a_neighbouring_local_is_not_clobbered(self):
        # The failure this guards: a float storing only its low word, or
        # writing its high word over the next variable.
        self.assertPrints(
            """
            fn main(): int {
                let before: int = 11;
                let x: float = 1.5;
                let after: int = 22;
                println(before); println(x); println(after);
                return 0;
            }
            """,
            "11", "1.5", "22",
        )

    def test_assignment_replaces_both_words(self):
        # 1.5 is 0x3FC00000: its low word is zero. A store that wrote only the
        # low word would leave the old high word and read back as the old value.
        self.assertPrints(
            """
            fn main(): int {
                let x: float = 1.5;
                x = 2.5;
                println(x);
                x = 0.375;
                println(x);
                return 0;
            }
            """,
            "2.5", "0.375",
        )

    def test_word_count_is_two_for_float_and_one_otherwise(self):
        self.assertEqual(word_count(Float), 2)
        self.assertEqual(word_count(Int), 1)


class TestFloatCallingConvention(QuinTestCase):
    """A float is one operand-stack entry and two slots, so CALL cannot assume
    argument i lands in local i."""

    def test_a_float_parameter_and_return(self):
        self.assertPrints(
            """
            fn scale(v: float, k: float): float { return v * k; }
            fn main(): int { println(scale(1.5, 4.0)); return 0; }
            """,
            "6.0",
        )

    def test_a_float_return_is_not_truncated(self):
        # RET re-pushes the value into the caller's frame. Doing that through
        # the 16-bit masking push would keep only the low half.
        self.assertPrints(
            """
            fn one_and_a_half(): float { return 1.5; }
            fn main(): int { println(one_and_a_half()); return 0; }
            """,
            "1.5",
        )

    def test_an_int_after_a_float_parameter_still_arrives(self):
        # The scatter has to advance two slots for the float, or `n` reads the
        # float's high word.
        self.assertPrints(
            """
            fn f(x: float, n: int): int { println(x); return n; }
            fn main(): int { println(f(2.5, 7)); return 0; }
            """,
            "2.5", "7",
        )

    def test_a_float_after_an_int_parameter(self):
        self.assertPrints(
            """
            fn f(n: int, x: float): float { println(n); return x; }
            fn main(): int { println(f(7, 2.5)); return 0; }
            """,
            "7", "2.5",
        )

    def test_several_float_parameters(self):
        self.assertPrints(
            """
            fn sum3(a: float, b: float, c: float): float { return a + b + c; }
            fn main(): int { println(sum3(0.5, 1.5, 2.5)); return 0; }
            """,
            "4.5",
        )

    def test_recursion_with_a_float_accumulator(self):
        self.assertPrints(
            """
            fn go(n: int, acc: float): float {
                if (n == 0) { return acc; }
                return go(n - 1, acc + 0.5);
            }
            fn main(): int { println(go(6, 0.0)); return 0; }
            """,
            "3.0",
        )

    def test_a_float_expression_statement_is_discarded_cleanly(self):
        # One entry per value is what keeps ExprStmt's single POP correct.
        self.assertPrints(
            """
            fn f(): float { println(1); return 1.5; }
            fn main(): int { f(); println(2); return 0; }
            """,
            "1", "2",
        )


class TestFloatStructFields(QuinTestCase):
    def test_a_float_field_round_trips(self):
        self.assertPrints(
            """
            struct P { x: float, y: float }
            fn main(): int {
                let p: P = P { x: 1.25, y: 2.5 };
                println(p.x); println(p.y);
                return 0;
            }
            """,
            "1.25", "2.5",
        )

    def test_a_float_field_can_be_assigned(self):
        self.assertPrints(
            """
            struct P { x: float }
            fn main(): int {
                let p: P = P { x: 1.25 };
                p.x = 8.5;
                println(p.x);
                return 0;
            }
            """,
            "8.5",
        )

    def test_a_float_field_does_not_overlap_the_next_field(self):
        # Field offsets are word offsets, so a float field has to advance the
        # running total by two or the next field shares its high word.
        self.assertPrints(
            """
            struct P { x: float, tag: int, y: float }
            fn main(): int {
                let p: P = P { x: 1.25, tag: 9, y: 2.5 };
                println(p.x); println(p.tag); println(p.y);
                return 0;
            }
            """,
            "1.25", "9", "2.5",
        )

    def test_the_object_is_sized_in_words(self):
        _, _, _, structs = compile_source(
            "struct P { x: float, tag: int } "
            "fn main(): int { let p: P = P { x: 1.0, tag: 1 }; return 0; }"
        )
        layout = next(s for s in structs if s.name == "P")
        self.assertEqual(layout.word_size, 3)

    def test_a_float_field_is_not_traced_as_a_reference(self):
        # A float's bit pattern can look like any address. The collector must
        # decide by the struct layout, never by inspecting the value.
        _, _, _, structs = compile_source(
            "struct P { x: float, s: str } "
            'fn main(): int { let p: P = P { x: 1.0, s: "hi" }; return 0; }'
        )
        layout = next(s for s in structs if s.name == "P")
        self.assertEqual(layout.ref_offsets, (2,))

    def test_float_fields_survive_a_collection(self):
        self.assertPrints(
            """
            struct Box { v: float, next: Box }
            fn main(): int {
                let head: Box = null;
                let i: int = 0;
                while (i < 200) {
                    head = Box { v: int_to_float(i), next: head };
                    i = i + 1;
                }
                gc();
                println(head.v);
                println(head.next.v);
                return 0;
            }
            """,
            "199.0", "198.0",
        )


class TestFloatIsNotAWordWideValue(QuinTestCase):
    """Places where treating a float as one slot would silently work on half
    of it. Each is refused rather than allowed to do the wrong thing."""

    def test_there_are_no_float_arrays(self):
        self.assertCompileError(
            "fn main(): int { let a: float[3]; return 0; }",
            "Only int arrays exist; 'float[N]' is not a type",
        )

    def test_the_address_of_a_float_is_refused(self):
        self.assertCompileError(
            "fn main(): int { let x: float = 1.5; let p: ptr = @x; return 0; }",
            "a float is two slots wide and a ptr addresses one",
        )

    def test_vm_asm_cannot_reach_a_float_local(self):
        self.assertCompileError(
            "fn main(): int { let x: float = 1.5; vm_asm { load_local x; store_local x; } return 0; }",
            "is a float, which is two slots wide; vm_asm only moves one",
        )

    def test_main_cannot_return_a_float(self):
        self.assertCompileError(
            "fn main(): float { return 1.5; }",
            "must return int or void",
        )


class TestFloatPrinting(QuinTestCase):
    def test_print_does_not_add_a_newline(self):
        self.assertPrints(
            'fn main(): int { print(1.5); print(2.5); println(""); return 0; }',
            "1.52.5",
        )

    def test_float_to_str_produces_the_same_text(self):
        self.assertPrints(
            'fn main(): int { println(float_to_str(1.5) + "!"); return 0; }',
            "1.5!",
        )

    def test_negative_zero_prints_as_zero(self):
        self.assertPrints(
            "fn main(): int { println(0.0 * (0.0 - 1.0)); return 0; }", "-0.0"
        )


class TestFloatEncoding(unittest.TestCase):
    """The bit-level helpers the VM and codegen both rely on."""

    def test_bits_round_trip(self):
        for value in (0.0, 1.0, 1.5, -2.25, 0.375, 1e30, -1e-30):
            with self.subTest(value=value):
                self.assertEqual(bits_to_float(float_to_bits(value)),
                                 bits_to_float(float_to_bits(value)))

    def test_zero_is_all_zero_bits(self):
        # Which is why an uninitialised float local reads as 0.0 for free.
        self.assertEqual(float_to_bits(0.0), 0)

    def test_a_non_finite_value_is_refused(self):
        # struct.pack would accept infinity without complaint, so this is
        # checked separately from the range.
        with self.assertRaises(VMError):
            float_to_bits(float("inf"))
        with self.assertRaises(VMError):
            float_to_bits(1e300 * 1e300)

    def test_format_shows_no_more_digits_than_the_value_carries(self):
        # repr() gives the shortest string that round-trips through a double,
        # which is not the same question: these are float32 values widened to
        # double, so repr would show digits the 32-bit value does not carry.
        third = bits_to_float(float_to_bits(1.0 / 3.0))
        self.assertEqual(repr(third), "0.3333333432674408")
        self.assertEqual(format_float(third), "0.33333334")

    def test_format_always_marks_a_float(self):
        self.assertEqual(format_float(3.0), "3.0")
        self.assertEqual(format_float(-1.0), "-1.0")


class TestFloatStdlib(QuinTestCase):
    SRC = 'include "std/float.ql";\n'

    def test_fabs_fmin_fmax_fsign(self):
        self.assertPrints(
            self.SRC + """
            fn main(): int {
                println(fabs(0.0 - 2.5)); println(fabs(2.5));
                println(fmin(1.5, 2.5)); println(fmax(1.5, 2.5));
                println(fsign(0.0 - 3.0)); println(fsign(3.0)); println(fsign(0.0));
                return 0;
            }
            """,
            "2.5", "2.5", "1.5", "2.5", "-1", "1", "0",
        )

    def test_floor_and_ceil_round_the_right_way_for_negatives(self):
        # float_to_int truncates toward zero, so a naive floor would give -2.0
        # for -2.7.
        self.assertPrints(
            self.SRC + """
            fn main(): int {
                println(floor(2.7)); println(floor(0.0 - 2.7)); println(floor(3.0));
                println(ceil(2.1));  println(ceil(0.0 - 2.1));  println(ceil(3.0));
                return 0;
            }
            """,
            "2.0", "-3.0", "3.0", "3.0", "-2.0", "3.0",
        )

    def test_round_is_half_away_from_zero(self):
        self.assertPrints(
            self.SRC + """
            fn main(): int {
                println(round(0.5)); println(round(0.0 - 0.5));
                println(round(2.4)); println(round(2.6));
                return 0;
            }
            """,
            "1.0", "-1.0", "2.0", "3.0",
        )

    def test_ftrunc_goes_toward_zero(self):
        self.assertPrints(
            self.SRC + """
            fn main(): int {
                println(ftrunc(2.7)); println(ftrunc(0.0 - 2.7));
                return 0;
            }
            """,
            "2.0", "-2.0",
        )

    def test_fpow(self):
        self.assertPrints(
            self.SRC + "fn main(): int { println(fpow(2.0, 10)); println(fpow(3.0, 0)); return 0; }",
            "1024.0", "1.0",
        )

    def test_fpow_rejects_a_negative_exponent(self):
        self.assertRuntimeError(
            self.SRC + "fn main(): int { println(fpow(2.0, 0 - 1)); return 0; }",
            "negative exponent",
        )

    def test_fclose_is_the_right_test_for_computed_values(self):
        # Ten additions of 0.1 land on 1.0000001, not 1.0. (0.1 + 0.2 == 0.3
        # is actually true at single precision -- the rounding happens to
        # agree -- so it makes a poor example.)
        self.assertPrints(
            self.SRC + """
            fn main(): int {
                let acc: float = 0.0;
                let i: int = 0;
                while (i < 10) { acc = acc + 0.1; i = i + 1; }
                println(acc);
                println(acc == 1.0);
                println(fclose(acc, 1.0, 0.001));
                return 0;
            }
            """,
            "1.0000001", "false", "true",
        )

    def test_floor_outside_the_int_range_panics(self):
        self.assertRuntimeError(
            self.SRC + "fn main(): int { println(floor(100000.0)); return 0; }",
            "outside the int range",
        )


if __name__ == "__main__":
    unittest.main()
