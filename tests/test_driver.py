"""The command-line driver, exercised as a real process.

Everything else in the suite runs the VM in-process and reads run_main()'s
value directly. These tests care about what a shell sees, which is a different
thing: a process exit status is 8 bits wide, and int is a 16-bit signed value.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from compiler.driver_vm import process_exit_code
from tests.harness import REPO_ROOT


def run_driver(source: str) -> subprocess.CompletedProcess:
    """Compile and run source in a subprocess, as a user would."""
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "compiler.driver_vm", str(entry)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )


class TestExitCode(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(run_driver("fn main(): int { return 0; }").returncode, 0)

    def test_a_nonzero_value_reaches_the_shell(self):
        self.assertEqual(run_driver("fn main(): int { return 3; }").returncode, 3)

    def test_a_larger_value(self):
        self.assertEqual(run_driver("fn main(): int { return 42; }").returncode, 42)

    def test_the_largest_value_that_survives_intact(self):
        self.assertEqual(run_driver("fn main(): int { return 255; }").returncode, 255)

    def test_values_above_255_keep_only_the_low_byte(self):
        # As in C. 256 exits 0, which looks like success -- worth knowing.
        self.assertEqual(run_driver("fn main(): int { return 256; }").returncode, 0)
        self.assertEqual(run_driver("fn main(): int { return 300; }").returncode, 44)

    def test_negative_values_wrap(self):
        self.assertEqual(run_driver("fn main(): int { return 0 - 1; }").returncode, 255)
        self.assertEqual(run_driver("fn main(): int { return 0 - 2; }").returncode, 254)

    def test_void_main_exits_zero(self):
        self.assertEqual(run_driver("fn main(): void { }").returncode, 0)

    def test_a_computed_value(self):
        self.assertEqual(
            run_driver("fn f(x: int): int { return x * 2; }\n"
                       "fn main(): int { return f(11); }").returncode,
            22,
        )

    def test_output_still_reaches_stdout(self):
        result = run_driver('fn main(): int { println("hi"); return 7; }')
        self.assertEqual(result.stdout.strip(), "hi")
        self.assertEqual(result.returncode, 7)


class TestExitCodeNarrowing(unittest.TestCase):
    """The truncation itself, independent of the host platform.

    POSIX narrows an exit status to its low byte on its own, so on Linux the
    masking looks like a no-op and a subprocess test cannot tell whether it
    happens. Windows exit codes are 32 bits wide and would report -1 as
    4294967295, so the rule is pinned here directly.
    """

    def test_values_that_fit_are_unchanged(self):
        for v in (0, 1, 42, 254, 255):
            self.assertEqual(process_exit_code(v), v)

    def test_values_above_a_byte_keep_the_low_byte(self):
        self.assertEqual(process_exit_code(256), 0)
        self.assertEqual(process_exit_code(300), 44)
        self.assertEqual(process_exit_code(32767), 255)

    def test_negative_values_become_their_twos_complement_byte(self):
        self.assertEqual(process_exit_code(-1), 255)
        self.assertEqual(process_exit_code(-2), 254)
        self.assertEqual(process_exit_code(-256), 0)
        self.assertEqual(process_exit_code(-32768), 0)

    def test_the_result_is_always_a_valid_exit_status(self):
        for v in range(-32768, 32768, 97):
            self.assertTrue(0 <= process_exit_code(v) <= 255, f"failed for {v}")


class TestErrorExits(unittest.TestCase):
    """Errors keep exiting 1, on stderr."""

    def test_compile_error(self):
        result = run_driver("fn main(): int { let x: int = true; return 0; }")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Semantic error", result.stderr)

    def test_syntax_error(self):
        result = run_driver("fn main(): int { return 0 }")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Import error", result.stderr)

    def test_runtime_error(self):
        result = run_driver("fn main(): int { let z: int; println(1 / z); return 0; }")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Runtime error", result.stderr)

    def test_a_program_returning_one_is_indistinguishable_from_an_error(self):
        # Both exit 1. Nothing to fix -- the same is true of any C program --
        # but a script that treats 1 as "the tool failed" needs to know.
        ok = run_driver("fn main(): int { return 1; }")
        bad = run_driver("fn main(): int { let z: int; println(1 / z); return 0; }")
        self.assertEqual(ok.returncode, bad.returncode)
        self.assertEqual(ok.stderr, "")
        self.assertNotEqual(bad.stderr, "")


if __name__ == "__main__":
    unittest.main()
