"""Helpers for compiling and running QuinLang source inside tests.

Tests describe programs as strings and assert on what they print or which
error they raise, so they exercise the whole pipeline (lex, parse, resolve,
type-check, lower, interpret) rather than any single pass in isolation.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from compiler.resolver import ImportResolver, ResolveError
from compiler.sema import SemanticAnalyzer, SemanticError
from compiler.codegen_vm import CodeGenVM, CodegenError
from runtime.vm import QuinVM, VMError

REPO_ROOT = Path(__file__).resolve().parent.parent
STD_PATH = REPO_ROOT / "std"
EXAMPLES_PATH = REPO_ROOT / "examples"
GOLDEN_PATH = Path(__file__).resolve().parent / "golden"

# Every way the front end can reject a program. Lexer and parser errors reach
# callers wrapped in ResolveError, because the resolver is what reads files.
COMPILE_ERRORS = (ResolveError, SemanticError, CodegenError)


@dataclass
class Run:
    """The observable result of running a program to completion."""
    stdout: str
    exit_value: int


def compile_file(path: Path):
    """Compile a .ql file to a CompiledProgram."""
    resolved = ImportResolver(STD_PATH).resolve(Path(path))
    ctx = SemanticAnalyzer().analyze(resolved.program)
    return CodeGenVM().generate(resolved.program, ctx)


def compile_source(source: str):
    """Compile source text by staging it as a file, so includes resolve."""
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        return compile_file(entry)


def warnings_for(source: str) -> list:
    """The compile-time warnings a program produces, as strings.

    Warnings live on the semantic Context, so tests can read them directly
    rather than capturing the driver's stderr.
    """
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        resolved = ImportResolver(STD_PATH).resolve(entry)
        ctx = SemanticAnalyzer().analyze(resolved.program)
        return [str(w) for w in ctx.warnings]


def _run(program) -> Run:
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_value = vm_for(program).run_main()
    return Run(buf.getvalue(), exit_value)


def vm_for(program, io=None) -> QuinVM:
    """A VM loaded with a CompiledProgram, source map included, so a runtime
    error in a test reports the same location a user would see.

    `io` sends the program's output somewhere other than stdout, which is what
    anything embedding the VM does.
    """
    return QuinVM(program.code, program.functions, program.strings,
                  program.structs, program.source_map, io)


def run_file(path: Path) -> Run:
    return _run(compile_file(path))


def run_source(source: str) -> Run:
    return _run(compile_source(source))


class QuinTestCase(unittest.TestCase):
    """Assertions phrased in terms of what a QuinLang program does."""

    def assertOutput(self, source: str, expected: str, msg: Optional[str] = None):
        """Assert a program runs and prints exactly `expected`.

        `expected` is compared after stripping leading/trailing blank lines, so
        tests can use triple-quoted strings without fighting indentation.
        """
        actual = run_source(source).stdout
        self.assertEqual(actual.strip("\n"), expected.strip("\n"), msg)

    def assertPrints(self, source: str, *lines: str):
        """Assert a program prints exactly these lines, in order."""
        self.assertOutput(source, "\n".join(lines))

    def assertExprPrints(self, expr: str, expected: str):
        """Assert `println(<expr>);` inside a bare main prints `expected`."""
        self.assertOutput(f"fn main(): int {{ println({expr}); return 0; }}", expected)

    def assertCompileError(self, source: str, expected_substring: str) -> str:
        """Assert compilation fails with a message containing `expected_substring`."""
        try:
            compile_source(source)
        except COMPILE_ERRORS as e:
            message = str(e)
            self.assertIn(
                expected_substring, message,
                f"wrong compile error.\n  expected substring: {expected_substring!r}"
                f"\n  actual message:     {message!r}",
            )
            return message
        self.fail(
            f"expected a compile error containing {expected_substring!r}, "
            f"but the program compiled"
        )

    def assertRuntimeError(self, source: str, expected_substring: str) -> str:
        """Assert the program compiles but the VM faults at run time."""
        try:
            run_source(source)
        except VMError as e:
            message = str(e)
            self.assertIn(
                expected_substring, message,
                f"wrong runtime error.\n  expected substring: {expected_substring!r}"
                f"\n  actual message:     {message!r}",
            )
            return message
        self.fail(
            f"expected a runtime error containing {expected_substring!r}, "
            f"but the program ran to completion"
        )

    def assertCompileWarning(self, source: str, expected_substring: str) -> str:
        """Assert a program compiles and warns, with a message containing this.

        Deliberately not named assertWarns: unittest already defines that for
        Python's own warnings, and shadowing it would break every caller.
        """
        found = warnings_for(source)
        self.assertTrue(found, f"expected a warning containing {expected_substring!r}, got none")
        joined = " | ".join(found)
        self.assertIn(expected_substring, joined,
                      f"wrong warning.\n  expected substring: {expected_substring!r}"
                      f"\n  actual: {joined!r}")
        return joined

    def assertNoCompileWarnings(self, source: str):
        found = warnings_for(source)
        self.assertEqual(found, [], f"expected no warnings, got: {found}")

    def assertCompiles(self, source: str):
        """Assert a program type-checks and lowers without error."""
        try:
            compile_source(source)
        except COMPILE_ERRORS as e:
            self.fail(f"expected the program to compile, but got: {e}")


# -- debugger --------------------------------------------------------------
#
# The debugger drives itself through a callback, so a test supplies one instead
# of a terminal. Nothing here needs stdin, and the program's own output is kept
# apart from the session's so assertions can name one or the other.


def debug_trace(source: str, mode, setup=None, limit: int = 500):
    """(function, line) at every stop, running the whole program in one mode.

    `setup(debugger)` runs before the program does, which is where a test sets
    breakpoints. `limit` stops a test hanging if a step mode never advances.
    """
    from runtime.debugger import Debugger

    program = compile_source(source)
    stops = []

    def on_stop(dbg, vm, stop):
        stops.append((stop.frame.function, stop.frame.line))
        if len(stops) >= limit:
            raise AssertionError(f"more than {limit} stops; a step mode is not advancing")
        dbg.resume(mode, vm)

    debugger = Debugger(program, on_stop)
    if setup is not None:
        setup(debugger)
    with redirect_stdout(io.StringIO()):
        debugger.run(vm_for(program))
    return stops


def debug_session(source: str, commands) -> str:
    """Everything the interactive front end printed, given these commands.

    The program's own stdout is captured separately and discarded: a test that
    cares about it uses run_source.
    """
    from compiler.debug import DebugSession

    program = compile_source(source)
    remaining = list(commands)
    transcript = io.StringIO()

    def read(_prompt: str) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    session = DebugSession(program, vm_for(program), read=read, out=transcript)
    with redirect_stdout(io.StringIO()):
        try:
            session.run()
        except VMError:
            pass          # a post-mortem session ends by re-raising the fault
    return transcript.getvalue()


def main_wrapping(body: str) -> str:
    """Wrap statements in a `fn main(): int` that returns 0."""
    return f"fn main(): int {{\n{body}\n    return 0;\n}}"
