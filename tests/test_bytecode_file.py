"""The `.qlc` bytecode file.

Two things are worth testing about a file format, and they pull in opposite
directions. A good file must round-trip *exactly* -- every table, or the
program that comes back is a different one. A bad file must be **refused**,
because the failure mode of a loader that shrugs is a program that runs and
computes the wrong answer, which is the whole reason the opcode numbers are
written out by hand.

So: every table is compared field by field, and every way a file can be wrong
is asserted to raise rather than to load.
"""

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from compiler.bytecode import Instruction, OpCode, SourceMap
from compiler.pipeline import program_for
from compiler.serialize import (
    FORMAT_VERSION,
    HAS_DEBUG_INFO,
    MAGIC,
    BytecodeError,
    dumps,
    loads,
    read_program,
    write_program,
)
from tests.harness import EXAMPLES_PATH, REPO_ROOT, QuinTestCase, compile_source

EVERYTHING = """
struct Point { x: int, y: int, tag: str }
enum Shape { Circle(int), Blank }

fn scale(p: Point, k: int): int {
    let sum: int = (p.x + p.y) * k;
    return sum;
}

fn main(): int {
    let p: Point = Point{x: 3, y: -4, tag: "origin"};
    let f: float = 1.75;
    let arr: int[3];
    arr[1] = 7;
    let s: Shape = Shape::Circle(9);
    println(scale(p, 2));
    println(f);
    return 0;
}
"""


class RoundTripTestCase(QuinTestCase):
    def round_trip(self, source: str = EVERYTHING, debug: bool = True):
        program = compile_source(source)
        return program, loads(dumps(program, debug))


class TestRoundTrip(RoundTripTestCase):
    def test_the_code_comes_back_instruction_for_instruction(self):
        program, back = self.round_trip()
        self.assertEqual(back.code, program.code)

    def test_operands_survive_the_full_32_bits(self):
        # A float literal is a bit pattern, and the widest operand there is.
        program, back = self.round_trip()
        floats = [i for i in program.code if i.op is OpCode.PUSH_FLOAT]
        self.assertTrue(floats)
        self.assertEqual([i.arg for i in back.code if i.op is OpCode.PUSH_FLOAT],
                         [i.arg for i in floats])

    def test_function_values_survive_the_round_trip(self):
        # Nothing in the format needed a version bump for these: an opcode is
        # an opcode, and a type name was already a string. This is what proves
        # it.
        program, back = self.round_trip(
            "fn add(a: int, b: int): int { return a + b; }\n"
            "fn main(): int { let f: fn(int, int): int = add;"
            " println(f(1, 2)); return 0; }")
        self.assertIn(OpCode.CALL_INDIRECT, [i.op for i in back.code])
        self.assertEqual(back.code, program.code)
        types = {l.name: l.type_name
                 for f in back.functions if f.name == "main"
                 for l in f.locals_}
        self.assertEqual(types["f"], "fn(int,int):int")

    def test_the_string_table_keeps_its_ids(self):
        # LOAD_STR names a literal by id, so position is not enough.
        program, back = self.round_trip()
        self.assertEqual(back.strings, program.strings)

    def test_struct_layouts_come_back_whole(self):
        # Order is the type id an object's header carries; ref_offsets is what
        # the collector traces. Either one wrong is a corrupted heap.
        program, back = self.round_trip()
        self.assertEqual(back.structs, program.structs)

    def test_the_function_table_comes_back_whole(self):
        program, back = self.round_trip()
        self.assertEqual(back.functions, program.functions)

    def test_the_source_map_comes_back_whole(self):
        program, back = self.round_trip()
        self.assertEqual(back.source_map, program.source_map)

    def test_a_program_with_no_strings_or_structs_round_trips(self):
        program, back = self.round_trip("fn main(): int { return 1 + 2; }")
        self.assertEqual(back.code, program.code)
        self.assertEqual(back.strings, program.strings)

    def test_every_example_round_trips(self):
        for path in sorted(EXAMPLES_PATH.glob("*.ql")):
            with self.subTest(example=path.name):
                program, _ = program_for(path)
                back = loads(dumps(program))
                self.assertEqual(back.code, program.code)
                self.assertEqual(back.functions, program.functions)
                self.assertEqual(back.structs, program.structs)
                self.assertEqual(back.strings, program.strings)
                self.assertEqual(back.source_map, program.source_map)

    def test_a_high_byte_string_literal_survives(self):
        # A str holds one byte per character. UTF-8 widens those on disk, and
        # has to hand back exactly what went in.
        program, back = self.round_trip(
            'fn main(): int { println("café ÿ"); return 0; }')
        self.assertEqual(back.strings, program.strings)
        self.assertIn("café ÿ", back.strings.values())


class TestStripping(RoundTripTestCase):
    def test_the_running_tables_are_all_still_there(self):
        program, back = self.round_trip(debug=False)
        self.assertEqual(back.code, program.code)
        self.assertEqual(back.strings, program.strings)
        self.assertEqual(back.structs, program.structs)

    def test_the_debug_tables_are_gone(self):
        _, back = self.round_trip(debug=False)
        self.assertEqual(back.source_map.pcs, ())
        self.assertTrue(all(fn.locals_ == () for fn in back.functions))
        self.assertTrue(all(fn.source_file == "" for fn in back.functions))

    def test_function_names_stay(self):
        # A backtrace naming no functions is not worth the bytes.
        _, back = self.round_trip(debug=False)
        self.assertIn("scale", [fn.name for fn in back.functions])

    def test_the_call_shape_stays(self):
        # CALL scatters arguments by param_words, so stripping these would not
        # save space, it would break the program.
        program, back = self.round_trip(debug=False)
        self.assertEqual([fn.param_words for fn in back.functions],
                         [fn.param_words for fn in program.functions])
        self.assertEqual([fn.ref_slots for fn in back.functions],
                         [fn.ref_slots for fn in program.functions])

    def test_it_is_smaller(self):
        program = compile_source(EVERYTHING)
        self.assertLess(len(dumps(program, debug=False)), len(dumps(program)))

    def test_the_header_says_which_it_is(self):
        program = compile_source(EVERYTHING)
        self.assertEqual(dumps(program)[6] & HAS_DEBUG_INFO, HAS_DEBUG_INFO)
        self.assertEqual(dumps(program, debug=False)[6] & HAS_DEBUG_INFO, 0)


class TestRefusal(RoundTripTestCase):
    def data(self, debug: bool = True) -> bytearray:
        return bytearray(dumps(compile_source(EVERYTHING), debug))

    def test_something_that_is_not_bytecode(self):
        with self.assertRaises(BytecodeError) as caught:
            loads(b"fn main(): int { return 0; }")
        self.assertIn("not a QuinLang bytecode file", str(caught.exception))

    def test_an_empty_file(self):
        with self.assertRaises(BytecodeError):
            loads(b"")

    def test_another_format_version(self):
        # The whole contract: a .qlc is a build artifact, so a file from
        # another build is refused rather than guessed at.
        data = self.data()
        data[4] = FORMAT_VERSION + 1
        with self.assertRaises(BytecodeError) as caught:
            loads(bytes(data))
        self.assertIn("recompile from source", str(caught.exception))

    def test_a_truncated_file(self):
        data = self.data()
        with self.assertRaises(BytecodeError) as caught:
            loads(bytes(data[:len(data) // 2]))
        self.assertIn("ends in the middle", str(caught.exception))

    def test_trailing_bytes(self):
        # Silent extra data is how two versions of a format start disagreeing
        # about where a section ends.
        with self.assertRaises(BytecodeError) as caught:
            loads(self.data() + b"\x00")
        self.assertIn("trailing bytes", str(caught.exception))

    def test_an_opcode_this_build_does_not_have(self):
        # The first instruction's opcode field is found by changing it and
        # seeing which byte moved, rather than by counting the tables in front
        # of it -- a count this test would then have to keep in step.
        program = compile_source("fn main(): int { return 0; }")
        first = program.code[0]
        baseline = dumps(program)
        program.code[0] = Instruction(OpCode.POP)
        altered = dumps(program)
        program.code[0] = first
        offset = next(i for i, (a, b) in enumerate(zip(baseline, altered))
                      if a != b)

        data = bytearray(baseline)
        data[offset] = max(op.value for op in OpCode) + 1
        with self.assertRaises(BytecodeError) as caught:
            loads(bytes(data))
        self.assertIn("different compiler", str(caught.exception))

    def test_an_operand_wider_than_the_format(self):
        program = compile_source("fn main(): int { return 0; }")
        program.code[0] = Instruction(OpCode.PUSH_INT, 1 << 32)
        with self.assertRaises(BytecodeError) as caught:
            dumps(program)
        self.assertIn("outside the 32 bits", str(caught.exception))


class TestRunningLoadedPrograms(QuinTestCase):
    """The point of the format: the program that comes back is the same one."""

    def emit(self, source: str, *flags):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ql = Path(directory.name) / "main.ql"
        ql.write_text(source, encoding="utf-8")
        qlc = Path(directory.name) / "main.qlc"
        # Flags go before the source: everything after it is the program's own
        # argv, which is what lets a program take a --flag of its own.
        result = self.run_driver("-o", str(qlc), *flags, str(ql))
        self.assertEqual(result.returncode, 0, result.stderr)
        return str(ql), str(qlc)

    def run_driver(self, *args):
        return subprocess.run([sys.executable, "-m", "compiler.driver_vm", *args],
                              cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=60)

    def test_the_output_is_identical(self):
        source = EVERYTHING
        ql, qlc = self.emit(source)
        self.assertEqual(self.run_driver(qlc).stdout, self.run_driver(ql).stdout)

    def test_a_stripped_program_runs_the_same(self):
        _, qlc = self.emit(EVERYTHING, "--strip")
        ql, _ = self.emit(EVERYTHING)
        self.assertEqual(self.run_driver(qlc).stdout, self.run_driver(ql).stdout)

    def test_the_exit_code_survives(self):
        _, qlc = self.emit("fn main(): int { return 7; }")
        self.assertEqual(self.run_driver(qlc).returncode, 7)

    def test_arguments_still_reach_the_program(self):
        _, qlc = self.emit("""
        fn main(): int {
            for (let i = 0; i < argc(); i = i + 1) { println(argv(i)); }
            return 0;
        }
        """)
        result = self.run_driver(qlc, "alpha", "beta")
        self.assertIn("alpha\nbeta\n", result.stdout)
        self.assertIn(".qlc", result.stdout, "argv(0) is what was run")

    def test_a_runtime_error_keeps_its_position(self):
        _, qlc = self.emit("fn main(): int { let z: int = 0; return 1 / z; }")
        result = self.run_driver(qlc)
        self.assertEqual(result.returncode, 3)
        self.assertRegex(result.stderr, r"\[\d+:\d+\]")

    def test_a_stripped_runtime_error_keeps_its_message(self):
        # The trade --strip makes, stated: the reason survives, the position
        # does not.
        _, qlc = self.emit("fn main(): int { let z: int = 0; return 1 / z; }",
                           "--strip")
        result = self.run_driver(qlc)
        self.assertEqual(result.returncode, 3)
        self.assertIn("Division by zero", result.stderr)
        self.assertNotIn("[1:", result.stderr)

    def test_debugging_a_stripped_program_is_refused(self):
        _, qlc = self.emit(EVERYTHING, "--strip")
        result = self.run_driver("--debug", qlc)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no debug info", result.stderr)

    def test_a_binary_file_that_is_not_bytecode_is_reported(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "junk.qlc"
        path.write_bytes(b"\x00\x8f\xff\xfe not text")
        result = self.run_driver(str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Not a text file", result.stderr)


class TestDispatch(QuinTestCase):
    def test_a_file_is_recognised_by_its_bytes_not_its_name(self):
        # A .qlc named .ql would otherwise be handed to the lexer, which would
        # report a syntax error in binary data.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "misnamed.ql"
        write_program(compile_source(EVERYTHING), path)
        program, warnings = program_for(path)
        self.assertEqual(program.functions[0].name,
                         compile_source(EVERYTHING).functions[0].name)
        self.assertEqual(warnings, [], "they were reported when it compiled")

    def test_the_magic_is_what_it_claims(self):
        self.assertTrue(dumps(compile_source(EVERYTHING)).startswith(MAGIC))

    def test_read_program_reports_a_missing_file(self):
        with self.assertRaises(BytecodeError) as caught:
            read_program(Path("/nowhere/absent.qlc"))
        self.assertIn("cannot read", str(caught.exception))


class TestSourceMapEdges(QuinTestCase):
    def test_an_empty_source_map_round_trips(self):
        # Nothing produces one today, but the format has to encode a table
        # with no rows rather than a table it forgot to write.
        program = replace(compile_source("fn main(): int { return 0; }"),
                          source_map=SourceMap())
        self.assertEqual(loads(dumps(program)).source_map, SourceMap())


if __name__ == "__main__":
    unittest.main()
