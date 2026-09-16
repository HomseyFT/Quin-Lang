"""Array<T>: the heap array, and what the collector makes of one.

The other array, int[N], lives in a frame and has its length in its type. This
one is an object, so the interesting questions are all about the heap: whether
the collector traces it, whether it survives a move with its elements intact,
and whether a wrong guess anywhere in the compiler could make the collector read
it incorrectly. It cannot -- the tracing decision lives in the object's header,
and these tests are mostly about proving that.
"""

import io
import unittest
from contextlib import redirect_stdout

from compiler.bytecode import OpCode
from compiler.compiler_types import (
    Float, Int, Str, array_obj_type, element_type_from_name, is_array_obj_type,
    is_reference_type, type_from_name, word_count, UnknownTypeError,
)
from compiler.parser import Parser
from compiler.lexer import Lexer
from runtime.vm import (
    HEADER_BYTES, KIND_REFARRAY, KIND_VALARRAY, QuinVM,
)
from tests.harness import QuinTestCase, compile_source, main_wrapping, vm_for


def run_and_inspect(source: str):
    """Run a program and return (vm, stdout) so the heap can be examined."""
    vm = vm_for(compile_source(source))
    buf = io.StringIO()
    with redirect_stdout(buf):
        vm.run_main()
    return vm, buf.getvalue()


def kinds_in(vm: QuinVM):
    return [vm._kind(hdr) for hdr in vm._blocks()]


class TestTheType(QuinTestCase):
    def test_it_is_one_word_and_a_reference(self):
        t = array_obj_type(Str)
        self.assertEqual(t.name, "Array<str>")
        self.assertEqual(word_count(t), 1)
        self.assertTrue(is_reference_type(t))

    def test_the_element_type_is_part_of_the_type(self):
        self.assertNotEqual(array_obj_type(Int), array_obj_type(Str))

    def test_it_reads_back_from_its_spelling(self):
        t = type_from_name("Array<int>")
        self.assertTrue(is_array_obj_type(t))
        self.assertEqual(t.element, Int)

    def test_it_nests(self):
        t = type_from_name("Array<Array<int>>")
        self.assertEqual(t.element, array_obj_type(Int))

    def test_a_function_type_is_an_element_type(self):
        t = type_from_name("Array<fn(int):int>")
        self.assertEqual(t.element.name, "fn(int):int")

    def test_element_extraction_ignores_other_types(self):
        self.assertIsNone(element_type_from_name("int"))
        self.assertIsNone(element_type_from_name("fn(int):int"))
        self.assertIsNone(element_type_from_name(None))

    def test_a_float_element_is_refused(self):
        # The header counts elements, and a float is two words. Refusing the
        # type is how that stays an invariant rather than a hazard.
        with self.assertRaises(UnknownTypeError) as cm:
            type_from_name("Array<float>")
        self.assertIn("two words", str(cm.exception))

    def test_a_frame_array_is_not_an_element(self):
        with self.assertRaises(UnknownTypeError):
            type_from_name("Array<int[4]>")

    def test_void_is_not_an_element(self):
        with self.assertRaises(UnknownTypeError):
            type_from_name("Array<void>")


class TestParsing(QuinTestCase):
    def _first_param_type(self, source: str) -> str:
        program = Parser(Lexer(source).tokenize()).parse()
        return program.functions[0].params[0].type_name

    def test_type_arguments_are_canonicalised(self):
        self.assertEqual(
            self._first_param_type("fn f(a: Array< Array< int > >): void {}"),
            "Array<Array<int>>")

    def test_a_closing_shift_is_split(self):
        # '>>' is the shift operator, so the lexer has already made one token of
        # it by the time the parser knows it is closing a type.
        self.assertPrints(main_wrapping("""
            let a: Array<Array<int>> = array_new(1);
            let b: Array<int> = array_new(1);
            b[0] = 7;
            a[0] = b;
            println(a[0][0]);
        """), "7")

    def test_a_closing_greater_equal_is_split(self):
        self.assertPrints(main_wrapping("""
            let a: Array<int>= array_new(1);
            a[0] = 9;
            println(a[0]);
        """), "9")

    def test_shifts_still_lex_as_operators(self):
        self.assertPrints(main_wrapping("println(16 >> 2); println(1 << 3);"),
                          "4", "8")

    def test_an_unknown_generic_name_is_reported_as_a_type(self):
        self.assertCompileError(
            main_wrapping("let a: Foo<int> = array_new(1);"),
            "Unknown type 'Foo<int>'")


class TestElements(QuinTestCase):
    def test_reading_gives_the_element_type(self):
        self.assertPrints(main_wrapping("""
            let a: Array<str> = array_new(2);
            a[1] = "hello";
            println(a[1]);
        """), "hello")

    def test_length_comes_from_the_object(self):
        self.assertPrints(main_wrapping("""
            let a: Array<int> = array_new(5);
            println(array_len(a));
        """), "5")

    def test_elements_start_zeroed(self):
        self.assertPrints(main_wrapping("""
            let a: Array<int> = array_new(3);
            println(a[0] + a[1] + a[2]);
        """), "0")

    def test_it_crosses_a_function_boundary(self):
        # The whole point of the type: an int[N] cannot be returned.
        self.assertPrints("""
            fn build(): Array<int> {
                let a: Array<int> = array_new(2);
                a[0] = 11;
                return a;
            }
            fn main(): int { println(build()[0]); return 0; }
        """, "11")

    def test_it_is_a_struct_field(self):
        self.assertPrints("""
            struct Box { items: Array<str> }
            fn main(): int {
                let b: Box = Box { items: array_new(1) };
                b.items[0] = "in a box";
                println(b.items[0]);
                return 0;
            }
        """, "in a box")

    def test_a_wrong_element_type_is_refused(self):
        self.assertCompileError(main_wrapping("""
            let a: Array<int> = array_new(1);
            a[0] = "s";
        """), "Cannot assign str to an element of Array<int>")

    def test_a_non_int_index_is_refused(self):
        self.assertCompileError(main_wrapping("""
            let a: Array<int> = array_new(1);
            println(a["x"]);
        """), "Array index must be int")

    def test_the_element_type_must_be_known(self):
        self.assertCompileError(main_wrapping("let a = array_new(4);"),
                                "Cannot tell what array_new builds here")

    def test_it_has_no_frame_address(self):
        self.assertCompileError(main_wrapping("""
            let a: Array<int> = array_new(2);
            let p: ptr = @a[0];
        """), "heap object, not a frame array")

    def test_array_len_needs_an_array(self):
        self.assertCompileError(main_wrapping("println(array_len(3));"),
                                "array_len expects an Array<T>, got int")


class TestBounds(QuinTestCase):
    def test_reading_past_the_end(self):
        self.assertRuntimeError(main_wrapping("""
            let a: Array<int> = array_new(2);
            println(a[2]);
        """), "Array index out of bounds: index=2, length=2")

    def test_a_negative_index(self):
        self.assertRuntimeError(main_wrapping("""
            let a: Array<int> = array_new(2);
            println(a[0 - 1]);
        """), "index=-1")

    def test_writing_past_the_end(self):
        self.assertRuntimeError(main_wrapping("""
            let a: Array<int> = array_new(2);
            a[5] = 1;
        """), "index=5, length=2")

    def test_a_computed_index_is_checked_too(self):
        # Nothing here is a literal, so the check can only be the run-time one.
        self.assertRuntimeError(main_wrapping("""
            let a: Array<int> = array_new(3);
            let i: int = 0;
            while (i < 10) { a[i] = i; i = i + 1; }
        """), "index=3, length=3")

    def test_a_zero_length_array_is_allowed_but_has_no_elements(self):
        self.assertRuntimeError(main_wrapping("""
            let a: Array<int> = array_new(0);
            println(array_len(a));
            println(a[0]);
        """), "length=0")


class TestHeapKinds(QuinTestCase):
    def test_a_reference_element_gets_the_traced_kind(self):
        vm, _ = run_and_inspect(main_wrapping(
            'let a: Array<str> = array_new(2); a[0] = "x";'))
        self.assertIn(KIND_REFARRAY, kinds_in(vm))
        self.assertNotIn(KIND_VALARRAY, kinds_in(vm))

    def test_a_value_element_gets_the_untraced_kind(self):
        vm, _ = run_and_inspect(main_wrapping(
            "let a: Array<int> = array_new(2); a[0] = 1;"))
        self.assertIn(KIND_VALARRAY, kinds_in(vm))
        self.assertNotIn(KIND_REFARRAY, kinds_in(vm))

    def test_codegen_picks_the_kind_from_the_element_type(self):
        for element, operand in (("int", 0), ("str", 1), ("bool", 0)):
            with self.subTest(element=element):
                program = compile_source(main_wrapping(
                    f"let a: Array<{element}> = array_new(1);"))
                new_array = [i for i in program.code
                             if i.op is OpCode.NEW_ARRAY]
                self.assertEqual([i.arg for i in new_array], [operand])

    def test_the_header_carries_the_element_count(self):
        vm, _ = run_and_inspect(main_wrapping(
            "let a: Array<int> = array_new(7);"))
        headers = [hdr for hdr in vm._blocks()
                   if vm._kind(hdr) == KIND_VALARRAY]
        self.assertEqual([vm._detail(hdr) for hdr in headers], [7])


class TestCollection(QuinTestCase):
    def test_an_element_is_a_root(self):
        # The array is the only thing keeping these strings alive: the frame
        # that built them is gone before gc() runs.
        self.assertPrints("""
            fn build(n: int): Array<str> {
                let a: Array<str> = array_new(n);
                for (let i = 0; i < n; i = i + 1) {
                    a[i] = "item " + int_to_str(i);
                }
                return a;
            }
            fn main(): int {
                let names: Array<str> = build(3);
                gc();
                println(names[0]);
                println(names[2]);
                return 0;
            }
        """, "item 0", "item 2")

    def test_elements_are_rewritten_when_the_array_moves(self):
        # Garbage below the array guarantees compaction actually slides it, so
        # both the reference to the array and the references inside it have to
        # be updated. Without the KIND_REFARRAY branch in _update_references
        # these elements would point at where their strings used to be.
        vm, out = run_and_inspect("""
            fn litter(): void {
                let junk: str = "x" + int_to_str(1);
            }
            fn main(): int {
                let i: int = 0;
                while (i < 40) { litter(); i = i + 1; }
                let a: Array<str> = array_new(2);
                a[0] = "first" + "";
                a[1] = "second" + "";
                gc();
                println(a[0]);
                println(a[1]);
                return 0;
            }
        """)
        self.assertGreater(vm.stats.objects_moved, 0,
                           "nothing moved, so this proves nothing")
        self.assertEqual(out, "first\nsecond\n")

    def test_a_value_array_is_not_traced(self):
        # An int element holding what looks like a heap address must not keep
        # anything alive, or every int array becomes a leak.
        vm, _ = run_and_inspect("""
            struct Node { value: int, next: Node }
            fn main(): int {
                let a: Array<int> = array_new(64);
                let doomed: Node = Node { value: 1, next: null };
                for (let i = 0; i < 64; i = i + 1) { a[i] = i * 2; }
                doomed = null;
                gc();
                println(a[3]);
                return 0;
            }
        """)
        self.assertGreater(vm.stats.objects_freed, 0,
                           "the struct should have been collected")

    def test_an_array_local_is_a_gc_root(self):
        program = compile_source(main_wrapping("""
            let a: Array<str> = array_new(1);
            let n: int = 5;
        """))
        main = next(f for f in program.functions if f.name == "main")
        names = {local.name: local.slot for local in main.locals_}
        self.assertIn(names["a"], main.ref_slots)
        self.assertNotIn(names["n"], main.ref_slots)

    def test_an_array_field_is_traced(self):
        program = compile_source("""
            struct Box { count: int, items: Array<int> }
            fn main(): int {
                let b: Box = Box { count: 0, items: array_new(1) };
                return 0;
            }
        """)
        box = next(s for s in program.structs if s.name == "Box")
        offsets = {f.name: f.offset for f in box.fields}
        self.assertIn(offsets["items"], box.ref_offsets)
        self.assertNotIn(offsets["count"], box.ref_offsets)

    def test_an_array_of_arrays_is_traced_through(self):
        self.assertPrints("""
            fn main(): int {
                let outer: Array<Array<int>> = array_new(2);
                for (let i = 0; i < 2; i = i + 1) {
                    let inner: Array<int> = array_new(2);
                    inner[0] = i * 10;
                    outer[i] = inner;
                }
                gc();
                println(outer[1][0]);
                return 0;
            }
        """, "10")

    def test_an_unreachable_array_is_freed(self):
        vm, _ = run_and_inspect("""
            fn drop(): void { let a: Array<str> = array_new(4); }
            fn main(): int {
                let i: int = 0;
                while (i < 50) { drop(); i = i + 1; }
                gc();
                return 0;
            }
        """)
        self.assertGreaterEqual(vm.stats.objects_freed, 50)
        self.assertEqual(vm.heap_in_use(), 0)


class TestTheHeapStaysParseable(QuinTestCase):
    def test_every_block_is_walkable_past_an_array(self):
        # _blocks() adds each block's size to reach the next one, so a kind
        # whose payload size is computed wrongly desynchronises the whole heap.
        vm, _ = run_and_inspect(main_wrapping("""
            let a: Array<int> = array_new(3);
            let b: Array<str> = array_new(1);
            let s: str = "after";
            b[0] = s;
            println(array_len(a) + array_len(b));
        """))
        blocks = list(vm._blocks())
        self.assertEqual(blocks, sorted(blocks))
        self.assertLessEqual(vm._block_end(blocks[-1]), vm.heap_ptr)

    def test_a_non_array_is_refused_by_the_array_opcodes(self):
        vm = vm_for(compile_source(main_wrapping('let s: str = "hi";')))
        with self.assertRaises(Exception) as cm:
            vm._array_at(2, "ARRAY_GET")
        self.assertIn("not an array", str(cm.exception))


class TestDebuggerDisplay(QuinTestCase):
    def test_an_array_shows_its_elements(self):
        from tests.harness import debug_session
        out = debug_session(main_wrapping("""
            let a: Array<int> = array_new(3);
            a[0] = 4;
            a[1] = 5;
            a[2] = 6;
            println(a[0]);
        """), ["break 7", "continue", "print a", "quit"])
        self.assertIn("4, 5, 6", out)


if __name__ == "__main__":
    unittest.main()
