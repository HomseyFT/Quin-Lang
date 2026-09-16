"""File I/O: the builtins, their error convention, and the Result wrapper.

Nothing here touches a disk. `CaptureIO` carries an in-memory filesystem, which
is the point of routing file access through `ProgramIO` at all -- where a
program's files come from is the caller's choice, so a test simply supplies a
different answer. A test that wants a file to already exist puts it in the dict;
a test that writes one reads it back out of the same dict.

The convention under test is that a file builtin is **total**: a failure sets
what `file_error()` reports and the program keeps running. Getting that wrong is
not a crash but a silence -- a read that returns "" for both an empty file and a
missing one -- so most of what follows pins that boundary.
"""

import unittest

from runtime.program_io import CaptureIO
from runtime.vm import VMError
from tests.harness import QuinTestCase, compile_source, vm_for


def run(source: str, files=None):
    """Run a program against an in-memory filesystem, returning (output, io)."""
    io = CaptureIO(files=files or {})
    vm_for(compile_source(source), io).run_main()
    return io.text, io


def main_with(body: str, includes=()) -> str:
    head = "".join(f'include "std/{name}.ql";\n' for name in includes)
    return f"{head}fn main(): int {{\n{body}\n    return 0;\n}}\n"


class TestReading(QuinTestCase):
    def test_a_file_reads_back(self):
        out, _ = run(main_with('print(file_read("a.txt"));'),
                     {"a.txt": b"hello\n"})
        self.assertEqual(out, "hello\n")

    def test_bytes_survive_unchanged(self):
        # A str is one byte per character, so a file of arbitrary bytes comes
        # back as exactly those bytes rather than through a decode.
        out, _ = run(main_with(
            'let s: str = file_read("b.bin");\n'
            'println(str_len(s)); println(str_char_at(s, 0)); '
            'println(str_char_at(s, 1));'),
            {"b.bin": bytes([0, 255])})
        self.assertEqual(out, "2\n0\n255\n")

    def test_an_empty_file_is_not_an_error(self):
        out, _ = run(main_with(
            'println(str_len(file_read("e.txt"))); println(str_len(file_error()));'),
            {"e.txt": b""})
        self.assertEqual(out, "0\n0\n")

    def test_a_missing_file_reports_instead_of_faulting(self):
        out, _ = run(main_with(
            'println(str_len(file_read("gone.txt")));\n'
            'println(str_len(file_error()) > 0);'))
        self.assertEqual(out, "0\ntrue\n")

    def test_reading_bytes(self):
        out, _ = run(main_with(
            'let b: Array<int> = file_read_bytes("b.bin");\n'
            'println(array_len(b)); println(b[0]); println(b[2]);'),
            {"b.bin": bytes([1, 2, 3])})
        self.assertEqual(out, "3\n1\n3\n")

    def test_reading_bytes_from_a_missing_file_is_empty_not_a_fault(self):
        out, _ = run(main_with(
            'println(array_len(file_read_bytes("gone.bin")));\n'
            'println(str_len(file_error()) > 0);'))
        self.assertEqual(out, "0\ntrue\n")


class TestWriting(QuinTestCase):
    def test_write_then_read(self):
        out, io = run(main_with(
            'println(file_write("out.txt", "written"));\n'
            'print(file_read("out.txt"));'))
        self.assertEqual(out, "true\nwritten")
        self.assertEqual(io.files["out.txt"], b"written")

    def test_write_replaces_and_append_extends(self):
        _, io = run(main_with(
            'file_write("x.txt", "one");\n'
            'file_write("x.txt", "two");\n'
            'file_append("x.txt", "three");'))
        self.assertEqual(io.files["x.txt"], b"twothree")

    def test_appending_to_a_missing_file_creates_it(self):
        _, io = run(main_with('file_append("new.txt", "first");'))
        self.assertEqual(io.files["new.txt"], b"first")

    def test_writing_bytes(self):
        _, io = run(main_with(
            "let b: Array<int> = array_new(3);\n"
            "b[0] = 72; b[1] = 105; b[2] = 33;\n"
            'println(file_write_bytes("hi.bin", b));'))
        self.assertEqual(io.files["hi.bin"], b"Hi!")

    def test_a_byte_out_of_range_is_refused(self):
        # An int array holds anything an int does; a file holds bytes.
        with self.assertRaises(VMError) as cm:
            run(main_with(
                "let b: Array<int> = array_new(1);\n"
                "b[0] = 300;\n"
                'file_write_bytes("bad.bin", b);'))
        self.assertIn("outside the 0..255", str(cm.exception))

    def test_a_write_failure_is_reported(self):
        class ReadOnly(CaptureIO):
            def write_file(self, path, data, append):
                raise PermissionError("read-only filesystem")

        io = ReadOnly()
        vm_for(compile_source(main_with(
            'println(file_write("x.txt", "nope"));\n'
            'println(file_error());')), io).run_main()
        self.assertEqual(io.text, "false\nread-only filesystem\n")


class TestExistsAndDelete(QuinTestCase):
    def test_exists(self):
        out, _ = run(main_with(
            'println(file_exists("there.txt")); println(file_exists("not.txt"));'),
            {"there.txt": b""})
        self.assertEqual(out, "true\nfalse\n")

    def test_delete(self):
        out, io = run(main_with(
            'println(file_delete("go.txt")); println(file_exists("go.txt"));'),
            {"go.txt": b"x"})
        self.assertEqual(out, "true\nfalse\n")
        self.assertNotIn("go.txt", io.files)

    def test_deleting_what_is_not_there_reports(self):
        out, _ = run(main_with(
            'println(file_delete("ghost.txt")); println(str_len(file_error()) > 0);'))
        self.assertEqual(out, "false\ntrue\n")


class TestTheErrorConvention(QuinTestCase):
    def test_no_error_before_anything_happens(self):
        out, _ = run(main_with("println(str_len(file_error()));"))
        self.assertEqual(out, "0\n")

    def test_a_success_clears_the_previous_failure(self):
        # The hazard of a last-error convention is reading a stale one as a
        # fresh failure, so every operation clears it before trying.
        out, _ = run(main_with(
            'file_read("gone.txt");\n'
            'println(str_len(file_error()) > 0);\n'
            'file_write("ok.txt", "x");\n'
            'println(str_len(file_error()));'))
        self.assertEqual(out, "true\n0\n")

    def test_exists_clears_it_too(self):
        out, _ = run(main_with(
            'file_read("gone.txt");\n'
            'file_exists("also-gone.txt");\n'
            'println(str_len(file_error()));'))
        self.assertEqual(out, "0\n")

    def test_a_failure_does_not_stop_the_program(self):
        out, _ = run(main_with(
            'file_read("a.txt"); file_read("b.txt"); file_delete("c.txt");\n'
            'println("still running");'))
        self.assertEqual(out, "still running\n")


class TestTheStdWrapper(QuinTestCase):
    def test_a_read_that_works(self):
        out, _ = run(main_with(
            'match (fs_read("a.txt")) {\n'
            '    Result::Ok(text) => { print(text); }\n'
            '    Result::Err(why) => { println("err"); }\n'
            '}', ["fs"]), {"a.txt": b"content"})
        self.assertEqual(out, "content")

    def test_a_read_that_does_not(self):
        out, _ = run(main_with(
            'match (fs_read("gone.txt")) {\n'
            '    Result::Ok(text) => { print(text); }\n'
            '    Result::Err(why) => { println(str_len(why) > 0); }\n'
            '}', ["fs"]))
        self.assertEqual(out, "true\n")

    def test_an_empty_file_is_ok_not_err(self):
        # The case the raw convention cannot distinguish on its own, and the
        # reason the wrapper asks file_error() rather than checking for "".
        out, _ = run(main_with(
            "println(result_is_ok(fs_read(\"e.txt\")));", ["fs"]),
            {"e.txt": b""})
        self.assertEqual(out, "true\n")

    def test_write_reports_how_much(self):
        out, _ = run(main_with(
            'println(result_unwrap(fs_write("o.txt", "12345")));', ["fs"]))
        self.assertEqual(out, "5\n")

    def test_read_or_falls_back(self):
        out, _ = run(main_with(
            'println(fs_read_or("gone.txt", "(none)"));\n'
            'println(fs_read_or("there.txt", "(none)"));', ["fs"]),
            {"there.txt": b"real"})
        self.assertEqual(out, "(none)\nreal\n")

    def test_bytes_through_the_wrapper(self):
        out, _ = run(main_with(
            'println(array_len(result_unwrap(fs_read_bytes("b.bin"))));', ["fs"]),
            {"b.bin": bytes([1, 2, 3, 4])})
        self.assertEqual(out, "4\n")

    def test_exists_is_not_a_result(self):
        out, _ = run(main_with(
            'println(fs_exists("a.txt")); println(fs_exists("b.txt"));', ["fs"]),
            {"a.txt": b""})
        self.assertEqual(out, "true\nfalse\n")


class TestTheIOSeam(QuinTestCase):
    def test_an_implementation_may_refuse_outright(self):
        # A sandbox is a legitimate ProgramIO: refusing everything is reported
        # like any other failure, and the program still runs.
        class NoFiles(CaptureIO):
            def read_file(self, path):
                raise PermissionError("filesystem access is not permitted")

        io = NoFiles()
        vm_for(compile_source(main_with(
            'file_read("anything");\n'
            'println(file_error());')), io).run_main()
        self.assertEqual(io.text, "filesystem access is not permitted\n")

    def test_text_wider_than_a_byte_is_refused(self):
        # Any ProgramIO can hand back anything; the VM checks rather than
        # trusting it, exactly as it does for read_line and argv.
        class WideIO(CaptureIO):
            def read_file(self, path):
                return "→"

        with self.assertRaises(VMError) as cm:
            vm_for(compile_source(main_with('file_read("x");')), WideIO()).run_main()
        self.assertIn("does not fit in a byte", str(cm.exception))

    def test_something_that_is_not_bytes_is_refused(self):
        class WrongIO(CaptureIO):
            def read_file(self, path):
                return 42

        with self.assertRaises(VMError) as cm:
            vm_for(compile_source(main_with('file_read("x");')), WrongIO()).run_main()
        self.assertIn("not bytes", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
