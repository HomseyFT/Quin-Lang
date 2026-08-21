"""QuinLang runs on a stock Python and nothing else.

That is a deliberate constraint, not an accident of the code being small: the
toolchain should work for anyone who has Python, with no install step. Nothing
enforces it except this file, and a single convenient import is all it takes to
lose it -- so the import surface is checked directly.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

from tests.harness import REPO_ROOT

# Packages that are part of this project rather than something to install.
FIRST_PARTY = {"compiler", "runtime", "tests"}

SOURCE_DIRS = ("compiler", "runtime", "tests")


def python_files():
    for d in SOURCE_DIRS:
        for p in sorted((REPO_ROOT / d).rglob("*.py")):
            if "__pycache__" not in p.parts:
                yield p


def top_level_imports(path: Path):
    """Every distinct package name `path` imports, ignoring relative imports.

    A relative import (`from . import ast`) can only name something inside this
    project, so it is never a dependency.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module.split(".")[0]


class TestNoThirdPartyDependencies(unittest.TestCase):
    def test_every_import_is_stdlib_or_first_party(self):
        offenders = {}
        for path in python_files():
            for name in top_level_imports(path):
                if name in FIRST_PARTY or name in sys.stdlib_module_names:
                    continue
                offenders.setdefault(name, []).append(
                    str(path.relative_to(REPO_ROOT))
                )
        self.assertEqual(
            offenders, {},
            "third-party imports found; QuinLang installs nothing, so these "
            "would have to be vendored or removed",
        )

    def test_there_are_files_to_check(self):
        # A path typo here would empty the walk and make the check above pass
        # while inspecting nothing.
        self.assertGreater(len(list(python_files())), 20)

    def test_the_check_can_actually_fail(self):
        # Guards the guard: if stdlib_module_names ever stopped containing what
        # this relies on, every import would look third-party or none would.
        self.assertIn("pathlib", sys.stdlib_module_names)
        self.assertNotIn("numpy", sys.stdlib_module_names)


class TestSupportedPythonVersion(unittest.TestCase):
    """The floor is 3.10, and something concrete depends on it."""

    def test_running_on_a_supported_version(self):
        self.assertGreaterEqual(
            sys.version_info[:2], (3, 10),
            "QuinLang uses dataclass field(kw_only=True), which is 3.10+",
        )

    def test_sources_parse_as_310(self):
        # CI covers this by running the suite on 3.10, but a syntax feature
        # from a later version would otherwise only be caught there.
        for path in python_files():
            with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                ast.parse(path.read_text(encoding="utf-8"),
                          feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
