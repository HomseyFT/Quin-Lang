"""Where a program's output goes.

The VM used to call print() directly. Everything here is about the consequence
of not doing that: output has a destination, the caller picks it, and a program
run under something that owns stdout -- a debug adapter speaking a protocol on
it, an editor with a console widget -- cannot corrupt it.

The load-bearing test is `test_nothing_reaches_stdout`. The rest describe what
the text looks like when it arrives.
"""

import io as _io
import unittest
from contextlib import redirect_stdout

from runtime.program_io import CaptureIO, ConsoleIO
from tests.harness import QuinTestCase, compile_source, vm_for


def output(source: str) -> str:
    """Run a program with its output captured rather than printed."""
    program = compile_source(source)
    sink = CaptureIO()
    vm_for(program, sink).run_main()
    return sink.text


class TestRouting(QuinTestCase):
    def test_output_reaches_the_supplied_sink(self):
        self.assertEqual(output('fn main(): int { println("hi"); return 0; }'), "hi\n")

    def test_nothing_reaches_stdout(self):
        # The reason this exists. A debug adapter speaks its protocol on
        # stdout; one println from the debugged program would corrupt it.
        program = compile_source(
            'fn main(): int { println("secret"); print(42); return 0; }')
        sink = CaptureIO()
        real = _io.StringIO()
        with redirect_stdout(real):
            vm_for(program, sink).run_main()
        self.assertEqual(real.getvalue(), "", "the VM wrote to the process's stdout")
        self.assertEqual(sink.text, "secret\n42")

    def test_the_default_is_the_console(self):
        # A plain run is unchanged, which is why the whole existing suite still
        # reads program output through redirect_stdout.
        program = compile_source('fn main(): int { println("plain"); return 0; }')
        vm = vm_for(program)
        self.assertIsInstance(vm.io, ConsoleIO)
        buf = _io.StringIO()
        with redirect_stdout(buf):
            vm.run_main()
        self.assertEqual(buf.getvalue(), "plain\n")

    def test_the_console_resolves_stdout_per_call(self):
        # Captured at construction, redirect_stdout would stop working and the
        # test suite would go quiet without failing.
        console = ConsoleIO()
        buf = _io.StringIO()
        with redirect_stdout(buf):
            console.write("into the redirect")
        self.assertEqual(buf.getvalue(), "into the redirect")


class TestFormatting(QuinTestCase):
    def test_print_adds_nothing(self):
        self.assertEqual(output('fn main(): int { print("a"); print("b"); return 0; }'),
                         "ab")

    def test_println_adds_one_newline(self):
        self.assertEqual(output('fn main(): int { println("a"); println("b"); return 0; }'),
                         "a\nb\n")

    def test_every_printable_type_routes_through(self):
        # One test per opcode would be six near-identical tests; what matters
        # is that none of the six was missed.
        self.assertEqual(
            output("""
            fn main(): int {
                println(42);
                println(0 - 7);
                println("text");
                println(1.5);
                println(true);
                print(9);
                return 0;
            }
            """),
            "42\n-7\ntext\n1.5\ntrue\n9")

    def test_the_newline_travels_in_the_text(self):
        # println is print plus "\n" in the same write, so a sink never has to
        # know which one it is serving.
        program = compile_source('fn main(): int { println("x"); return 0; }')
        sink = CaptureIO()
        vm_for(program, sink).run_main()
        self.assertEqual(sink.chunks, ["x\n"])


class TestSeparationFromToolOutput(QuinTestCase):
    def test_a_runtime_error_is_not_program_output(self):
        # The VM reporting a fault is the tool talking, not the program. It
        # travels as an exception and the driver puts it on stderr.
        from runtime.vm import VMError
        program = compile_source("fn main(): int { let z: int; return 1 / z; }")
        sink = CaptureIO()
        with self.assertRaises(VMError):
            vm_for(program, sink).run_main()
        self.assertEqual(sink.text, "")

    def test_output_before_a_fault_is_kept(self):
        from runtime.vm import VMError
        program = compile_source(
            'fn main(): int { println("before"); let z: int; return 1 / z; }')
        sink = CaptureIO()
        with self.assertRaises(VMError):
            vm_for(program, sink).run_main()
        self.assertEqual(sink.text, "before\n")


if __name__ == "__main__":
    unittest.main()
