"""Pointers, memory intrinsics, and the two address spaces.

`ptr` (a frame slot index, from `@`) and `heapptr` (a byte offset, from
`alloc`) are distinct types. Mixing them used to typecheck and silently read
the wrong memory; these tests pin that it no longer does.
"""

import unittest

from tests.harness import QuinTestCase


class TestFramePointers(QuinTestCase):
    def test_store16_then_read_the_variable(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int;
                let p: ptr;
                p = @x;
                store16(p, 4321);
                println(x);
                return 0;
            }
            """,
            "4321",
        )

    def test_load16_round_trip(self):
        self.assertPrints(
            """
            fn main(): int {
                let x: int = 1234;
                let p: ptr;
                p = @x;
                println(load16(p));
                return 0;
            }
            """,
            "1234",
        )

    def test_address_of_an_array_element(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                let p: ptr;
                a[1] = 55;
                p = @a[1];
                println(load16(p));
                return 0;
            }
            """,
            "55",
        )

    def test_address_of_a_computed_element(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                let i: int = 2;
                let p: ptr;
                a[2] = 9;
                p = @a[i];
                println(load16(p));
                return 0;
            }
            """,
            "9",
        )

    def test_cannot_take_the_address_of_a_literal(self):
        self.assertCompileError(
            "fn main(): int { let p: ptr; p = @1; return 0; }",
            "Can only take address of variables or array elements",
        )


class TestMemoryIntrinsics(QuinTestCase):
    def test_memcpy_counts_slots(self):
        # A 3-element array is copied with a count of 3, not 6 bytes. The
        # guard variable proves the copy stops where it should.
        self.assertPrints(
            """
            fn main(): int {
                let src: int[3];
                let dst: int[3];
                let guard: int = 999;
                src[0] = 7; src[1] = 8; src[2] = 9;
                memcpy(@dst[0], @src[0], 3);
                println(dst[0]); println(dst[1]); println(dst[2]);
                println(guard);
                return 0;
            }
            """,
            "7", "8", "9", "999",
        )

    def test_memset_counts_slots(self):
        self.assertPrints(
            """
            fn main(): int {
                let buf: int[3];
                let guard: int = 42;
                buf[0] = 1; buf[1] = 2; buf[2] = 3;
                memset(@buf[0], 0, 3);
                println(buf[0]); println(buf[2]); println(guard);
                return 0;
            }
            """,
            "0", "0", "42",
        )

    def test_memset_writes_whole_words(self):
        self.assertPrints(
            """
            fn main(): int {
                let buf: int[2];
                memset(@buf[0], 513, 2);
                println(buf[0]);
                return 0;
            }
            """,
            "513",
        )

    def test_overlapping_memcpy_shifts_correctly(self):
        # Copying up by one must run back to front, or the first element
        # smears across the whole range.
        self.assertPrints(
            """
            fn main(): int {
                let a: int[4];
                a[0] = 1; a[1] = 2; a[2] = 3;
                memcpy(@a[1], @a[0], 3);
                println(a[0]); println(a[1]); println(a[2]); println(a[3]);
                return 0;
            }
            """,
            "1", "1", "2", "3",
        )

    def test_negative_count_is_a_runtime_error(self):
        self.assertRuntimeError(
            """
            fn main(): int {
                let a: int[2];
                let b: int[2];
                memcpy(@b[0], @a[0], 0 - 1);
                return 0;
            }
            """,
            "negative count",
        )


class TestHeap(QuinTestCase):
    def test_round_trip(self):
        self.assertPrints(
            """
            fn main(): int {
                let p: heapptr;
                p = alloc(2);
                heap_store(p, 1234);
                println(heap_load(p));
                return 0;
            }
            """,
            "1234",
        )

    def test_fresh_memory_is_zero(self):
        self.assertPrints(
            "fn main(): int { let p: heapptr; p = alloc(2); println(heap_load(p)); return 0; }",
            "0",
        )

    def test_allocations_do_not_overlap(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: heapptr;
                let b: heapptr;
                a = alloc(2);
                b = alloc(2);
                heap_store(a, 11);
                heap_store(b, 22);
                println(heap_load(a));
                println(heap_load(b));
                return 0;
            }
            """,
            "11", "22",
        )

    def test_words_are_two_bytes_apart(self):
        self.assertPrints(
            """
            fn main(): int {
                let base: heapptr;
                base = alloc(4);
                heap_store(base, 100);
                println(heap_load(base));
                return 0;
            }
            """,
            "100",
        )

    def test_type_is_inferred_from_alloc(self):
        self.assertPrints(
            "fn main(): int { let p = alloc(2); heap_store(p, 7); println(heap_load(p)); return 0; }",
            "7",
        )

    def test_exhaustion_is_a_runtime_error(self):
        self.assertRuntimeError(
            """
            fn main(): int {
                let p: heapptr;
                let i: int;
                while (i < 1000) { p = alloc(100); i = i + 1; }
                return 0;
            }
            """,
            "Heap out of memory",
        )


class TestAddressSpacesAreDisjoint(QuinTestCase):
    """The whole point of splitting ptr and heapptr."""

    def test_load16_rejects_a_heap_pointer(self):
        self.assertCompileError(
            "fn main(): int { let p: heapptr; p = alloc(2); println(load16(p)); return 0; }",
            "expected ptr, got heapptr",
        )

    def test_heap_load_rejects_a_frame_pointer(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let p: ptr; p = @x; println(heap_load(p)); return 0; }",
            "expected heapptr, got ptr",
        )

    def test_store16_rejects_a_heap_pointer(self):
        self.assertCompileError(
            "fn main(): int { let p: heapptr; p = alloc(2); store16(p, 1); return 0; }",
            "expected ptr, got heapptr",
        )

    def test_heap_store_rejects_a_frame_pointer(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let p: ptr; p = @x; heap_store(p, 1); return 0; }",
            "expected heapptr, got ptr",
        )

    def test_memcpy_rejects_heap_pointers(self):
        self.assertCompileError(
            "fn main(): int { let p: heapptr; p = alloc(4); memset(p, 0, 2); return 0; }",
            "expected ptr, got heapptr",
        )

    def test_cannot_assign_a_heap_pointer_to_a_frame_pointer(self):
        self.assertCompileError(
            "fn main(): int { let p: ptr; p = alloc(2); return 0; }",
            "Cannot assign heapptr to ptr",
        )

    def test_cannot_assign_a_frame_pointer_to_a_heap_pointer(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let h: heapptr; h = @x; return 0; }",
            "Cannot assign ptr to heapptr",
        )

    def test_cannot_compare_across_address_spaces(self):
        self.assertCompileError(
            """
            fn main(): int {
                let x: int;
                let p: ptr;
                let h: heapptr;
                p = @x;
                h = alloc(2);
                if (p == h) { println(1); }
                return 0;
            }
            """,
            "Comparison requires operands of same type",
        )

    def test_address_of_still_yields_ptr(self):
        self.assertCompiles(
            "fn main(): int { let x: int; let p: ptr; p = @x; return 0; }"
        )


class TestArrayHelpers(QuinTestCase):
    def test_push_returns_the_new_length(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                let len: int;
                len = array_push(a, len, 10);
                println(len);
                len = array_push(a, len, 20);
                println(len);
                println(a[0]); println(a[1]);
                return 0;
            }
            """,
            "1", "2", "10", "20",
        )

    def test_pop_reads_the_last_element_without_changing_length(self):
        self.assertPrints(
            """
            fn main(): int {
                let a: int[3];
                let len: int;
                len = array_push(a, len, 10);
                len = array_push(a, len, 20);
                println(array_pop(a, len));
                println(len);
                return 0;
            }
            """,
            "20", "2",
        )

    def test_push_argument_must_be_a_named_array(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; let n: int; n = array_push(a[0], 0, 1); return 0; }",
            "array_push first argument must be int[N] array",
        )

    def test_push_arity(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; array_push(a, 0); return 0; }",
            "array_push expects 3 arguments",
        )

    def test_pop_arity(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; array_pop(a); return 0; }",
            "array_pop expects 2 arguments",
        )


if __name__ == "__main__":
    unittest.main()
