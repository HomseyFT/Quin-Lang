"""Heap-allocated structs: declaration, literals, fields, and reference semantics.

A struct value is a reference into the heap, so these tests care as much about
aliasing and null as they do about reading a field back. The layout tests pin
the object header and the stack map, which exist for a collector to consume.
"""

import io
import unittest
from contextlib import redirect_stdout

from runtime.vm import QuinVM, HEADER_BYTES, KIND_RAW, KIND_STRUCT
from tests.harness import QuinTestCase, compile_source, run_source


POINT = "struct Point { x: int, y: int }\n"
NODE = "struct Node { value: int, next: Node }\n"


def run_and_inspect(source: str):
    """Run a program and hand back the finished VM, for poking at its heap.

    stdout is swallowed: these tests examine the heap rather than the output,
    and without this their programs print into the test runner's own output.
    """
    code, functions, strings, structs = compile_source(source)
    vm = QuinVM(code, functions, strings, structs)
    with redirect_stdout(io.StringIO()):
        vm.run_main()
    return vm


class TestDeclarationAndLiterals(QuinTestCase):
    def test_read_fields_back(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 3, y: 4 }; "
                    "println(p.x); println(p.y); return 0; }",
            "3", "4",
        )

    def test_literal_field_order_does_not_matter(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { y: 4, x: 3 }; "
                    "println(p.x); println(p.y); return 0; }",
            "3", "4",
        )

    def test_trailing_comma_in_literal(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 3, y: 4, }; "
                    "println(p.x); return 0; }",
            "3",
        )

    def test_trailing_comma_in_declaration(self):
        self.assertPrints(
            "struct P { a: int, b: int, }\n"
            "fn main(): int { let p: P = P { a: 1, b: 2 }; println(p.b); return 0; }",
            "2",
        )

    def test_type_is_inferred_from_a_literal(self):
        self.assertPrints(
            POINT + "fn main(): int { let p = Point { x: 8, y: 9 }; println(p.y); return 0; }",
            "9",
        )

    def test_field_assignment(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 1, y: 2 }; "
                    "p.y = 10; println(p.y); return 0; }",
            "10",
        )

    def test_field_expressions(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 3, y: 4 }; "
                    "println(p.x * p.y); p.x = p.x + p.y; println(p.x); return 0; }",
            "12", "7",
        )

    def test_literal_fields_evaluate_in_written_order(self):
        self.assertPrints(
            POINT +
            """
            fn shout(n: int): int { println(n); return n; }
            fn main(): int {
                let p: Point = Point { x: shout(1), y: shout(2) };
                println(p.x);
                return 0;
            }
            """,
            "1", "2", "1",
        )

    def test_several_structs_coexist(self):
        self.assertPrints(
            POINT + "struct Pair { a: int, b: int }\n"
            "fn main(): int { let p: Point = Point { x: 1, y: 2 }; "
            "let q: Pair = Pair { a: 3, b: 4 }; println(p.x); println(q.b); return 0; }",
            "1", "4",
        )

    def test_bool_and_str_fields(self):
        self.assertPrints(
            "struct Flag { on: bool, label: str }\n"
            "fn main(): int { let f: Flag = Flag { on: true, label: \"hi\" }; "
            "println(f.on); println(f.label); return 0; }",
            "true", "hi",
        )

    def test_single_field_struct(self):
        self.assertPrints(
            "struct Box { v: int }\n"
            "fn main(): int { let b: Box = Box { v: 5 }; println(b.v); return 0; }",
            "5",
        )


class TestReferenceSemantics(QuinTestCase):
    def test_assignment_shares_the_object(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 1, y: 2 }; "
                    "let q: Point = p; q.x = 99; println(p.x); return 0; }",
            "99",
        )

    def test_passing_to_a_function_shares_the_object(self):
        self.assertPrints(
            POINT +
            """
            fn bump(p: Point): void { p.x = p.x + 1; }
            fn main(): int {
                let p: Point = Point { x: 1, y: 2 };
                bump(p);
                println(p.x);
                return 0;
            }
            """,
            "2",
        )

    def test_a_function_can_return_a_struct(self):
        self.assertPrints(
            POINT +
            """
            fn make(a: int, b: int): Point { return Point { x: a, y: b }; }
            fn main(): int { let p: Point = make(7, 8); println(p.x); println(p.y); return 0; }
            """,
            "7", "8",
        )

    def test_distinct_literals_are_distinct_objects(self):
        self.assertPrints(
            POINT + "fn main(): int { let p: Point = Point { x: 1, y: 1 }; "
                    "let q: Point = Point { x: 1, y: 1 }; q.x = 5; println(p.x); return 0; }",
            "1",
        )

    def test_identity_comparison(self):
        self.assertPrints(
            POINT +
            """
            fn main(): int {
                let p: Point = Point { x: 1, y: 1 };
                let q: Point = Point { x: 1, y: 1 };
                let r: Point = p;
                println(p == q);
                println(p == r);
                println(p != q);
                return 0;
            }
            """,
            "false", "true", "true",
        )


class TestStructFields(QuinTestCase):
    def test_struct_typed_field(self):
        self.assertPrints(
            POINT + "struct Line { a: Point, b: Point }\n"
            "fn main(): int { let l: Line = Line { a: Point { x: 1, y: 2 }, "
            "b: Point { x: 3, y: 4 } }; println(l.a.x); println(l.b.y); return 0; }",
            "1", "4",
        )

    def test_nested_field_assignment(self):
        self.assertPrints(
            POINT + "struct Line { a: Point, b: Point }\n"
            "fn main(): int { let l: Line = Line { a: Point { x: 1, y: 2 }, "
            "b: Point { x: 3, y: 4 } }; l.a.x = 9; println(l.a.x); return 0; }",
            "9",
        )

    def test_self_referential_struct(self):
        self.assertPrints(
            NODE +
            """
            fn main(): int {
                let third: Node = Node { value: 3, next: null };
                let second: Node = Node { value: 2, next: third };
                let first: Node = Node { value: 1, next: second };
                println(first.next.next.value);
                return 0;
            }
            """,
            "3",
        )

    def test_walking_a_linked_list(self):
        self.assertPrints(
            NODE +
            """
            fn sum(head: Node): int {
                let total: int = 0;
                let cur: Node = head;
                while (cur != null) {
                    total = total + cur.value;
                    cur = cur.next;
                }
                return total;
            }
            fn main(): int {
                let head: Node = null;
                for (let i = 1; i < 5; i = i + 1) {
                    head = Node { value: i, next: head };
                }
                println(sum(head));
                return 0;
            }
            """,
            "10",
        )

    def test_forward_reference_to_a_later_struct(self):
        # Field types resolve in a second pass, so declaration order is free.
        self.assertPrints(
            "struct Outer { inner: Inner }\n"
            "struct Inner { v: int }\n"
            "fn main(): int { let o: Outer = Outer { inner: Inner { v: 6 } }; "
            "println(o.inner.v); return 0; }",
            "6",
        )

    def test_mutual_reference(self):
        self.assertPrints(
            "struct A { b: B, tag: int }\n"
            "struct B { a: A, tag: int }\n"
            "fn main(): int {\n"
            "    let x: A = A { b: null, tag: 1 };\n"
            "    let y: B = B { a: x, tag: 2 };\n"
            "    x.b = y;\n"
            "    println(x.b.a.tag);\n"
            "    return 0;\n"
            "}",
            "1",
        )


class TestNull(QuinTestCase):
    def test_uninitialized_struct_is_null(self):
        self.assertPrints(
            NODE + "fn main(): int { let n: Node; println(n == null); return 0; }",
            "true",
        )

    def test_null_initializer(self):
        self.assertPrints(
            NODE + "fn main(): int { let n: Node = null; println(n == null); return 0; }",
            "true",
        )

    def test_null_is_not_a_live_object(self):
        self.assertPrints(
            NODE + "fn main(): int { let n: Node = Node { value: 1, next: null }; "
                   "println(n != null); println(n.next == null); return 0; }",
            "true", "true",
        )

    def test_reading_a_field_through_null_faults(self):
        self.assertRuntimeError(
            NODE + "fn main(): int { let n: Node; println(n.value); return 0; }",
            "Null pointer dereference",
        )

    def test_reading_a_later_field_through_null_faults(self):
        # The regression this guards: adding the field offset before the null
        # check turns a null base into address 2, so the read silently returns
        # whatever lives there instead of faulting.
        #
        # The access at offset 1 must be the LAST one in the expression. Writing
        # this as `n.next.value` on a null n would still fault -- but on the
        # second access, at offset 0 -- and so would pass even with the bug
        # present. Use a struct whose second field is an int and read it
        # directly.
        self.assertRuntimeError(
            "struct Pair { a: int, b: int }\n"
            "fn main(): int { let p: Pair; println(p.b); return 0; }",
            "Null pointer dereference",
        )

    def test_reading_the_first_field_through_null_faults(self):
        self.assertRuntimeError(
            "struct Pair { a: int, b: int }\n"
            "fn main(): int { let p: Pair; println(p.a); return 0; }",
            "Null pointer dereference",
        )

    def test_chained_access_through_null_faults(self):
        self.assertRuntimeError(
            NODE + "fn main(): int { let n: Node; println(n.next.value); return 0; }",
            "Null pointer dereference",
        )

    def test_writing_a_later_field_through_null_faults(self):
        # The write counterpart: with the offset added first this would store
        # into address 2 rather than faulting, corrupting another object's header.
        self.assertRuntimeError(
            "struct Pair { a: int, b: int }\n"
            "fn main(): int { let p: Pair; p.b = 7; return 0; }",
            "Null pointer dereference",
        )

    def test_writing_the_first_field_through_null_faults(self):
        self.assertRuntimeError(
            NODE + "fn main(): int { let n: Node; n.value = 1; return 0; }",
            "Null pointer dereference",
        )

    def test_cannot_infer_a_type_from_bare_null(self):
        self.assertCompileError(
            "fn main(): int { let n = null; return 0; }",
            "Cannot infer type for 'n' from 'null'",
        )

    def test_null_is_not_assignable_to_a_different_struct(self):
        # null is fine, but a Point is not a Node.
        self.assertCompileError(
            POINT + NODE + "fn main(): int { let n: Node; let p: Point; n = p; return 0; }",
            "Cannot assign Point to Node",
        )

    def test_null_passes_as_a_struct_argument(self):
        self.assertPrints(
            NODE + "fn takes(n: Node): int { return 5; }\n"
            "fn main(): int { println(takes(null)); return 0; }",
            "5",
        )

    def test_null_returns_as_a_struct(self):
        self.assertPrints(
            NODE + "fn none(): Node { return null; }\n"
            "fn main(): int { println(none() == null); return 0; }",
            "true",
        )


class TestStructErrors(QuinTestCase):
    def test_unknown_struct_in_a_literal(self):
        self.assertCompileError(
            "fn main(): int { let p = Nope { x: 1 }; return 0; }", "Unknown struct 'Nope'"
        )

    def test_unknown_type_name(self):
        self.assertCompileError(
            "fn main(): int { let p: Nope; return 0; }", "Unknown type 'Nope'"
        )

    def test_unknown_field_read(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p: Point = Point { x: 1, y: 2 }; "
                    "println(p.z); return 0; }",
            "Struct 'Point' has no field 'z'",
        )

    def test_unknown_field_write(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p: Point = Point { x: 1, y: 2 }; "
                    "p.z = 1; return 0; }",
            "Struct 'Point' has no field 'z'",
        )

    def test_unknown_field_in_literal(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2, z: 3 }; return 0; }",
            "Struct 'Point' has no field 'z'",
        )

    def test_missing_field_in_literal(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1 }; return 0; }",
            "missing field(s): y",
        )

    def test_repeated_field_in_literal(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, x: 2, y: 3 }; return 0; }",
            "Field 'x' given twice",
        )

    def test_wrong_field_type_in_literal(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: true, y: 2 }; return 0; }",
            "Field 'x' expects int, got bool",
        )

    def test_wrong_field_type_in_assignment(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; p.x = true; return 0; }",
            "Cannot assign bool to field 'x'",
        )

    def test_duplicate_field_in_declaration(self):
        self.assertCompileError(
            "struct P { a: int, a: int }\nfn main(): int { return 0; }",
            "Duplicate field 'a' in struct 'P'",
        )

    def test_redefinition_of_a_struct(self):
        self.assertCompileError(
            "struct P { a: int }\nstruct P { b: int }\nfn main(): int { return 0; }",
            "Redefinition of struct 'P'",
        )

    def test_struct_cannot_shadow_a_builtin_type(self):
        self.assertCompileError(
            "struct int { a: int }\nfn main(): int { return 0; }",
            "Expected struct name",
        )

    def test_struct_cannot_shadow_bool(self):
        # 'bool' is not a keyword, so it parses as a name and sema must catch it.
        self.assertCompileError(
            "struct bool { a: int }\nfn main(): int { return 0; }",
            "shadows the built-in type 'bool'",
        )

    def test_empty_struct_is_rejected(self):
        self.assertCompileError(
            "struct Nothing { }\nfn main(): int { return 0; }",
            "must declare at least one field",
        )

    def test_array_field_is_rejected(self):
        self.assertCompileError(
            "struct Buf { data: int[4] }\nfn main(): int { return 0; }",
            "cannot be an array",
        )

    def test_void_field_is_rejected(self):
        self.assertCompileError(
            "struct V { nothing: void }\nfn main(): int { return 0; }",
            "cannot have type void",
        )

    def test_field_access_on_a_non_struct(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 1; println(x.y); return 0; }",
            "Field access requires a struct value, got int",
        )

    def test_struct_is_not_printable(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; println(p); return 0; }",
            "print/println expect int, float, str, or bool",
        )

    def test_struct_cannot_be_compared_relationally(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; "
                    "let q = Point { x: 1, y: 2 }; println(p < q); return 0; }",
            "Relational operators do not apply",
        )

    def test_struct_is_not_an_int(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; "
                    "let n: int = p; return 0; }",
            "Type mismatch in initializer",
        )

    def test_struct_and_heapptr_do_not_mix(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; "
                    "let h: heapptr = p; return 0; }",
            "Type mismatch in initializer",
        )

    def test_field_name_required_after_dot(self):
        self.assertCompileError(
            POINT + "fn main(): int { let p = Point { x: 1, y: 2 }; println(p.); return 0; }",
            "Expected field name after '.'",
        )


class TestObjectLayout(QuinTestCase):
    """The header and stack map exist for a collector; pin them now."""

    def test_struct_table_records_reference_fields(self):
        _, _, _, structs = compile_source(
            NODE + POINT + "fn main(): int { return 0; }"
        )
        by_name = {s.name: s for s in structs}
        self.assertEqual(by_name["Node"].word_size, 2)
        # 'next' is at word 1 and is a reference; 'value' is a plain int.
        self.assertEqual(by_name["Node"].ref_offsets, (1,))
        self.assertEqual(by_name["Point"].ref_offsets, ())

    def test_stack_map_lists_reference_slots_only(self):
        _, functions, _, _ = compile_source(
            NODE + "fn main(): int { let n: Node; let h: heapptr; let i: int; "
                   "let b: bool; return 0; }"
        )
        main = next(f for f in functions if f.name == "main")
        # Slots 0 (Node) and 1 (heapptr) are references; the int and bool are not.
        self.assertEqual(main.ref_slots, (0, 1))

    def test_struct_object_header_carries_its_type_id(self):
        vm = run_and_inspect(
            NODE + "fn main(): int { let n: Node = Node { value: 42, next: null }; return 0; }"
        )
        ref = vm.locals[0]
        self.assertNotEqual(ref, 0)
        hdr = ref - HEADER_BYTES
        self.assertEqual(vm._kind(hdr), KIND_STRUCT)
        self.assertEqual(vm._detail(hdr), 0)  # the only struct, so type id 0
        self.assertEqual(vm._read_word(ref), 42)

    def test_raw_allocation_header_records_its_size(self):
        vm = run_and_inspect(
            "fn main(): int { let h: heapptr = alloc(6); return 0; }"
        )
        hdr = vm.locals[0] - HEADER_BYTES
        self.assertEqual(vm._kind(hdr), KIND_RAW,
                         "raw blocks are kept alive but never traced through")
        self.assertEqual(vm._detail(hdr), 6)

    def test_allocations_do_not_overlap_their_headers(self):
        vm = run_and_inspect(
            NODE + "fn main(): int { let a: Node = Node { value: 1, next: null }; "
                   "let b: Node = Node { value: 2, next: null }; return 0; }"
        )
        a, b = vm.locals[0], vm.locals[1]
        self.assertNotEqual(a, b)
        # b's header sits above a's two-word body.
        self.assertGreaterEqual(b - HEADER_BYTES, a + 4)
        self.assertEqual(vm._read_word(a), 1)
        self.assertEqual(vm._read_word(b), 2)

    def test_a_struct_local_occupies_one_slot(self):
        _, functions, _, _ = compile_source(
            NODE + "fn main(): int { let a: Node; let b: Node; return 0; }"
        )
        main = next(f for f in functions if f.name == "main")
        self.assertEqual(main.num_locals, 2)

    def test_a_block_larger_than_the_heap_is_rejected(self):
        # The size now has a header word to itself, so the only limit left is
        # the heap. Two blocks of 32767 cannot both fit in 64 KiB, and the
        # first is still reachable when the second is requested.
        self.assertRuntimeError(
            "fn main(): int { let a: heapptr = alloc(32767); "
            "let b: heapptr = alloc(32767); println(heap_load(a)); return 0; }",
            "Heap out of memory",
        )

    def test_the_largest_single_block_now_fits(self):
        self.assertPrints(
            "fn main(): int { let h: heapptr = alloc(32767); heap_store(h, 5); "
            "println(heap_load(h)); return 0; }",
            "5",
        )

    def test_the_upper_half_of_the_heap_is_usable(self):
        # Heap addresses run to 65535. Sign-extending one would make every
        # object above 32767 look like a negative address and fault. A live
        # Node costs 8 bytes, so 6000 of them reach well past the halfway
        # mark while still fitting in 64 KiB.
        source = NODE + """
            fn main(): int {
                let head: Node = null;
                for (let i = 0; i < 6000; i = i + 1) {
                    head = Node { value: i, next: head };
                }
                println(head.value);
                return 0;
            }
            """
        self.assertPrints(source, "5999")
        vm = run_and_inspect(source)
        self.assertGreater(vm.locals[0], 0x8000,
                           "the list should have grown past the signed-word boundary")

    def test_heap_still_runs_out(self):
        self.assertRuntimeError(
            NODE +
            """
            fn main(): int {
                let n: Node;
                for (;;) {
                    n = Node { value: 1, next: n };
                }
                return 0;
            }
            """,
            "Heap out of memory",
        )


class TestStructsAcrossFiles(QuinTestCase):
    def test_struct_declared_before_the_functions_that_use_it(self):
        self.assertPrints(
            "struct P { v: int }\n"
            "fn get(p: P): int { return p.v; }\n"
            "fn main(): int { println(get(P { v: 4 })); return 0; }",
            "4",
        )

    def test_struct_may_follow_the_functions_that_use_it(self):
        self.assertPrints(
            "fn get(p: P): int { return p.v; }\n"
            "struct P { v: int }\n"
            "fn main(): int { println(get(P { v: 4 })); return 0; }",
            "4",
        )


if __name__ == "__main__":
    unittest.main()
