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

from compiler.driver_vm import EXIT_COMPILE_ERROR, EXIT_RUNTIME_ERROR, process_exit_code
from tests.harness import REPO_ROOT, QuinTestCase, warnings_for


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


class TestExitCodeWarning(QuinTestCase):
    """A constant main can only return 0..255 unambiguously.

    Without this, `return 256` exits 0 and reads as success, which is the one
    case where the truncation is actively misleading rather than merely lossy.
    """

    def test_256_is_warned_about(self):
        message = self.assertCompileWarning(
            "fn main(): int { return 256; }", "main returns 256"
        )
        self.assertIn("exits 0", message, "the warning should name the real exit code")

    def test_the_warning_names_the_resulting_code(self):
        self.assertCompileWarning("fn main(): int { return 300; }", "exits 44")

    def test_negative_values_are_warned_about(self):
        self.assertCompileWarning("fn main(): int { return 0 - 1; }", "main returns -1")
        self.assertCompileWarning("fn main(): int { return 0 - 1; }", "exits 255")

    def test_unary_negation_is_folded(self):
        self.assertCompileWarning("fn main(): int { return -2; }", "main returns -2")

    def test_arithmetic_is_folded(self):
        # 200 + 100 is 300, which is out of range even though neither part is.
        self.assertCompileWarning("fn main(): int { return 200 + 100; }", "exits 44")

    def test_wrapping_is_accounted_for(self):
        # 32767 + 1 wraps to -32768, so that is what gets returned and reported.
        self.assertCompileWarning(
            "fn main(): int { return 32767 + 1; }", "main returns -32768"
        )

    def test_values_in_range_are_not_warned_about(self):
        for v in ("0", "1", "42", "255", "254 + 1"):
            self.assertNoCompileWarnings(f"fn main(): int {{ return {v}; }}")

    def test_void_main_is_not_warned_about(self):
        self.assertNoCompileWarnings("fn main(): void { }")

    def test_a_non_constant_return_is_not_warned_about(self):
        # Nothing can be known about this at compile time, so stay quiet
        # rather than guess.
        self.assertNoCompileWarnings(
            "fn f(): int { return 999; }\nfn main(): int { return f(); }"
        )
        self.assertNoCompileWarnings(
            "fn main(): int { let x: int = 300; return x; }"
        )

    def test_other_functions_are_not_warned_about(self):
        # Only main's return becomes an exit code.
        self.assertNoCompileWarnings(
            "fn helper(): int { return 999; }\n"
            "fn main(): int { println(helper()); return 0; }"
        )

    def test_every_offending_return_is_reported(self):
        found = warnings_for(
            """
            fn main(): int {
                if (true) { return 256; }
                return 0 - 5;
            }
            """
        )
        self.assertEqual(len(found), 2, f"expected both returns flagged, got {found}")

    def test_the_warning_carries_a_location(self):
        found = warnings_for("fn main(): int {\n    return 256;\n}")
        self.assertTrue(found[0].startswith("[2:"), f"expected line 2, got {found[0]}")

    def test_the_warning_goes_to_stderr_and_changes_nothing(self):
        result = run_driver('fn main(): int { println("out"); return 256; }')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "out",
                         "warnings must not pollute stdout")
        self.assertIn("Warning:", result.stderr)
        self.assertIn("main returns 256", result.stderr)

    def test_a_clean_program_prints_no_warning(self):
        result = run_driver("fn main(): int { return 0; }")
        self.assertEqual(result.stderr, "")


class TestErrorExits(unittest.TestCase):
    """Errors exit with a code of their own, on stderr."""

    def test_compile_error(self):
        result = run_driver("fn main(): int { let x: int = true; return 0; }")
        self.assertEqual(result.returncode, EXIT_COMPILE_ERROR)
        self.assertIn("Semantic error", result.stderr)

    def test_syntax_error(self):
        result = run_driver("fn main(): int { return 0 }")
        self.assertEqual(result.returncode, EXIT_COMPILE_ERROR)
        self.assertIn("Import error", result.stderr)

    def test_runtime_error(self):
        result = run_driver("fn main(): int { let z: int; println(1 / z); return 0; }")
        self.assertEqual(result.returncode, EXIT_RUNTIME_ERROR)
        self.assertIn("Runtime error", result.stderr)

    def test_compile_and_runtime_failures_are_distinguishable(self):
        # The point of moving off 1: a caller can tell "it never ran" from
        # "it ran and faulted" without parsing stderr.
        compile_fail = run_driver("fn main(): int { let x: int = true; return 0; }")
        runtime_fail = run_driver("fn main(): int { let z: int; println(1 / z); return 0; }")
        self.assertNotEqual(compile_fail.returncode, runtime_fail.returncode)

    def test_a_program_returning_one_is_no_longer_an_error_code(self):
        # This used to be indistinguishable from a failure. Nothing reserves 2
        # or 3 from a program either, so stderr is still the certain signal --
        # but 1 is the value a script is most likely to return on purpose.
        ok = run_driver("fn main(): int { return 1; }")
        self.assertEqual(ok.returncode, 1)
        self.assertEqual(ok.stderr, "")
        self.assertNotIn(ok.returncode, (EXIT_COMPILE_ERROR, EXIT_RUNTIME_ERROR))

    def test_a_program_may_still_return_an_error_code_itself(self):
        # Documented collision: exit status alone cannot carry both, so a 3
        # from a clean program looks like a runtime error to the shell.
        result = run_driver("fn main(): int { return 3; }")
        self.assertEqual(result.returncode, EXIT_RUNTIME_ERROR)
        self.assertEqual(result.stderr, "", "but stderr tells them apart")


if __name__ == "__main__":
    unittest.main()
