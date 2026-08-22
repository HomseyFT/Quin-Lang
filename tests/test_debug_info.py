"""Source mapping and the debug tables built beside the bytecode.

A runtime fault used to say only what went wrong. Everything here is about
saying *where*: a pc -> source position map, a per-frame table of named slots,
and the file each function came from. The interpreter loop reads none of it,
so the cost is paid only when something fails or a debugger asks.

These are the foundation the debugger sits on, which is why the positions are
asserted exactly rather than loosely: a map that is off by one instruction is
worse than none, because it points confidently at the wrong line.
"""

import unittest

from compiler.bytecode import SourceMap, SourceMapBuilder
from runtime.vm import QuinVM, VMError
from tests.harness import QuinTestCase, compile_source, run_source


def fault(source: str) -> VMError:
    """Run a program expected to fault, and return the error."""
    try:
        run_source(source)
    except VMError as e:
        return e
    raise AssertionError("expected the program to fault, but it completed")


class TestSourceMapStructure(unittest.TestCase):
    """The marker table itself, independent of codegen."""

    def test_lookup_finds_the_marker_in_force(self):
        m = SourceMapBuilder()
        m.mark(0, 1, 1)
        m.mark(4, 7, 3)
        table = m.build()
        self.assertEqual(table.lookup(0), (1, 1))
        self.assertEqual(table.lookup(3), (1, 1), "still inside the first run")
        self.assertEqual(table.lookup(4), (7, 3))
        self.assertEqual(table.lookup(99), (7, 3), "the last marker runs on")

    def test_a_pc_before_the_first_marker_is_unmapped(self):
        table = SourceMapBuilder().build()
        self.assertIsNone(table.lookup(0))
        self.assertEqual(table.describe(0), "",
                         "describe must be safe to concatenate")

    def test_the_innermost_node_at_a_pc_wins(self):
        # Entering a statement and then an expression without emitting between
        # them leaves two markers at the same pc. The inner one is correct.
        m = SourceMapBuilder()
        m.mark(0, 1, 1)
        m.mark(0, 1, 9)
        self.assertEqual(m.build().lookup(0), (1, 9))

    def test_repeated_positions_collapse(self):
        # Otherwise every nested expression on one line would add an entry.
        m = SourceMapBuilder()
        m.mark(0, 1, 1)
        m.mark(2, 1, 1)
        m.mark(4, 1, 1)
        self.assertEqual(len(m.build().pcs), 1)

    def test_describe_formats_like_a_compile_error(self):
        m = SourceMapBuilder()
        m.mark(0, 12, 5)
        self.assertEqual(m.build().describe(0), "[12:5]")


class TestFaultLocations(QuinTestCase):
    """A real program's fault points at the construct that caused it."""

    def test_division_by_zero_points_at_the_operator(self):
        e = fault("fn main(): int {\n    let z: int;\n    println(1 / z);\n    return 0;\n}")
        self.assertEqual(e.location, "[3:15]")

    def test_a_bad_index_points_at_the_index_expression(self):
        e = fault("fn main(): int {\n    let a: int[3];\n    let i: int = 9;\n"
                  "    println(a[i]);\n    return 0;\n}")
        self.assertEqual(e.location, "[4:14]")

    def test_reading_and_writing_a_bad_index_agree(self):
        # These lower through different codegen paths, and pointing at
        # different places for the same mistake would be its own puzzle.
        read = fault("fn main(): int {\n    let a: int[3];\n    let i: int = 9;\n"
                     "    println(a[i]);\n    return 0;\n}")
        write = fault("fn main(): int {\n    let a: int[3];\n    let i: int = 9;\n"
                      "    a[i] = 1;\n    return 0;\n}")
        self.assertEqual(read.location.split(":")[0], "[4")
        self.assertEqual(write.location.split(":")[0], "[4")

    def test_a_null_field_read_points_at_the_access(self):
        e = fault("struct N { v: int }\nfn main(): int {\n    let n: N;\n"
                  "    println(n.v);\n    return 0;\n}")
        self.assertEqual(e.location, "[4:15]")

    def test_float_division_by_zero_is_located_too(self):
        e = fault("fn main(): int {\n    let z: float;\n    println(1.0 / z);\n    return 0;\n}")
        self.assertEqual(e.location, "[3:17]")

    def test_the_location_is_on_the_message(self):
        e = fault("fn main(): int {\n    let z: int;\n    return 1 / z;\n}")
        self.assertIn("[3:14]", str(e))
        self.assertIn("Division by zero", str(e),
                      "the original message must survive decoration")

    def test_a_fault_on_a_later_line_is_not_attributed_to_the_first(self):
        # The regression a marker table exists to prevent.
        e = fault(
            """
            fn main(): int {
                let a: int = 1;
                let b: int = 2;
                let z: int;
                println(a + b);
                println(a / z);
                return 0;
            }
            """
        )
        # Line 1 is the blank one the triple-quoted string opens with.
        self.assertEqual(e.location, "[7:27]")


class TestBacktrace(QuinTestCase):
    def test_frames_are_innermost_first(self):
        e = fault(
            """
            fn inner(n: int): int { let z: int; return n / z; }
            fn outer(n: int): int { return inner(n); }
            fn main(): int { println(outer(1)); return 0; }
            """
        )
        text = str(e)
        self.assertIn("in inner:", text)
        order = [text.index(f"at {name}") for name in ("inner", "outer", "main")]
        self.assertEqual(order, sorted(order), "innermost frame must come first")

    def test_every_frame_is_listed(self):
        e = fault(
            """
            fn a(): int { let z: int; return 1 / z; }
            fn b(): int { return a(); }
            fn c(): int { return b(); }
            fn main(): int { println(c()); return 0; }
            """
        )
        self.assertEqual(len(e.frames), 4)

    def test_a_single_frame_prints_no_trace(self):
        # main is already named in the header; repeating it is noise.
        e = fault("fn main(): int { let z: int; return 1 / z; }")
        self.assertEqual(len(e.frames), 1)
        self.assertNotIn("  at ", str(e))

    def test_recursion_shows_each_activation(self):
        e = fault(
            """
            fn down(n: int): int {
                if (n == 0) { let z: int; return 1 / z; }
                return down(n - 1);
            }
            fn main(): int { println(down(3)); return 0; }
            """
        )
        self.assertEqual(len(e.frames), 5, "four activations of down, plus main")
        self.assertEqual(str(e).count("at down"), 4)

    def test_caller_lines_point_at_the_call(self):
        e = fault(
            """
            fn inner(): int { let z: int; return 1 / z; }
            fn main(): int {
                println(1);
                println(inner());
                return 0;
            }
            """
        )
        # main's frame resumes after its CALL, so the line reported for main
        # must be the call site and not the statement after it.
        self.assertIn("at main  (line 5)", str(e))

    def test_a_panic_carries_a_location(self):
        e = fault(
            """
            fn check(ok: bool): int {
                if (!ok) { panic("not ok"); }
                return 1;
            }
            fn main(): int { println(check(false)); return 0; }
            """
        )
        self.assertIn("not ok", str(e))
        self.assertIn("in check", str(e))


class TestCrossFileBacktrace(QuinTestCase):
    """A trace through std/ is unreadable without file names: line 30 could be
    any of half a dozen files."""

    SRC = ('include "std/math.ql";\n'
           "fn main(): int {\n    println(clamp(1, 9, 2));\n    return 0;\n}\n")

    def test_the_file_is_named_when_the_trace_spans_files(self):
        e = fault(self.SRC)
        self.assertIn("std/math.ql", str(e))

    def test_the_file_is_omitted_for_a_single_file_program(self):
        e = fault(
            """
            fn inner(): int { let z: int; return 1 / z; }
            fn main(): int { println(inner()); return 0; }
            """
        )
        self.assertNotIn(".ql", str(e),
                         "naming one file on every line is noise")
        self.assertIn("(line ", str(e))

    def test_each_function_knows_its_file(self):
        program = compile_source(self.SRC)
        by_name = {f.name: f for f in program.functions}
        self.assertTrue(by_name["clamp"].source_file.endswith("math.ql"))
        self.assertTrue(by_name["main"].source_file.endswith("main.ql"))


class TestLocalNameTable(QuinTestCase):
    """Slot -> name, which is what lets a debugger print a variable."""

    SRC = """
    fn f(n: int, x: float, s: str): int {
        let arr: int[3];
        let flag: bool;
        return n;
    }
    fn main(): int { return f(1, 2.0, "a"); }
    """

    def frame(self):
        program = compile_source(self.SRC)
        return next(f for f in program.functions if f.name == "f")

    def test_every_slot_is_named(self):
        names = [li.name for li in self.frame().locals_]
        self.assertEqual(names, ["n", "x", "s", "arr", "flag"])

    def test_slots_account_for_width(self):
        by_name = {li.name: li for li in self.frame().locals_}
        self.assertEqual(by_name["n"].slot, 0)
        self.assertEqual(by_name["x"].slot, 1)
        self.assertEqual(by_name["x"].words, 2, "a float is two slots")
        self.assertEqual(by_name["s"].slot, 3, "so the next slot is 3, not 2")
        self.assertEqual(by_name["arr"].words, 3)
        self.assertEqual(by_name["flag"].slot, 7)

    def test_parameters_are_flagged_and_lead_the_frame(self):
        flags = [li.is_param for li in self.frame().locals_]
        self.assertEqual(flags, [True, True, True, False, False])

    def test_types_are_recorded(self):
        by_name = {li.name: li for li in self.frame().locals_}
        self.assertEqual(by_name["x"].type_name, "float")
        self.assertEqual(by_name["arr"].type_name, "int[3]")

    def test_a_shadowed_name_appears_twice_with_distinct_slots(self):
        program = compile_source(
            "fn main(): int { let x: int = 1; if (true) { let x: int = 2; } return x; }"
        )
        main = next(f for f in program.functions if f.name == "main")
        xs = [li for li in main.locals_ if li.name == "x"]
        self.assertEqual(len(xs), 2)
        self.assertNotEqual(xs[0].slot, xs[1].slot)


class TestCompiledProgram(QuinTestCase):
    """generate() returns a named record; the source map is one of its fields."""

    def test_the_tables_are_reachable_by_name(self):
        program = compile_source("fn main(): int { return 0; }")
        self.assertTrue(program.code)
        self.assertTrue(program.functions)
        self.assertIsInstance(program.source_map, SourceMap)

    def test_the_map_covers_the_emitted_code(self):
        program = compile_source(
            "fn main(): int {\n    let x: int = 1;\n    println(x);\n    return 0;\n}"
        )
        mapped = [program.source_map.lookup(pc) for pc in range(len(program.code))]
        self.assertTrue(all(pos is not None for pos in mapped),
                        "every instruction should trace back to a line")
        lines = sorted({pos[0] for pos in mapped})
        self.assertEqual(lines, [2, 3, 4])

    def test_the_map_is_far_smaller_than_the_code(self):
        # Markers, not one entry per instruction. If this ratio ever inverts,
        # the position is being re-marked between every instruction.
        program = compile_source(
            "fn main(): int { let a: int = 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8; return a; }"
        )
        self.assertLess(len(program.source_map.pcs), len(program.code))


class TestSourceMapIsOptional(unittest.TestCase):
    """A VM built by hand, as several tests do, still runs."""

    def test_a_vm_without_a_map_reports_the_bare_message(self):
        program = compile_source("fn main(): int { let z: int; return 1 / z; }")
        vm = QuinVM(program.code, program.functions, program.strings, program.structs)
        with self.assertRaises(VMError) as caught:
            vm.run_main()
        self.assertIn("Division by zero", str(caught.exception))
        self.assertEqual(caught.exception.location, "",
                         "no map means no location, not a wrong one")

    def test_the_function_name_is_still_reported(self):
        # It comes from the function table, not the source map.
        program = compile_source("fn main(): int { let z: int; return 1 / z; }")
        vm = QuinVM(program.code, program.functions, program.strings, program.structs)
        with self.assertRaises(VMError) as caught:
            vm.run_main()
        self.assertIn("in main", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
