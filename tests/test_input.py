"""Reading input, and program arguments.

The whole design rests on one convention: `read_line()` returns a line **with
its terminator**, so `""` means end of input and a blank line means `"\\n"`.
Getting that wrong is not a crash but a hang -- a loop that reads until the
empty string stops early on a blank line, or never stops at all -- so most of
what follows pins the boundary between those two cases.

`std/input.ql` turns the convention into an enum, which is the version worth
writing programs against: a rule you must remember becomes a variant you must
account for.

Sources are written with a leading newline for readability, so line 1 is the
blank one the triple-quoted string opens with.
"""

import unittest

from runtime.program_io import CaptureIO, ConsoleIO
from tests.harness import QuinTestCase, compile_source, run_source, vm_for

ECHO = """
fn main(): int {
    while (true) {
        let line: str = read_line();
        if (str_len(line) == 0) { break; }
        print("[");
        print(line);
        println("]");
    }
    return 0;
}
"""


class TestReadLinePrimitive(QuinTestCase):
    def test_a_line_keeps_its_terminator(self):
        self.assertPrintsGiven(ECHO, "[one\n]\n[two\n]", "one\ntwo\n")

    def test_a_blank_line_is_a_newline_not_the_end(self):
        # The distinction the whole convention exists for. If a blank line came
        # back as "", this loop would stop at the first one.
        self.assertPrintsGiven(ECHO, "[a\n]\n[\n]\n[b\n]", "a\n\nb\n")

    def test_the_end_of_input_is_empty(self):
        self.assertPrintsGiven(ECHO, "", "")

    def test_a_final_line_without_a_terminator_still_arrives(self):
        self.assertPrintsGiven(ECHO, "[a\n]\n[b]", "a\nb")

    def test_reading_past_the_end_keeps_returning_empty(self):
        self.assertPrintsGiven(
            """
            fn main(): int {
                let a: str = read_line();
                let b: str = read_line();
                let c: str = read_line();
                println(str_len(a));
                println(str_len(b));
                println(str_len(c));
                return 0;
            }
            """,
            "2\n0\n0", "x\n")

    def test_a_latin1_character_is_one_character(self):
        # A CaptureIO is handed text that is already one character per byte,
        # which is the form a ProgramIO is expected to produce. Turning UTF-8
        # into that form is ConsoleIO's job, covered in TestConsoleReading.
        self.assertPrintsGiven(
            'fn main(): int { println(str_len(read_line())); return 0; }',
            "3", "éé\n")

    def test_a_character_too_wide_for_a_byte_is_refused(self):
        # An arbitrary ProgramIO can hand back anything, so the VM checks
        # rather than trusting the implementation.
        program = compile_source("fn main(): int { println(read_line()); return 0; }")
        from runtime.vm import VMError
        with self.assertRaises(VMError) as caught:
            vm_for(program, CaptureIO("→\n")).run_main()
        self.assertIn("U+2192", str(caught.exception))
        self.assertIn("does not fit in a byte", str(caught.exception))


class TestStdInput(QuinTestCase):
    """std/input.ql, which is the version worth writing programs against."""

    LOOP = """
    include "std/input.ql";
    fn main(): int {
        let n: int = 0;
        while (true) {
            match (next_line()) {
                Input::Line(text) => {
                    n = n + 1;
                    print(n);
                    print(":");
                    println(text);
                }
                Input::End => { break; }
            }
        }
        print("total ");
        println(n);
        return 0;
    }
    """

    def test_each_line_becomes_a_variant(self):
        self.assertPrintsGiven(self.LOOP, "1:a\n2:b\ntotal 2", "a\nb\n")

    def test_the_terminator_is_stripped(self):
        self.assertPrintsGiven(
            'include "std/input.ql";\n'
            "fn main(): int { match (next_line()) { "
            "Input::Line(t) => { println(str_len(t)); } Input::End => {} } return 0; }",
            "3", "abc\n")

    def test_a_blank_line_is_a_line_not_the_end(self):
        self.assertPrintsGiven(self.LOOP, "1:a\n2:\n3:b\ntotal 3", "a\n\nb\n")

    def test_empty_input_ends_immediately(self):
        self.assertPrintsGiven(self.LOOP, "total 0", "")

    def test_carriage_returns_are_stripped_too(self):
        # A file written on Windows should not leave a stray \r on every line.
        self.assertPrintsGiven(
            'include "std/input.ql";\n'
            "fn main(): int { match (next_line()) { "
            "Input::Line(t) => { println(str_len(t)); } Input::End => {} } return 0; }",
            "3", "abc\r\n")

    def test_trailing_spaces_are_kept(self):
        # str_trim_end would eat them; a line's terminator is not its
        # whitespace.
        self.assertPrintsGiven(
            'include "std/input.ql";\n'
            "fn main(): int { match (next_line()) { "
            "Input::Line(t) => { println(str_len(t)); } Input::End => {} } return 0; }",
            "5", "ab   \n")

    def test_it_is_not_in_the_prelude(self):
        # It declares an enum, and an enum name is global once included -- the
        # same reason std/list.ql and std/vec.ql are left out.
        from tests.harness import STD_PATH
        self.assertNotIn("input.ql", (STD_PATH / "prelude.ql").read_text(encoding="utf-8"))


class TestArguments(QuinTestCase):
    COUNT = """
    fn main(): int {
        println(argc());
        for (let i = 0; i < argc(); i = i + 1) { println(argv(i)); }
        return 0;
    }
    """

    def test_arguments_are_reported_in_order(self):
        self.assertPrintsGiven(self.COUNT, "3\na\nb\nc", "", ["a", "b", "c"])

    def test_no_arguments_is_a_count_of_zero(self):
        # Nothing invents an argv(0): the driver supplies the program path, an
        # embedded VM supplies whatever it has.
        self.assertPrintsGiven(self.COUNT, "0", "", [])

    def test_an_index_past_the_end_faults(self):
        self.assertRuntimeError(
            "fn main(): int { println(argv(4)); return 0; }",
            "argv index out of bounds")

    def test_a_negative_index_faults(self):
        self.assertRuntimeError(
            "fn main(): int { println(argv(0 - 1)); return 0; }",
            "argv index out of bounds")

    def test_an_argument_too_wide_for_a_byte_is_refused(self):
        program = compile_source("fn main(): int { println(argv(0)); return 0; }")
        from runtime.vm import VMError
        with self.assertRaises(VMError) as caught:
            vm_for(program, CaptureIO(), ["→"]).run_main()
        self.assertIn("an argument contains U+2192", str(caught.exception))


class TestConsoleReading(unittest.TestCase):
    """ConsoleIO reads bytes, which is what makes input byte-oriented."""

    class FakeStdin:
        def __init__(self, data: bytes):
            import io
            self.buffer = io.BytesIO(data)

        def readline(self):
            raise AssertionError("the binary buffer should be preferred")

    def test_it_reads_from_the_binary_buffer(self):
        import sys
        from unittest.mock import patch
        with patch.object(sys, "stdin", self.FakeStdin(b"caf\xc3\xa9\n")):
            line = ConsoleIO().read_line()
        # Four bytes of text plus the newline: the UTF-8 e-acute is two
        # characters here, because a QuinLang character is a byte.
        self.assertEqual(line, "cafÃ©\n")
        self.assertEqual(len(line), 6)

    def test_end_of_input_is_empty(self):
        import sys
        from unittest.mock import patch
        with patch.object(sys, "stdin", self.FakeStdin(b"")):
            self.assertEqual(ConsoleIO().read_line(), "")


if __name__ == "__main__":
    unittest.main()
