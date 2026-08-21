"""Strings as heap objects.

A str value is the address of a string object, so a string is allocated,
traced, moved and reclaimed exactly like a struct. The difference is that it
holds no references, so the collector keeps it without tracing into it.

These tests care about three things: that the operations are right, that the
collector treats strings correctly, and that a str can never be null.
"""

import io
import unittest
from contextlib import redirect_stdout

from runtime.vm import QuinVM, KIND_STRING, HEADER_BYTES
from tests.harness import QuinTestCase, compile_source


def run_and_inspect(source: str):
    code, functions, strings, structs = compile_source(source)
    vm = QuinVM(code, functions, strings, structs)
    buf = io.StringIO()
    with redirect_stdout(buf):
        vm.run_main()
    return vm, buf.getvalue()


class TestEscapes(QuinTestCase):
    def test_newline(self):
        self.assertPrints(r'fn main(): int { println("a\nb"); return 0; }', "a", "b")

    def test_tab_and_quote(self):
        self.assertOutput(r'fn main(): int { print("a\tb"); return 0; }', "a\tb")
        self.assertOutput(r'fn main(): int { print("say \"hi\""); return 0; }', 'say "hi"')

    def test_backslash(self):
        self.assertOutput(r'fn main(): int { print("a\\b"); return 0; }', "a\\b")

    def test_escapes_count_as_one_character(self):
        self.assertPrints(r'fn main(): int { println(str_len("a\nb")); return 0; }', "3")
        self.assertPrints(r'fn main(): int { println(str_len("a\\b")); return 0; }', "3")

    def test_unknown_escape_is_rejected(self):
        self.assertCompileError(r'fn main(): int { print("a\qb"); return 0; }',
                                "Unknown escape sequence")


class TestConcatenation(QuinTestCase):
    def test_two_literals(self):
        self.assertPrints('fn main(): int { println("ab" + "cd"); return 0; }', "abcd")

    def test_chained(self):
        self.assertPrints(
            'fn main(): int { println("a" + "b" + "c" + "d"); return 0; }', "abcd")

    def test_with_a_variable(self):
        self.assertPrints(
            'fn main(): int { let n: str = "world"; println("hello, " + n + "!"); return 0; }',
            "hello, world!")

    def test_with_the_empty_string(self):
        self.assertPrints('fn main(): int { println("" + "a" + ""); return 0; }', "a")

    def test_the_result_is_a_new_string(self):
        # Equal content, but built rather than shared with either operand.
        self.assertPrints(
            'fn main(): int { let a: str = "ab"; let b: str = a + ""; '
            'println(a == b); println(str_len(b)); return 0; }',
            "true", "2")

    def test_concatenation_in_a_loop(self):
        self.assertPrints(
            """
            fn main(): int {
                let out: str = "";
                for (let i = 0; i < 5; i = i + 1) { out = out + "ab"; }
                println(out);
                println(str_len(out));
                return 0;
            }
            """,
            "ababababab", "10")

    def test_plus_still_rejects_mixed_types(self):
        self.assertCompileError('fn main(): int { println("a" + 1); return 0; }',
                                "Arithmetic operators require int or float operands")


class TestLengthAndCharacters(QuinTestCase):
    def test_len(self):
        self.assertPrints('fn main(): int { println(str_len("")); println(str_len("a")); '
                          'println(str_len("hello")); return 0; }',
                          "0", "1", "5")

    def test_char_at(self):
        self.assertPrints('fn main(): int { println(str_char_at("abc", 0)); '
                          'println(str_char_at("abc", 2)); return 0; }',
                          "97", "99")

    def test_char_at_checks_its_range(self):
        self.assertRuntimeError('fn main(): int { println(str_char_at("abc", 3)); return 0; }',
                                "str_char_at index out of range")
        self.assertRuntimeError('fn main(): int { println(str_char_at("abc", 0 - 1)); return 0; }',
                                "str_char_at index out of range")
        self.assertRuntimeError('fn main(): int { println(str_char_at("", 0)); return 0; }',
                                "str_char_at index out of range")

    def test_char_to_str_round_trips(self):
        self.assertPrints('fn main(): int { println(char_to_str(65)); '
                          'println(str_char_at(char_to_str(200), 0)); return 0; }',
                          "A", "200")

    def test_char_to_str_checks_its_range(self):
        self.assertRuntimeError('fn main(): int { println(char_to_str(256)); return 0; }',
                                "0..255")
        self.assertRuntimeError('fn main(): int { println(char_to_str(0 - 1)); return 0; }',
                                "0..255")


class TestSlicing(QuinTestCase):
    def test_slice(self):
        self.assertPrints('fn main(): int { println(str_slice("hello", 1, 3)); '
                          'println(str_slice("hello", 0, 5)); return 0; }',
                          "el", "hello")

    def test_empty_slice(self):
        self.assertPrints('fn main(): int { println(str_len(str_slice("hello", 2, 2))); '
                          'return 0; }', "0")

    def test_slice_checks_its_range(self):
        self.assertRuntimeError('fn main(): int { println(str_slice("abc", 0, 4)); return 0; }',
                                "str_slice range out of bounds")
        self.assertRuntimeError('fn main(): int { println(str_slice("abc", 2, 1)); return 0; }',
                                "str_slice range out of bounds")
        self.assertRuntimeError(
            'fn main(): int { println(str_slice("abc", 0 - 1, 2)); return 0; }',
            "str_slice range out of bounds")

    def test_a_slice_is_independent_of_its_source(self):
        self.assertPrints(
            'fn main(): int { let s: str = "abcdef"; let part: str = str_slice(s, 1, 3); '
            'println(part); println(s); return 0; }',
            "bc", "abcdef")


class TestConversions(QuinTestCase):
    def test_int_to_str(self):
        self.assertPrints('fn main(): int { println(int_to_str(0)); println(int_to_str(42)); '
                          'println(int_to_str(0 - 7)); return 0; }',
                          "0", "42", "-7")

    def test_int_to_str_at_the_extremes(self):
        self.assertPrints('fn main(): int { println(int_to_str(32767)); '
                          'println(int_to_str(0 - 32768)); return 0; }',
                          "32767", "-32768")

    def test_int_to_str_composes(self):
        self.assertPrints(
            'fn main(): int { println("n = " + int_to_str(5)); return 0; }', "n = 5")

    def test_int_to_str_length(self):
        self.assertPrints('fn main(): int { println(str_len(int_to_str(1000))); '
                          'println(str_len(int_to_str(0 - 1))); return 0; }',
                          "4", "2")


class TestComparison(QuinTestCase):
    def test_built_strings_compare_by_content(self):
        self.assertPrints(
            'fn main(): int { println(("ab" + "c") == "abc"); '
            'println(("ab" + "c") != "abc"); return 0; }',
            "true", "false")

    def test_ordering_of_built_strings(self):
        self.assertPrints(
            'fn main(): int { println(("ab" + "c") < "abd"); '
            'println(("ab" + "d") < "abc"); return 0; }',
            "true", "false")

    def test_empty_compares_correctly(self):
        self.assertPrints('fn main(): int { println("" == ""); println("" < "a"); '
                          'println(str_slice("abc", 1, 1) == ""); return 0; }',
                          "true", "true", "true")

    def test_a_string_with_a_nul_is_compared_in_full(self):
        # The length is stored, so a nul is an ordinary character rather than
        # a terminator.
        self.assertPrints(r'fn main(): int { println(str_len("a\0b")); '
                          r'println("a\0b" == "a\0b"); println("a\0b" == "a"); return 0; }',
                          "3", "true", "false")


class TestUninitialisedIsEmpty(QuinTestCase):
    def test_an_uninitialised_str_is_the_empty_string(self):
        self.assertPrints('fn main(): int { let s: str; println(str_len(s)); '
                          'println(s == ""); return 0; }',
                          "0", "true")

    def test_printing_an_uninitialised_str(self):
        self.assertOutput('fn main(): int { let s: str; print("["); print(s); print("]"); '
                          'return 0; }', "[]")

    def test_null_is_not_a_string(self):
        # A str is a heap reference, but it has no null: there is always a
        # string there, so no operation needs a null check.
        self.assertCompileError('fn main(): int { let s: str = null; return 0; }',
                                "Type mismatch in initializer")

    def test_a_string_cannot_be_compared_with_null(self):
        self.assertCompileError('fn main(): int { let s: str; println(s == null); return 0; }',
                                "Comparison requires operands of same type")


class TestAddressOfIsRejected(QuinTestCase):
    def test_a_str_cannot_have_its_address_taken(self):
        # Same reasoning as heapptr and structs: load16 could read the address
        # out as an int and hide it from the collector.
        self.assertCompileError(
            'fn main(): int { let s: str = "a"; let p: ptr = @s; return 0; }',
            "Cannot take the address of 's'")


class TestHeapRepresentation(QuinTestCase):
    def test_a_literal_is_a_string_object_in_the_heap(self):
        vm, _ = run_and_inspect('fn main(): int { let s: str = "hello"; return 0; }')
        addr = vm.locals[0]
        hdr = addr - HEADER_BYTES
        self.assertEqual(vm._kind(hdr), KIND_STRING)
        self.assertEqual(vm._detail(hdr), 5, "the header carries the length")
        self.assertEqual(vm._string_text(addr), "hello")

    def test_an_odd_length_string_still_tiles_the_heap(self):
        # A three-character string occupies a four-byte payload, so the next
        # header stays word-aligned and the block walk keeps working.
        vm, _ = run_and_inspect(
            'fn main(): int { let a: str = "abc"; let b: str = "de"; return 0; }')
        blocks = list(vm._blocks())
        for x, y in zip(blocks, blocks[1:]):
            self.assertEqual(vm._block_end(x), y)
        self.assertEqual(vm._block_end(blocks[-1]), vm.heap_ptr)

    def test_string_slots_are_in_the_stack_map(self):
        _, functions, _, _ = compile_source(
            'fn main(): int { let s: str = "a"; let n: int = 1; return 0; }')
        main = next(f for f in functions if f.name == "main")
        self.assertEqual(main.ref_slots, (0,), "the str is a root, the int is not")

    def test_a_str_field_is_a_traced_reference(self):
        _, _, _, structs = compile_source(
            "struct Person { name: str, age: int }\n"
            'fn main(): int { let p: Person = Person { name: "a", age: 1 }; return 0; }')
        person = next(s for s in structs if s.name == "Person")
        self.assertEqual(person.ref_offsets, (0,), "name is traced, age is not")


class TestCollection(QuinTestCase):
    def test_dropped_strings_are_reclaimed(self):
        vm, out = run_and_inspect(
            """
            fn churn(): void { let tmp: str = int_to_str(1234) + "x"; }
            fn main(): int {
                for (let i = 0; i < 300; i = i + 1) { churn(); }
                gc();
                println(1);
                return 0;
            }
            """)
        self.assertEqual(out.strip(), "1")
        self.assertGreaterEqual(vm.stats.objects_freed, 300)

    def test_a_program_can_outlive_the_heap_building_strings(self):
        # 20000 strings through 64 KiB only works if they are collected.
        vm, out = run_and_inspect(
            """
            fn main(): int {
                for (let i = 0; i < 20000; i = i + 1) { let s: str = int_to_str(i); }
                println(1);
                return 0;
            }
            """)
        self.assertEqual(out.strip(), "1")
        self.assertGreater(vm.stats.collections, 0)

    def test_a_string_survives_being_moved(self):
        vm, out = run_and_inspect(
            """
            fn drop(): void { let junk: str = int_to_str(9999); }
            fn main(): int {
                for (let i = 0; i < 30; i = i + 1) { drop(); }
                let s: str = "abc" + "def";
                gc();
                println(s);
                println(str_len(s));
                return 0;
            }
            """)
        self.assertEqual(out.split(), ["abcdef", "6"])
        self.assertGreater(vm.stats.objects_moved, 0, "the string should have moved")

    def test_a_literal_survives_being_moved(self):
        # Literals are named by the bytecode, not by any variable, so they are
        # permanent roots and compaction has to rewrite their addresses too.
        vm, out = run_and_inspect(
            """
            fn drop(): void { let junk: str = int_to_str(7); }
            fn main(): int {
                for (let i = 0; i < 40; i = i + 1) { drop(); }
                gc();
                println("a literal, still here");
                return 0;
            }
            """)
        self.assertEqual(out.strip(), "a literal, still here")

    def test_literal_addresses_are_rewritten_when_they_move(self):
        # White-box, because a literal cannot move through ordinary execution:
        # literals are materialised first, so they sit at the bottom of the
        # heap, and being permanent roots they never die, so compaction always
        # finds them in place. The rewrite exists so that stops being a silent
        # assumption, and this is what pins it.
        vm, _ = run_and_inspect('fn main(): int { println("abc"); return 0; }')
        original = vm.literals[0]
        forward = {original: original + 64}
        vm._update_references(forward, vm._object_starts())
        self.assertEqual(vm.literals[0], original + 64,
                         "a literal that moved must be followed")

    def test_a_string_in_a_struct_field_survives(self):
        self.assertPrints(
            "struct Person { name: str, age: int }\n"
            """
            fn drop(): void { let junk: str = int_to_str(1111); }
            fn main(): int {
                let p: Person = Person { name: "Ada" + " Lovelace", age: 36 };
                for (let i = 0; i < 50; i = i + 1) { drop(); }
                gc();
                println(p.name);
                println(p.age);
                return 0;
            }
            """,
            "Ada Lovelace", "36")

    def test_a_string_only_on_the_operand_stack_survives(self):
        self.assertPrints(
            """
            fn collect_now(): str { gc(); return "world"; }
            fn main(): int { println("hello " + collect_now()); return 0; }
            """,
            "hello world")

    def test_a_string_is_not_traced_through(self):
        # A string holds characters, not references. Bytes that happen to look
        # like an address must not keep anything alive.
        vm, _ = run_and_inspect(
            'fn main(): int { let s: str = "abcdefgh"; gc(); println(str_len(s)); return 0; }')
        hdr = vm.locals[0] - HEADER_BYTES
        self.assertEqual(vm._kind(hdr), KIND_STRING)

    def test_an_intermediate_result_survives_a_collection(self):
        # "x" + "y" produces a string that is held by nothing but the operand
        # stack while tag() runs. If a concatenation's result were not tagged
        # as a reference, that collection would free it and the second
        # concatenation would read reclaimed memory.
        #
        # The collection is forced with gc() rather than by filling the heap:
        # relying on heap pressure makes it a matter of luck whether any
        # collection lands in the window at all.
        self.assertPrints(
            """
            fn tag(): str { gc(); return "!"; }
            fn main(): int { println("x" + "y" + tag()); return 0; }
            """,
            "xy!")

    def test_every_freshly_built_string_survives_a_collection_in_flight(self):
        # Each of the four opcodes that allocates a string must tag its result
        # as a reference. Here the fresh string is held by nothing but the
        # operand stack while tag() collects, so an untagged one is reclaimed
        # and the concatenation that follows reads dead memory.
        for expression, expected in [
            ('str_slice("abcdef", 1, 3)', "bc!"),
            ("int_to_str(1234)", "1234!"),
            ("char_to_str(65)", "A!"),
            ('"x" + "y"', "xy!"),
        ]:
            with self.subTest(expression=expression):
                self.assertPrints(
                    'fn tag(): str { gc(); return "!"; }\n'
                    f"fn main(): int {{ println({expression} + tag()); return 0; }}",
                    expected)

    def test_a_long_chain_of_concatenations_under_pressure(self):
        source = """
            fn main(): int {
                let out: str = "";
                for (let i = 0; i < 3000; i = i + 1) {
                    out = int_to_str(i) + "-" + int_to_str(i);
                }
                println(out);
                return 0;
            }
            """
        self.assertPrints(source, "2999-2999")
        vm, _ = run_and_inspect(source)
        self.assertGreater(vm.stats.collections, 0,
                           "3000 iterations should exhaust the heap at least once")

    def test_concatenation_under_collection_pressure(self):
        self.assertPrints(
            """
            fn churn(): int {
                for (let i = 0; i < 4000; i = i + 1) { let junk: str = int_to_str(i); }
                return 0;
            }
            fn main(): int {
                let a: str = "left";
                let b: str = "right";
                churn();
                println(a + "-" + b);
                return 0;
            }
            """,
            "left-right")


class TestStringLibrary(QuinTestCase):
    def lib(self, body: str) -> str:
        return f'include "std/string.ql";\nfn main(): int {{\n{body}\n    return 0;\n}}\n'

    def test_predicates(self):
        self.assertPrints(self.lib(
            'println(str_is_empty("")); println(str_is_empty("a")); '
            'println(str_starts_with("hello", "he")); println(str_starts_with("he", "hello")); '
            'println(str_ends_with("hello", "lo")); println(str_contains("hello", "ell"));'),
            "true", "false", "true", "false", "true", "true")

    def test_searching(self):
        self.assertPrints(self.lib(
            'println(str_index_of("hello", "l")); println(str_last_index_of("hello", "l")); '
            'println(str_index_of("hello", "z")); println(str_index_of_char("hello", 101)); '
            'println(str_count_char("hello", 108));'),
            "2", "3", "-1", "1", "2")

    def test_transforms(self):
        self.assertPrints(self.lib(
            'println(str_to_upper("aBc")); println(str_to_lower("AbC")); '
            'println(str_reverse("abc")); println(str_repeat("ab", 3)); '
            'println(str_repeat("ab", 0));'),
            "ABC", "abc", "cba", "ababab", "")

    def test_trimming(self):
        self.assertPrints(self.lib(
            'print("["); print(str_trim("  a  ")); println("]"); '
            'print("["); print(str_trim_start("  a  ")); println("]"); '
            'print("["); print(str_trim_end("  a  ")); println("]"); '
            'print("["); print(str_trim("   ")); println("]");'),
            "[a]", "[a  ]", "[  a]", "[]")

    def test_character_predicates(self):
        self.assertPrints(self.lib(
            'println(is_digit(53)); println(is_digit(65)); println(is_alpha(65)); '
            'println(is_upper(65)); println(is_lower(97)); println(is_space(32)); '
            'println(is_alnum(48)); println(to_upper_char(97)); println(to_lower_char(65));'),
            "true", "false", "true", "true", "true", "true", "true", "65", "97")

    def test_parse_int(self):
        self.assertPrints(self.lib(
            'println(str_parse_int("0")); println(str_parse_int("1234")); '
            'println(str_parse_int("-42")); println(str_parse_int("+7"));'),
            "0", "1234", "-42", "7")

    def test_parse_int_round_trips(self):
        self.assertPrints(self.lib(
            'println(str_parse_int(int_to_str(31337))); '
            'println(str_parse_int(int_to_str(0 - 31337)));'),
            "31337", "-31337")

    def test_parse_int_rejects_rubbish(self):
        self.assertRuntimeError(self.lib('println(str_parse_int(""));'), "empty string")
        self.assertRuntimeError(self.lib('println(str_parse_int("12a"));'), "not a digit")
        self.assertRuntimeError(self.lib('println(str_parse_int("-"));'), "sign with no digits")

    def test_first_and_last(self):
        self.assertPrints(self.lib(
            'println(str_first("abc")); println(str_last("abc"));'), "97", "99")

    def test_first_and_last_reject_an_empty_string(self):
        self.assertRuntimeError(self.lib('println(str_first(""));'), "empty string")
        self.assertRuntimeError(self.lib('println(str_last(""));'), "empty string")

    def test_repeat_rejects_a_negative_count(self):
        self.assertRuntimeError(self.lib('println(str_repeat("a", 0 - 1));'),
                                "negative count")

    def test_the_library_arrives_through_the_prelude(self):
        self.assertPrints(
            'include "std/prelude.ql";\n'
            'fn main(): int { println(str_to_upper("hi")); println(max(1, 2)); return 0; }',
            "HI", "2")


if __name__ == "__main__":
    unittest.main()
