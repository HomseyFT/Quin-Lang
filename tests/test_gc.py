"""The garbage collector: what it reclaims, and what it must never reclaim.

The collector is precise. Roots come from each frame's stack map and from the
operand stack, whose entries the VM tags as it pushes them. These tests care
mostly about the second kind: an object can be live while sitting in no
variable at all, and that is the case a naive collector gets wrong.
"""

import io
import unittest
from contextlib import redirect_stdout

from runtime.vm import QuinVM, KIND_FREE, KIND_RAW, HEADER_BYTES
from tests.harness import QuinTestCase, compile_source


NODE = "struct Node { value: int, next: Node }\n"


def run_and_inspect(source: str):
    """Run a program and return (vm, stdout) so the heap can be examined."""
    code, functions, strings, structs = compile_source(source)
    vm = QuinVM(code, functions, strings, structs)
    buf = io.StringIO()
    with redirect_stdout(buf):
        vm.run_main()
    return vm, buf.getvalue()


class TestReclaiming(QuinTestCase):
    def test_unreachable_objects_are_freed(self):
        vm, _ = run_and_inspect(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 1, next: null }; }
            fn main(): int {
                let i: int;
                while (i < 100) { drop(); i = i + 1; }
                gc();
                return 0;
            }
            """
        )
        self.assertEqual(vm.stats.collections, 1)
        self.assertGreaterEqual(vm.stats.objects_freed, 100)
        # Nothing survives: drop()'s frame is gone by the time gc() runs.
        self.assertEqual(vm.heap_in_use(), 0)

    def test_reachable_objects_survive(self):
        self.assertPrints(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 9, next: null }; }
            fn main(): int {
                let keep: Node = Node { value: 42, next: null };
                let i: int;
                while (i < 100) { drop(); i = i + 1; }
                gc();
                println(keep.value);
                return 0;
            }
            """,
            "42",
        )

    def test_a_whole_list_survives(self):
        self.assertPrints(
            NODE +
            """
            fn sum(head: Node): int {
                let total: int = 0;
                let cur: Node = head;
                while (cur != null) { total = total + cur.value; cur = cur.next; }
                return total;
            }
            fn main(): int {
                let head: Node = null;
                for (let i = 1; i < 21; i = i + 1) {
                    head = Node { value: i, next: head };
                }
                gc();
                println(sum(head));
                return 0;
            }
            """,
            "210",
        )

    def test_memory_is_reused_after_collection(self):
        vm, _ = run_and_inspect(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 1, next: null }; }
            fn main(): int {
                let i: int;
                while (i < 50) { drop(); i = i + 1; }
                gc();
                let after: Node = Node { value: 2, next: null };
                return 0;
            }
            """
        )
        # 50 dead nodes were reclaimed, so the survivor fits in freed space
        # rather than extending the heap.
        self.assertLess(vm.heap_ptr, 200)

    def test_dropping_references_lets_a_program_outlive_the_heap(self):
        # 20000 nodes is far more than 64 KiB holds. This only completes
        # because collection runs on its own when an allocation cannot be met.
        vm, out = run_and_inspect(
            NODE +
            """
            fn main(): int {
                let i: int;
                while (i < 20000) {
                    let junk: Node = Node { value: i, next: null };
                    i = i + 1;
                }
                println(i);
                return 0;
            }
            """
        )
        self.assertEqual(out.strip(), "20000")
        self.assertGreater(vm.stats.collections, 0,
                           "the heap cannot hold 20000 nodes without collecting")

    def test_collection_happens_without_an_explicit_call(self):
        self.assertPrints(
            """
            fn main(): int {
                let p: heapptr;
                let i: int;
                while (i < 2000) { p = alloc(60); i = i + 1; }
                println(i);
                return 0;
            }
            """,
            "2000",
        )

    def test_exhaustion_still_reported_when_everything_is_live(self):
        self.assertRuntimeError(
            NODE +
            """
            fn main(): int {
                let head: Node = null;
                for (;;) { head = Node { value: 1, next: head }; }
                return 0;
            }
            """,
            "Heap out of memory",
        )


class TestRootsOnTheOperandStack(QuinTestCase):
    """Objects can be live while held in no variable at all."""

    def test_object_under_construction_survives_a_nested_collection(self):
        # While the outer literal's fields are being filled, the outer object
        # exists only on the operand stack. make() collects in the middle of
        # that, so the outer object is reachable through nothing else.
        self.assertPrints(
            NODE +
            """
            fn make(v: int): Node { gc(); return Node { value: v, next: null }; }
            fn main(): int {
                let n: Node = Node { value: 7, next: make(9) };
                println(n.value);
                println(n.next.value);
                return 0;
            }
            """,
            "7", "9",
        )

    def test_nested_literals_survive_real_collection_pressure(self):
        # churn() must allocate more than the heap holds, so that a collection
        # genuinely happens while the outer object is still under construction.
        # At a count that fits in 64 KiB this passes without ever collecting
        # and proves nothing, so the collection is asserted too.
        source = NODE + """
            fn churn(): int {
                let i: int;
                while (i < 12000) { let junk: Node = Node { value: 0, next: null }; i = i + 1; }
                return 5;
            }
            fn main(): int {
                let n: Node = Node { value: churn(), next: Node { value: 6, next: null } };
                println(n.value);
                println(n.next.value);
                return 0;
            }
            """
        self.assertPrints(source, "5", "6")
        vm, _ = run_and_inspect(source)
        self.assertGreater(vm.stats.collections, 0,
                           "churn() must actually force a collection")

    def test_arguments_in_flight_survive(self):
        # first is evaluated and sits on the operand stack while second
        # allocates and collects.
        self.assertPrints(
            NODE +
            """
            fn pick(a: Node, b: Node): int { return a.value + b.value; }
            fn second(): Node { gc(); return Node { value: 20, next: null }; }
            fn main(): int {
                println(pick(Node { value: 1, next: null }, second()));
                return 0;
            }
            """,
            "21",
        )

    def test_a_returned_reference_stays_tagged_across_ret(self):
        # make()'s object is returned onto the operand stack and waits there
        # while collector() runs a cycle. RET must carry the value's reference
        # flag back into the caller, or that object is invisible to the mark
        # phase and gets freed while still needed.
        self.assertPrints(
            NODE +
            """
            fn make(): Node { return Node { value: 3, next: null }; }
            fn collector(): Node { gc(); return Node { value: 4, next: null }; }
            fn add(a: Node, b: Node): int { return a.value + b.value; }
            fn main(): int { println(add(make(), collector())); return 0; }
            """,
            "7",
        )


class TestRootsInCallerFrames(QuinTestCase):
    def test_a_suspended_frame_keeps_its_objects_alive(self):
        self.assertPrints(
            NODE +
            """
            fn inner(): int { gc(); return 1; }
            fn outer(held: Node): int { let r: int = inner(); return held.value + r; }
            fn main(): int {
                let n: Node = Node { value: 41, next: null };
                println(outer(n));
                return 0;
            }
            """,
            "42",
        )

    def test_deep_recursion_keeps_every_frame_alive(self):
        self.assertPrints(
            NODE +
            """
            fn down(depth: int, held: Node): int {
                if (depth == 0) {
                    gc();
                    return held.value;
                }
                let mine: Node = Node { value: depth, next: held };
                return down(depth - 1, mine);
            }
            fn main(): int {
                let root: Node = Node { value: 100, next: null };
                println(down(20, root));
                return 0;
            }
            """,
            "1",
        )


class TestTracing(QuinTestCase):
    def test_objects_reachable_through_fields_survive(self):
        self.assertPrints(
            NODE +
            """
            fn main(): int {
                let head: Node = Node { value: 1, next: Node { value: 2, next:
                                  Node { value: 3, next: null } } };
                gc();
                println(head.next.next.value);
                return 0;
            }
            """,
            "3",
        )

    def test_cycles_are_collected(self):
        # A reference counter would leak every one of these.
        vm, _ = run_and_inspect(
            NODE +
            """
            fn cycle(): void {
                let a: Node = Node { value: 1, next: null };
                let b: Node = Node { value: 2, next: a };
                a.next = b;
            }
            fn main(): int {
                let i: int;
                while (i < 50) { cycle(); i = i + 1; }
                gc();
                return 0;
            }
            """
        )
        self.assertEqual(vm.heap_in_use(), 0, "a cycle with no root is garbage")
        self.assertGreaterEqual(vm.stats.objects_freed, 100)

    def test_a_live_cycle_survives(self):
        self.assertPrints(
            NODE +
            """
            fn main(): int {
                let a: Node = Node { value: 1, next: null };
                let b: Node = Node { value: 2, next: a };
                a.next = b;
                gc();
                println(a.next.value);
                println(a.next.next.value);
                return 0;
            }
            """,
            "2", "1",
        )

    def test_dropping_the_head_frees_the_whole_list(self):
        vm, _ = run_and_inspect(
            NODE +
            """
            fn build(): void {
                let head: Node = null;
                for (let i = 0; i < 30; i = i + 1) {
                    head = Node { value: i, next: head };
                }
            }
            fn main(): int { build(); gc(); return 0; }
            """
        )
        self.assertEqual(vm.heap_in_use(), 0)


class TestRawBlocks(QuinTestCase):
    def test_a_reachable_raw_block_survives(self):
        self.assertPrints(
            """
            fn main(): int {
                let h: heapptr = alloc(8);
                heap_store(h, 1234);
                let i: int;
                while (i < 200) { let junk: heapptr = alloc(8); i = i + 1; }
                gc();
                println(heap_load(h));
                return 0;
            }
            """,
            "1234",
        )

    def test_unreachable_raw_blocks_are_freed(self):
        vm, _ = run_and_inspect(
            """
            fn drop(): void { let junk: heapptr = alloc(8); }
            fn main(): int {
                let i: int;
                while (i < 100) { drop(); i = i + 1; }
                gc();
                return 0;
            }
            """
        )
        self.assertEqual(vm.heap_in_use(), 0)

    def test_a_raw_block_is_kept_but_not_traced(self):
        # The header marks it KIND_RAW, which is what tells the collector to
        # keep it alive without reading its contents as references.
        vm, _ = run_and_inspect(
            "fn main(): int { let h: heapptr = alloc(4); heap_store(h, 12); "
            "gc(); println(heap_load(h)); return 0; }"
        )
        hdr = vm.locals[0] - HEADER_BYTES
        self.assertEqual(vm._kind(hdr), KIND_RAW)

    def test_an_interior_pointer_keeps_its_block_alive(self):
        # heapptr arithmetic can point into the middle of a block, and such a
        # pointer still keeps the whole block alive.
        #
        # The read has to happen after the space could have been handed out
        # again. Sweeping leaves the old contents in place, so reading straight
        # after a wrongly-freed collection still returns the right value and
        # hides the bug; allocating over it first is what exposes it.
        self.assertPrints(
            """
            fn main(): int {
                let base: heapptr = alloc(8);
                let inside: heapptr = base + 6;
                heap_store(inside, 88);
                base = null;
                gc();
                let other: heapptr = alloc(8);
                heap_store(other, 1);
                heap_store(other + 2, 2);
                heap_store(other + 4, 3);
                heap_store(other + 6, 4);
                println(heap_load(inside));
                return 0;
            }
            """,
            "88",
        )


class TestFreeList(QuinTestCase):
    def test_adjacent_free_blocks_coalesce(self):
        vm, _ = run_and_inspect(
            "struct Big { a: int, b: int, c: int, d: int }\n"
            "struct Small { v: int }\n"
            """
            fn drop(): void { let junk: Big = Big { a: 1, b: 2, c: 3, d: 4 }; }
            fn main(): int {
                let keep: Small = Small { v: 1 };
                let i: int;
                while (i < 40) { drop(); i = i + 1; }
                gc();
                println(keep.v);
                return 0;
            }
            """
        )
        # 40 dead blocks in a row become one, not 40.
        self.assertLessEqual(len(vm.free_blocks()), 1,
                             f"expected coalescing, got {vm.free_blocks()}")

    def test_a_freed_block_is_reused_for_a_later_object(self):
        vm, out = run_and_inspect(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 1, next: null }; }
            fn main(): int {
                drop();
                gc();
                let reused: Node = Node { value: 5, next: null };
                println(reused.value);
                return 0;
            }
            """
        )
        self.assertEqual(out.strip(), "5")
        # One node's worth of heap, not two: the second reused the first's space.
        self.assertEqual(vm.heap_in_use(), 8)

    def test_a_large_object_can_use_a_coalesced_run(self):
        self.assertPrints(
            "struct Small { v: int }\n"
            "struct Big { a: int, b: int, c: int, d: int, e: int, f: int }\n"
            """
            fn drop(): void { let junk: Small = Small { v: 1 }; }
            fn main(): int {
                let i: int;
                while (i < 20) { drop(); i = i + 1; }
                gc();
                let big: Big = Big { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 };
                println(big.f);
                return 0;
            }
            """,
            "6",
        )

    def test_the_heap_stays_consistent_across_many_cycles(self):
        vm, out = run_and_inspect(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 1, next: null }; }
            fn main(): int {
                let keep: Node = Node { value: 7, next: null };
                for (let round = 0; round < 30; round = round + 1) {
                    for (let i = 0; i < 20; i = i + 1) { drop(); }
                    gc();
                }
                println(keep.value);
                return 0;
            }
            """
        )
        self.assertEqual(out.strip(), "7")
        self.assertEqual(vm.stats.collections, 30)
        self.assertEqual(vm.heap_in_use(), 8, "only 'keep' should remain")
        # Every block in the heap must still parse.
        for hdr in vm._blocks():
            self.assertIn(vm._kind(hdr), (0, KIND_RAW, KIND_FREE))


class TestOperandStackTagging(QuinTestCase):
    """The tagging rules themselves, at the level of single instructions.

    Some of these are not reachable from current QuinLang source: the compiler
    never emits a sequence where, say, only a DUPed copy of a reference remains.
    They are pinned anyway, because the collector's soundness rests on the rule
    being uniform rather than on which sequences codegen happens to produce.
    """

    def _vm(self, source: str):
        code, functions, strings, structs = compile_source(source)
        return QuinVM(code, functions, strings, structs)

    def test_dup_copies_the_reference_flag(self):
        from compiler.bytecode import Instruction, OpCode
        vm = self._vm(NODE + "fn main(): int { return 0; }")
        vm.locals = [0]
        vm.code = [Instruction(OpCode.ALLOC_TYPED, 0), Instruction(OpCode.DUP)]
        vm.pc = 0
        vm._run()
        self.assertEqual(vm.stack_is_ref, [True, True],
                         "a duplicated reference is still a reference")

    def test_push_int_is_not_a_reference(self):
        from compiler.bytecode import Instruction, OpCode
        vm = self._vm(NODE + "fn main(): int { return 0; }")
        vm.locals = [0]
        vm.code = [Instruction(OpCode.PUSH_INT, 4)]
        vm.pc = 0
        vm._run()
        self.assertEqual(vm.stack_is_ref, [False])

    def test_swap_carries_the_flags_with_the_values(self):
        from compiler.bytecode import Instruction, OpCode
        vm = self._vm(NODE + "fn main(): int { return 0; }")
        vm.locals = [0]
        vm.code = [
            Instruction(OpCode.ALLOC_TYPED, 0),
            Instruction(OpCode.PUSH_INT, 9),
            Instruction(OpCode.SWAP),
        ]
        vm.pc = 0
        vm._run()
        self.assertEqual(vm.stack_is_ref, [False, True])

    def test_heapptr_arithmetic_stays_a_reference(self):
        # heapptr + int is still a heap address, and an interior one at that.
        from compiler.bytecode import Instruction, OpCode
        vm = self._vm(NODE + "fn main(): int { return 0; }")
        vm.locals = [0]
        vm.code = [
            Instruction(OpCode.ALLOC_TYPED, 0),
            Instruction(OpCode.PUSH_INT, 2),
            Instruction(OpCode.ADD),
        ]
        vm.pc = 0
        vm._run()
        self.assertEqual(vm.stack_is_ref, [True])

    def test_arithmetic_on_plain_ints_is_not_a_reference(self):
        from compiler.bytecode import Instruction, OpCode
        vm = self._vm(NODE + "fn main(): int { return 0; }")
        vm.locals = [0]
        vm.code = [
            Instruction(OpCode.PUSH_INT, 3),
            Instruction(OpCode.PUSH_INT, 4),
            Instruction(OpCode.ADD),
        ]
        vm.pc = 0
        vm._run()
        self.assertEqual(vm.stack_is_ref, [False])

    def test_a_struct_field_load_is_tagged_from_the_header(self):
        # Reading 'next' yields a reference; reading 'value' does not. The VM
        # learns which is which from the object's header, not from the compiler.
        vm, _ = run_and_inspect(
            NODE + "fn main(): int { let n: Node = Node { value: 1, next: null }; return 0; }"
        )
        ref = vm.locals[0]
        self.assertTrue(vm._field_is_ref(ref, 1), "'next' is a reference field")
        self.assertFalse(vm._field_is_ref(ref, 0), "'value' is an int")

    def test_stack_and_flags_stay_the_same_length(self):
        vm, _ = run_and_inspect(
            NODE +
            """
            fn f(a: Node, b: int): int { return b + a.value; }
            fn main(): int {
                let n: Node = Node { value: 1, next: null };
                let total: int = 0;
                for (let i = 0; i < 5; i = i + 1) {
                    total = total + f(n, i) * 2 - 1;
                }
                println(total);
                return 0;
            }
            """
        )
        self.assertEqual(len(vm.stack), len(vm.stack_is_ref))


class TestGcBuiltin(QuinTestCase):
    def test_gc_is_callable_as_a_statement(self):
        self.assertPrints("fn main(): int { gc(); println(1); return 0; }", "1")

    def test_gc_returns_void(self):
        self.assertCompileError(
            "fn main(): int { let x: int = gc(); return 0; }",
            "Type mismatch in initializer",
        )

    def test_gc_takes_no_arguments(self):
        self.assertCompileError(
            "fn main(): int { gc(1); return 0; }", "expects 0 args"
        )

    def test_gc_cannot_be_redefined(self):
        self.assertCompileError(
            "fn gc(): void { }\nfn main(): int { return 0; }",
            "Redefinition of function 'gc'",
        )

    def test_statistics_report_work_done(self):
        vm, _ = run_and_inspect(
            NODE +
            """
            fn drop(): void { let junk: Node = Node { value: 1, next: null }; }
            fn main(): int {
                let i: int;
                while (i < 10) { drop(); i = i + 1; }
                gc();
                gc();
                return 0;
            }
            """
        )
        self.assertEqual(vm.stats.collections, 2)
        self.assertEqual(vm.stats.objects_allocated, 10)
        self.assertEqual(vm.stats.objects_freed, 10)
        self.assertGreater(vm.stats.bytes_freed, 0)


if __name__ == "__main__":
    unittest.main()
