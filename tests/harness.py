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
    """Compile a .ql file to (bytecode, function table, string table, struct table)."""
    resolved = ImportResolver(STD_PATH).resolve(Path(path))
    ctx = SemanticAnalyzer().analyze(resolved.program)
    return CodeGenVM().generate(resolved.program, ctx)


def compile_source(source: str):
    """Compile source text by staging it as a file, so includes resolve."""
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        return compile_file(entry)


def run_file(path: Path) -> Run:
    code, functions, strings, structs = compile_file(path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_value = QuinVM(code, functions, strings, structs).run_main()
    return Run(buf.getvalue(), exit_value)


def run_source(source: str) -> Run:
    code, functions, strings, structs = compile_source(source)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_value = QuinVM(code, functions, strings, structs).run_main()
    return Run(buf.getvalue(), exit_value)


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

    def assertCompiles(self, source: str):
        """Assert a program type-checks and lowers without error."""
        try:
            compile_source(source)
        except COMPILE_ERRORS as e:
            self.fail(f"expected the program to compile, but got: {e}")


def main_wrapping(body: str) -> str:
    """Wrap statements in a `fn main(): int` that returns 0."""
    return f"fn main(): int {{\n{body}\n    return 0;\n}}"
