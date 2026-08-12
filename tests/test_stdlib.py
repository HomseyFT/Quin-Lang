"""The standard library, and the panic builtin it relies on.

Every function is exercised at its edges as well as its middle: zero, negative
inputs, the ends of the 16-bit range, and each case that panics. The library is
written in QuinLang, so these tests are the only thing standing between it and
a silent wrong answer.
"""

import unittest

from tests.harness import QuinTestCase


def program(includes, body: str) -> str:
    """A main() with the given std modules included."""
    head = "".join(f'include "std/{name}.ql";\n' for name in includes)
    return f"{head}fn main(): int {{\n{body}\n    return 0;\n}}\n"


def math(body: str) -> str:
    return program(["math"], body)


def bits(body: str) -> str:
    return program(["bits"], body)


def io(body: str) -> str:
    return program(["io"], body)


def lists(body: str) -> str:
    return program(["list"], body)


def vecs(body: str) -> str:
    return program(["vec"], body)


class TestPanic(QuinTestCase):
    def test_panic_stops_the_program_with_its_message(self):
        self.assertRuntimeError(
            'fn main(): int { panic("something went wrong"); return 0; }',
            "something went wrong",
        )

    def test_output_before_a_panic_still_appears(self):
        self.assertRuntimeError(
            'fn main(): int { println(1); panic("stop"); return 0; }', "stop"
        )

    def test_a_panic_that_is_not_reached_does_nothing(self):
        self.assertPrints(
            'fn main(): int { if (false) { panic("no"); } println(1); return 0; }', "1"
        )

    def test_panic_satisfies_return_checking(self):
        # panic never returns, so a function may end with one.
        self.assertPrints(
            'fn f(x: int): int { if (x > 0) { return 1; } panic("bad"); }\n'
            "fn main(): int { println(f(1)); return 0; }",
            "1",
        )

    def test_panic_takes_a_string(self):
        self.assertCompileError(
            "fn main(): int { panic(1); return 0; }", "expected str, got int"
        )

    def test_panic_returns_void(self):
        self.assertCompileError(
            'fn main(): int { let x: int = panic("a"); return 0; }',
            "Type mismatch in initializer",
        )

    def test_panic_cannot_be_redefined(self):
        self.assertCompileError(
            'fn panic(m: str): void { }\nfn main(): int { return 0; }',
            "Redefinition of function 'panic'",
        )


class TestMath(QuinTestCase):
    def test_abs(self):
        self.assertPrints(math("println(abs(5)); println(abs(0 - 5)); println(abs(0));"),
                          "5", "5", "0")

    def test_min_and_max(self):
        self.assertPrints(math("println(min(2, 8)); println(max(2, 8)); "
                               "println(min(0 - 3, 3)); println(max(0 - 3, 0 - 9));"),
                          "2", "8", "-3", "-3")

    def test_clamp(self):
        self.assertPrints(math("println(clamp(99, 0, 10)); println(clamp(0 - 5, 0, 10)); "
                               "println(clamp(5, 0, 10));"),
                          "10", "0", "5")

    def test_clamp_rejects_an_inverted_range(self):
        self.assertRuntimeError(math("println(clamp(1, 10, 0));"),
                                "lo greater than hi")

    def test_sign(self):
        self.assertPrints(math("println(sign(7)); println(sign(0 - 7)); println(sign(0));"),
                          "1", "-1", "0")

    def test_is_even_and_is_odd(self):
        self.assertPrints(math("println(is_even(4)); println(is_even(5)); "
                               "println(is_odd(4)); println(is_odd(5)); "
                               "println(is_even(0)); println(is_even(0 - 4));"),
                          "true", "false", "false", "true", "true", "true")

    def test_pow(self):
        self.assertPrints(math("println(pow(2, 0)); println(pow(2, 10)); "
                               "println(pow(3, 3)); println(pow(0 - 2, 3)); println(pow(0, 0));"),
                          "1", "1024", "27", "-8", "1")

    def test_pow_wraps_at_16_bits(self):
        # 2^15 is the sign bit, and 2^16 falls off the end entirely.
        self.assertPrints(math("println(pow(2, 15)); println(pow(2, 16));"),
                          "-32768", "0")

    def test_pow_rejects_a_negative_exponent(self):
        self.assertRuntimeError(math("println(pow(2, 0 - 1));"), "negative exponent")

    def test_gcd(self):
        self.assertPrints(math("println(gcd(48, 18)); println(gcd(17, 5)); "
                               "println(gcd(0, 5)); println(gcd(5, 0)); println(gcd(0, 0));"),
                          "6", "1", "5", "5", "0")

    def test_gcd_is_non_negative(self):
        self.assertPrints(math("println(gcd(0 - 48, 18)); println(gcd(48, 0 - 18)); "
                               "println(gcd(0 - 48, 0 - 18));"),
                          "6", "6", "6")

    def test_lcm(self):
        self.assertPrints(math("println(lcm(4, 6)); println(lcm(3, 5)); "
                               "println(lcm(0, 5)); println(lcm(7, 7));"),
                          "12", "15", "0", "7")

    def test_isqrt(self):
        self.assertPrints(math("println(isqrt(0)); println(isqrt(1)); println(isqrt(15)); "
                               "println(isqrt(16)); println(isqrt(50)); println(isqrt(10000));"),
                          "0", "1", "3", "4", "7", "100")

    def test_isqrt_at_the_top_of_the_range(self):
        # 181 * 181 is 32761, the largest square that fits in an int.
        self.assertPrints(math("println(isqrt(32767)); println(isqrt(32761));"), "181", "181")

    def test_isqrt_rejects_a_negative(self):
        self.assertRuntimeError(math("println(isqrt(0 - 1));"), "negative number")


class TestBits(QuinTestCase):
    def test_bit_get(self):
        self.assertPrints(bits("println(bit_get(5, 0)); println(bit_get(5, 1)); "
                               "println(bit_get(5, 2)); println(bit_get(0 - 1, 15));"),
                          "true", "false", "true", "true")

    def test_bit_set_clear_toggle(self):
        self.assertPrints(bits("println(bit_set(0, 3)); println(bit_clear(15, 0)); "
                               "println(bit_toggle(5, 1)); println(bit_toggle(7, 1));"),
                          "8", "14", "7", "5")

    def test_bit_index_is_checked(self):
        self.assertRuntimeError(bits("println(bit_get(1, 16));"), "bit index out of range")
        self.assertRuntimeError(bits("println(bit_set(1, 0 - 1));"), "bit index out of range")

    def test_popcount(self):
        self.assertPrints(bits("println(popcount(0)); println(popcount(1)); "
                               "println(popcount(255)); println(popcount(0 - 1)); "
                               "println(popcount(0 - 32768));"),
                          "0", "1", "8", "16", "1")

    def test_reverse_bits(self):
        self.assertPrints(bits("println(reverse_bits(0)); println(reverse_bits(1)); "
                               "println(reverse_bits(0 - 1)); "
                               "println(reverse_bits(reverse_bits(1234)));"),
                          "0", "-32768", "-1", "1234")

    def test_leading_zeros(self):
        self.assertPrints(bits("println(leading_zeros(0)); println(leading_zeros(1)); "
                               "println(leading_zeros(255)); println(leading_zeros(0 - 1));"),
                          "16", "15", "8", "0")

    def test_trailing_zeros(self):
        self.assertPrints(bits("println(trailing_zeros(0)); println(trailing_zeros(1)); "
                               "println(trailing_zeros(8)); println(trailing_zeros(0 - 32768));"),
                          "16", "0", "3", "15")

    def test_highest_bit(self):
        self.assertPrints(bits("println(highest_bit(0)); println(highest_bit(1)); "
                               "println(highest_bit(255)); println(highest_bit(0 - 1));"),
                          "-1", "0", "7", "15")

    def test_rotate_left(self):
        self.assertPrints(bits("println(rotate_left(1, 0)); println(rotate_left(1, 1)); "
                               "println(rotate_left(0 - 32768, 1)); println(rotate_left(1, 16));"),
                          "1", "2", "1", "1")

    def test_rotate_right(self):
        self.assertPrints(bits("println(rotate_right(2, 1)); println(rotate_right(1, 1)); "
                               "println(rotate_right(1, 0));"),
                          "1", "-32768", "1")

    def test_rotation_round_trips(self):
        self.assertPrints(bits("println(rotate_right(rotate_left(1234, 5), 5)); "
                               "println(rotate_left(rotate_right(0 - 999, 7), 7));"),
                          "1234", "-999")

    def test_logical_shift_right_does_not_sign_extend(self):
        # The arithmetic >> would give -1 here; the logical one gives 255.
        self.assertPrints(bits("println(logical_shift_right(0 - 1, 8)); "
                               "println(logical_shift_right(0 - 1, 15)); "
                               "println(logical_shift_right(256, 8)); "
                               "println(logical_shift_right(5, 0));"),
                          "255", "1", "1", "5")

    def test_logical_shift_right_checks_its_count(self):
        self.assertRuntimeError(bits("println(logical_shift_right(1, 16));"),
                                "shift count out of range")


class TestIo(QuinTestCase):
    def test_newline(self):
        self.assertPrints(io('print("a"); newline(); print("b");'), "a", "b")

    def test_print_repeat(self):
        self.assertPrints(io('print_repeat("ab", 3); newline();'), "ababab")

    def test_print_repeat_zero_times(self):
        self.assertPrints(io('print("["); print_repeat("x", 0); println("]");'), "[]")

    def test_print_spaces(self):
        self.assertPrints(io('print("["); print_spaces(3); println("]");'), "[   ]")

    def test_hex_digit(self):
        self.assertPrints(io('print(hex_digit(0)); print(hex_digit(9)); '
                             'print(hex_digit(10)); println(hex_digit(15));'),
                          "09af")

    def test_hex_digit_checks_its_range(self):
        self.assertRuntimeError(io("println(hex_digit(16));"), "0..15")

    def test_print_hex(self):
        self.assertPrints(io("println_hex(0); println_hex(255); "
                             "println_hex(48879); println_hex(0 - 1);"),
                          "0000", "00ff", "beef", "ffff")

    def test_print_binary(self):
        self.assertPrints(io("println_binary(0); println_binary(5); println_binary(0 - 1);"),
                          "0000000000000000", "0000000000000101", "1111111111111111")

    def test_print_padded(self):
        self.assertPrints(io('print("["); print_padded(42, 6); println("]"); '
                             'print("["); print_padded(0, 3); println("]"); '
                             'print("["); print_padded(0 - 42, 6); println("]");'),
                          "[    42]", "[  0]", "[   -42]")

    def test_print_padded_when_the_value_does_not_fit(self):
        self.assertPrints(io('print("["); print_padded(12345, 2); println("]");'), "[12345]")


class TestList(QuinTestCase):
    def test_push_and_read_back(self):
        self.assertPrints(lists(
            "let l: IntList = list_empty();\n"
            "l = list_push(l, 3); l = list_push(l, 2); l = list_push(l, 1);\n"
            "println(list_len(l)); println(list_head(l)); println(list_last(l));"),
            "3", "1", "3")

    def test_empty_list(self):
        self.assertPrints(lists(
            "let l: IntList = list_empty();\n"
            "println(list_is_empty(l)); println(list_len(l)); println(list_sum(l)); "
            "println(list_contains(l, 1));"),
            "true", "0", "0", "false")

    def test_get(self):
        self.assertPrints(lists(
            "let l: IntList = list_push(list_push(list_push(null, 3), 2), 1);\n"
            "println(list_get(l, 0)); println(list_get(l, 1)); println(list_get(l, 2));"),
            "1", "2", "3")

    def test_sum_and_extremes(self):
        self.assertPrints(lists(
            "let l: IntList = list_push(list_push(list_push(null, 5), 0 - 2), 9);\n"
            "println(list_sum(l)); println(list_max(l)); println(list_min(l));"),
            "12", "9", "-2")

    def test_contains_and_index_of(self):
        self.assertPrints(lists(
            "let l: IntList = list_push(list_push(null, 7), 4);\n"
            "println(list_contains(l, 7)); println(list_contains(l, 8)); "
            "println(list_index_of(l, 7)); println(list_index_of(l, 8));"),
            "true", "false", "1", "-1")

    def test_reverse_leaves_the_original_alone(self):
        self.assertPrints(lists(
            "let l: IntList = list_push(list_push(list_push(null, 3), 2), 1);\n"
            "let r: IntList = list_reverse(l);\n"
            "list_println(l); list_println(r);"),
            "[1, 2, 3]", "[3, 2, 1]")

    def test_tail_shares_the_rest_of_the_list(self):
        self.assertPrints(lists(
            "let l: IntList = list_push(list_push(null, 2), 1);\n"
            "println(list_head(list_tail(l))); println(list_len(list_tail(l)));"),
            "2", "1")

    def test_printing(self):
        self.assertPrints(lists(
            "list_println(list_empty());\n"
            "list_println(list_push(null, 9));\n"
            "list_println(list_push(list_push(null, 2), 1));"),
            "[]", "[9]", "[1, 2]")

    def test_a_long_list_survives_collection(self):
        self.assertPrints(lists(
            "let l: IntList = list_empty();\n"
            "for (let i = 0; i < 100; i = i + 1) { l = list_push(l, i); }\n"
            "gc();\n"
            "println(list_len(l)); println(list_sum(l)); println(list_head(l));"),
            "100", "4950", "99")

    def test_empty_list_accessors_panic(self):
        self.assertRuntimeError(lists("println(list_head(list_empty()));"), "empty list")
        self.assertRuntimeError(lists("println(list_last(list_empty()));"), "empty list")
        self.assertRuntimeError(lists("println(list_max(list_empty()));"), "empty list")
        self.assertRuntimeError(lists("println(list_min(list_empty()));"), "empty list")
        self.assertRuntimeError(lists("let l: IntList = list_tail(list_empty());"),
                                "empty list")

    def test_get_out_of_range_panics(self):
        self.assertRuntimeError(lists("println(list_get(list_push(null, 1), 5));"),
                                "past the end")
        self.assertRuntimeError(lists("println(list_get(list_push(null, 1), 0 - 1));"),
                                "negative index")


class TestVec(QuinTestCase):
    def test_push_and_read_back(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "vec_push(v, 10); vec_push(v, 20); vec_push(v, 30);\n"
            "println(vec_len(v)); println(vec_get(v, 0)); println(vec_get(v, 2));"),
            "3", "10", "30")

    def test_a_new_vector_is_empty(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(2);\n"
            "println(vec_len(v)); println(vec_is_empty(v)); println(vec_capacity(v));"),
            "0", "true", "2")

    def test_set(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(2);\n"
            "vec_push(v, 1); vec_set(v, 0, 99); println(vec_get(v, 0));"),
            "99")

    def test_growth_preserves_the_contents(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(1);\n"
            "for (let i = 0; i < 10; i = i + 1) { vec_push(v, i * 3); }\n"
            "println(vec_len(v)); println(vec_get(v, 0)); println(vec_get(v, 9)); "
            "println(vec_sum(v)); println(vec_capacity(v));"),
            "10", "0", "27", "135", "16")

    def test_pop(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "vec_push(v, 1); vec_push(v, 2);\n"
            "println(vec_pop(v)); println(vec_len(v)); println(vec_last(v));"),
            "2", "1", "1")

    def test_clear_keeps_the_capacity(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "vec_push(v, 1); vec_push(v, 2); vec_clear(v);\n"
            "println(vec_len(v)); println(vec_capacity(v)); println(vec_is_empty(v));"),
            "0", "4", "true")

    def test_contains_and_index_of(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "vec_push(v, 5); vec_push(v, 6);\n"
            "println(vec_contains(v, 6)); println(vec_contains(v, 7)); "
            "println(vec_index_of(v, 6)); println(vec_index_of(v, 7));"),
            "true", "false", "1", "-1")

    def test_reverse(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "for (let i = 1; i < 5; i = i + 1) { vec_push(v, i); }\n"
            "vec_reverse(v); vec_println(v);"),
            "[4, 3, 2, 1]")

    def test_reverse_of_an_odd_length(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(4);\n"
            "vec_push(v, 1); vec_push(v, 2); vec_push(v, 3);\n"
            "vec_reverse(v); vec_println(v);"),
            "[3, 2, 1]")

    def test_a_vector_is_a_reference(self):
        # The callee's pushes are visible to the caller, and so is the
        # reallocation they force: the caller never re-reads v.data itself.
        self.assertPrints(
            'include "std/vec.ql";\n'
            """
            fn fill(target: IntVec): void {
                for (let i = 0; i < 5; i = i + 1) { vec_push(target, i); }
            }
            fn main(): int {
                let v: IntVec = vec_new(1);
                fill(v);
                println(vec_len(v));
                println(vec_get(v, 4));
                return 0;
            }
            """,
            "5", "4")

    def test_printing(self):
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(2);\n"
            "vec_println(v);\n"
            "vec_push(v, 7); vec_println(v);\n"
            "vec_push(v, 8); vec_println(v);"),
            "[]", "[7]", "[7, 8]")

    def test_the_block_survives_a_collection_that_moves_it(self):
        # data is a heapptr field, so the collector traces and rewrites it.
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(8);\n"
            "for (let i = 0; i < 8; i = i + 1) { vec_push(v, i); }\n"
            "for (let i = 0; i < 500; i = i + 1) { let junk: IntVec = vec_new(4); }\n"
            "gc();\n"
            "println(vec_len(v)); println(vec_sum(v)); println(vec_get(v, 7));"),
            "8", "28", "7")

    def test_growth_during_collection_pressure(self):
        # Every vec_grow allocates, and one of those allocations collects.
        self.assertPrints(vecs(
            "let v: IntVec = vec_new(1);\n"
            "for (let i = 0; i < 400; i = i + 1) {\n"
            "    let junk: IntVec = vec_new(8);\n"
            "    vec_push(v, i);\n"
            "}\n"
            "println(vec_len(v)); println(vec_get(v, 0)); println(vec_get(v, 399));"),
            "400", "0", "399")

    def test_out_of_range_access_panics(self):
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(4); println(vec_get(v, 0));"),
                                "vec_get index out of range")
        self.assertRuntimeError(
            vecs("let v: IntVec = vec_new(4); vec_push(v, 1); println(vec_get(v, 1));"),
            "vec_get index out of range")
        self.assertRuntimeError(
            vecs("let v: IntVec = vec_new(4); vec_set(v, 0, 1);"),
            "vec_set index out of range")

    def test_popping_an_empty_vector_panics(self):
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(2); println(vec_pop(v));"),
                                "empty vector")
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(2); println(vec_last(v));"),
                                "empty vector")

    def test_a_bad_capacity_panics(self):
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(0);"), "capacity of at least 1")
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(0 - 1);"), "capacity of at least 1")
        self.assertRuntimeError(vecs("let v: IntVec = vec_new(20000);"), "too large")


class TestPrelude(QuinTestCase):
    def test_one_include_brings_in_the_pure_modules(self):
        self.assertPrints(program(["prelude"],
                                  "println(max(3, 9)); println(popcount(7)); "
                                  "println_hex(255);"),
                          "9", "3", "00ff")

    def test_the_prelude_can_be_combined_with_the_collections(self):
        self.assertPrints(program(["prelude", "list", "vec"],
                                  "println(gcd(12, 18)); "
                                  "println(list_len(list_push(null, 1))); "
                                  "println(vec_capacity(vec_new(3)));"),
                          "6", "1", "3")

    def test_including_a_module_twice_is_harmless(self):
        # math arrives directly and again through the prelude; the resolver
        # collapses the repeat rather than reporting a redefinition.
        self.assertPrints(program(["math", "prelude"], "println(abs(0 - 3));"), "3")


if __name__ == "__main__":
    unittest.main()
