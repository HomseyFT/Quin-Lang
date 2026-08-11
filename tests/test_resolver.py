"""Include resolution: path rules, cycles, and merging."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from compiler.resolver import ImportResolver, ResolveError
from tests.harness import QuinTestCase, STD_PATH, run_file


class TestIncludes(QuinTestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, source: str) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_relative_include(self):
        self.write("helper.ql", "fn helper(): int { return 21; }")
        entry = self.write(
            "main.ql",
            'include "./helper.ql";\nfn main(): int { println(helper() * 2); return 0; }',
        )
        self.assertEqual(run_file(entry).stdout, "42\n")

    def test_include_without_dot_prefix(self):
        self.write("helper.ql", "fn helper(): int { return 1; }")
        entry = self.write(
            "main.ql", 'include "helper.ql";\nfn main(): int { println(helper()); return 0; }'
        )
        self.assertEqual(run_file(entry).stdout, "1\n")

    def test_include_from_a_subdirectory(self):
        self.write("lib/helper.ql", "fn helper(): int { return 5; }")
        entry = self.write(
            "main.ql",
            'include "lib/helper.ql";\nfn main(): int { println(helper()); return 0; }',
        )
        self.assertEqual(run_file(entry).stdout, "5\n")

    def test_std_library(self):
        entry = self.write(
            "main.ql",
            'include "std/math.ql";\n'
            "fn main(): int { println(max(3, 9)); println(abs(0 - 4)); "
            "println(min(2, 8)); println(clamp(99, 0, 10)); return 0; }",
        )
        self.assertEqual(run_file(entry).stdout, "9\n4\n2\n10\n")

    def test_transitive_include(self):
        self.write("a.ql", "fn a(): int { return 1; }")
        self.write("b.ql", 'include "./a.ql";\nfn b(): int { return a() + 1; }')
        entry = self.write(
            "main.ql", 'include "./b.ql";\nfn main(): int { println(b()); return 0; }'
        )
        self.assertEqual(run_file(entry).stdout, "2\n")

    def test_diamond_include_is_processed_once(self):
        self.write("base.ql", "fn base(): int { return 1; }")
        self.write("left.ql", 'include "./base.ql";\nfn left(): int { return base(); }')
        self.write("right.ql", 'include "./base.ql";\nfn right(): int { return base(); }')
        entry = self.write(
            "main.ql",
            'include "./left.ql";\ninclude "./right.ql";\n'
            "fn main(): int { println(left() + right()); return 0; }",
        )
        self.assertEqual(run_file(entry).stdout, "2\n")

    def test_cycle_terminates(self):
        self.write("a.ql", 'include "./b.ql";\nfn a(): int { return 1; }')
        self.write("b.ql", 'include "./a.ql";\nfn b(): int { return 2; }')
        entry = self.write(
            "main.ql", 'include "./a.ql";\nfn main(): int { println(a() + b()); return 0; }'
        )
        self.assertEqual(run_file(entry).stdout, "3\n")

    def test_self_include_terminates(self):
        entry = self.write(
            "main.ql", 'include "./main.ql";\nfn main(): int { println(1); return 0; }'
        )
        self.assertEqual(run_file(entry).stdout, "1\n")

    def test_missing_file(self):
        entry = self.write(
            "main.ql", 'include "./nope.ql";\nfn main(): int { return 0; }'
        )
        with self.assertRaises(ResolveError) as cm:
            ImportResolver(STD_PATH).resolve(entry)
        self.assertIn("Cannot find file", str(cm.exception))

    def test_duplicate_function_across_files(self):
        self.write("dup.ql", "fn shared(): int { return 1; }")
        entry = self.write(
            "main.ql",
            'include "./dup.ql";\n'
            "fn shared(): int { return 2; }\nfn main(): int { return 0; }",
        )
        with self.assertRaises(ResolveError) as cm:
            ImportResolver(STD_PATH).resolve(entry)
        self.assertIn("Redefinition of function 'shared'", str(cm.exception))

    def test_struct_from_an_included_file(self):
        self.write("point.ql", "struct Point { x: int, y: int }")
        entry = self.write(
            "main.ql",
            'include "./point.ql";\n'
            "fn main(): int { let p: Point = Point { x: 6, y: 7 }; println(p.y); return 0; }",
        )
        self.assertEqual(run_file(entry).stdout, "7\n")

    def test_struct_and_the_functions_using_it_may_live_apart(self):
        self.write("point.ql", "struct Point { x: int, y: int }")
        self.write(
            "area.ql",
            'include "./point.ql";\nfn area(p: Point): int { return p.x * p.y; }',
        )
        entry = self.write(
            "main.ql",
            'include "./area.ql";\n'
            "fn main(): int { println(area(Point { x: 3, y: 4 })); return 0; }",
        )
        self.assertEqual(run_file(entry).stdout, "12\n")

    def test_duplicate_struct_across_files(self):
        self.write("dup.ql", "struct Shared { a: int }")
        entry = self.write(
            "main.ql",
            'include "./dup.ql";\n'
            "struct Shared { b: int }\nfn main(): int { return 0; }",
        )
        with self.assertRaises(ResolveError) as cm:
            ImportResolver(STD_PATH).resolve(entry)
        self.assertIn("Redefinition of struct 'Shared'", str(cm.exception))

    def test_diamond_include_defines_a_struct_once(self):
        self.write("base.ql", "struct Base { v: int }")
        self.write("left.ql", 'include "./base.ql";\nfn left(): int { return 1; }')
        self.write("right.ql", 'include "./base.ql";\nfn right(): int { return 2; }')
        entry = self.write(
            "main.ql",
            'include "./left.ql";\ninclude "./right.ql";\n'
            "fn main(): int { let b: Base = Base { v: 9 }; println(b.v); return 0; }",
        )
        self.assertEqual(run_file(entry).stdout, "9\n")

    def test_syntax_error_names_the_including_file(self):
        self.write("bad.ql", "fn broken( { }")
        entry = self.write(
            "main.ql", 'include "./bad.ql";\nfn main(): int { return 0; }'
        )
        with self.assertRaises(ResolveError) as cm:
            ImportResolver(STD_PATH).resolve(entry)
        self.assertIn("bad.ql", str(cm.exception))

    def test_included_functions_come_before_the_includers(self):
        self.write("helper.ql", "fn helper(): int { return 1; }")
        entry = self.write(
            "main.ql", 'include "./helper.ql";\nfn main(): int { return 0; }'
        )
        resolved = ImportResolver(STD_PATH).resolve(entry)
        names = [f.name for f in resolved.program.functions]
        self.assertEqual(names, ["helper", "main"])

    def test_merged_program_has_no_includes_left(self):
        self.write("helper.ql", "fn helper(): int { return 1; }")
        entry = self.write(
            "main.ql", 'include "./helper.ql";\nfn main(): int { return 0; }'
        )
        resolved = ImportResolver(STD_PATH).resolve(entry)
        self.assertEqual(resolved.program.includes, [])
        self.assertEqual(len(resolved.source_files), 2)


if __name__ == "__main__":
    unittest.main()
