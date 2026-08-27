"""Every example must compile, run, and print exactly its golden output.

An example that reads input is fed `examples/<name>.in`, so it still has one
fixed expected output. Examples never read the real stdin: the harness supplies
an empty one when there is no fixture.

The goldens live in tests/golden/<name>.out. Regenerate them after an
intentional change with:

    python3 -m tests.update_golden

and read the diff before committing it: a changed golden is either a fix or a
regression, and only you can tell which.
"""

import unittest

from tests.harness import EXAMPLES_PATH, GOLDEN_PATH, QuinTestCase, run_file

EXAMPLES = sorted(EXAMPLES_PATH.glob("*.ql"))


class TestExamples(QuinTestCase):
    def test_examples_exist(self):
        self.assertTrue(EXAMPLES, "no examples found to test")

    def test_every_example_has_a_golden(self):
        missing = [
            p.name for p in EXAMPLES if not (GOLDEN_PATH / f"{p.stem}.out").exists()
        ]
        self.assertEqual(
            missing, [], "run `python3 -m tests.update_golden` to create these"
        )

    def test_no_orphan_goldens(self):
        stems = {p.stem for p in EXAMPLES}
        orphans = [g.name for g in GOLDEN_PATH.glob("*.out") if g.stem not in stems]
        self.assertEqual(orphans, [], "golden files with no matching example")

    def test_no_orphan_input_fixtures(self):
        # An example that reads is fed examples/<name>.in, so a fixture whose
        # program is gone would silently stop being used.
        stems = {p.stem for p in EXAMPLES}
        orphans = [f.name for f in EXAMPLES_PATH.glob("*.in") if f.stem not in stems]
        self.assertEqual(orphans, [], "input fixtures with no matching example")


def _make_test(path):
    def test(self):
        golden = GOLDEN_PATH / f"{path.stem}.out"
        expected = golden.read_text(encoding="utf-8")
        actual = run_file(path).stdout
        self.assertEqual(
            actual, expected,
            f"\n{path.name} output changed.\n"
            f"If this is intentional, run: python3 -m tests.update_golden",
        )
    test.__name__ = f"test_{path.stem}"
    test.__doc__ = f"examples/{path.name} matches its golden output"
    return test


# One test method per example, so a failure names the file that broke.
for _path in EXAMPLES:
    setattr(TestExamples, f"test_{_path.stem}", _make_test(_path))


if __name__ == "__main__":
    unittest.main()
