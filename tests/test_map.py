"""The hash map and hash set.

Open addressing means the interesting cases are all about the probe: what
happens when two keys want the same slot, and what a removal leaves behind. A
tombstone is not an empty slot -- a probe must walk through one, or every key
that once collided with a removed one becomes unfindable -- and most of what
follows pins that.

Several tests hash every key to the same slot on purpose. That is the worst case
and the only way to exercise the probe deterministically, since a real hash
spreads keys out and collides only by luck.
"""

import io
import unittest
from contextlib import redirect_stdout

from tests.harness import QuinTestCase, compile_source, run_source, vm_for

MAPS = 'include "std/map.ql";\ninclude "std/string.ql";\n'
SETS = 'include "std/set.ql";\ninclude "std/string.ql";\n'
# Every key lands in slot 0, so every operation is a probe.
COLLIDE = "fn always_zero(s: str): int { return 0; }\n"


def program(head: str, body: str, extra: str = "") -> str:
    return f"{head}{extra}fn main(): int {{\n{body}\n    return 0;\n}}\n"


def run_and_inspect(source: str):
    vm = vm_for(compile_source(source))
    buf = io.StringIO()
    with redirect_stdout(buf):
        vm.run_main()
    return vm, buf.getvalue()


class TestTheOrdinaryPath(QuinTestCase):
    def test_set_and_get(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "ada", 36); map_set(m, "alan", 41);\n'
            'println(map_len(m));\n'
            'println(option_show(map_get(m, "ada"), int_to_str));\n'
            'println(option_show(map_get(m, "nobody"), int_to_str));'),
            "2", "Some(36)", "None")

    def test_setting_an_existing_key_replaces(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "k", 1); map_set(m, "k", 2);\n'
            'println(map_len(m)); println(map_get_or(m, "k", 0));'),
            "1", "2")

    def test_has_and_get_or(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "k", 7);\n'
            'println(map_has(m, "k")); println(map_has(m, "j"));\n'
            'println(map_get_or(m, "j", 0 - 1));'),
            "true", "false", "-1")

    def test_an_empty_map(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'println(map_is_empty(m)); println(map_len(m));\n'
            'println(map_has(m, "anything"));\n'
            'println(array_len(map_keys(m)));'),
            "true", "0", "false", "0")

    def test_capacity_is_rounded_to_a_power_of_two(self):
        # Indexing masks rather than taking a remainder, which needs one.
        self.assertPrints(program(MAPS,
            'println(map_capacity(map_new::<str, int>(1, hash_str)));\n'
            'println(map_capacity(map_new::<str, int>(9, hash_str)));\n'
            'println(map_capacity(map_new::<str, int>(16, hash_str)));'),
            "8", "16", "16")

    def test_int_keys(self):
        self.assertPrints(program(MAPS,
            'let m: Map<int, str> = map_new(8, hash_int);\n'
            'map_set(m, 7, "seven");\n'
            'println(option_show(map_get(m, 7), show_str));\n'
            'println(option_show(map_get(m, 8), show_str));'),
            "Some(seven)", "None")

    def test_two_instantiations_in_one_program(self):
        self.assertPrints(program(MAPS,
            'let a: Map<str, int> = map_new(8, hash_str);\n'
            'let b: Map<int, str> = map_new(8, hash_int);\n'
            'map_set(a, "one", 1); map_set(b, 1, "one");\n'
            'println(map_get_or(a, "one", 0));\n'
            'println(option_show(map_get(b, 1), show_str));'),
            "1", "Some(one)")


class TestTheProbe(QuinTestCase):
    def collide(self, body: str) -> str:
        return program(MAPS, body, COLLIDE)

    def test_colliding_keys_all_survive(self):
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2); map_set(m, "c", 3);\n'
            'println(map_len(m));\n'
            'println(map_get_or(m, "a", 0)); println(map_get_or(m, "b", 0));\n'
            'println(map_get_or(m, "c", 0));'),
            "3", "1", "2", "3")

    def test_a_probe_walks_through_a_tombstone(self):
        # Removing the middle of a chain must not hide what is beyond it.
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2); map_set(m, "c", 3);\n'
            'map_remove(m, "b");\n'
            'println(map_get_or(m, "c", 0 - 1));\n'
            'println(option_show(map_get(m, "b"), int_to_str));\n'
            'println(map_len(m));'),
            "3", "None", "2")

    def test_a_tombstone_is_reused(self):
        # Not appended past: a table that only ever grew would fill with holes.
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2); map_set(m, "c", 3);\n'
            'map_remove(m, "b");\n'
            'map_set(m, "b", 20);\n'
            'println(map_len(m));\n'
            'println(map_get_or(m, "b", 0)); println(map_get_or(m, "c", 0));\n'
            'println(str_join(map_keys(m), ","));'),
            "3", "20", "3", "a,b,c")

    def test_removing_what_is_not_there(self):
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'map_set(m, "a", 1);\n'
            'println(map_remove(m, "zzz")); println(map_len(m));'),
            "false", "1")

    def test_removing_everything_and_starting_again(self):
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2);\n'
            'map_remove(m, "a"); map_remove(m, "b");\n'
            'println(map_is_empty(m));\n'
            'map_set(m, "c", 3);\n'
            'println(map_len(m)); println(map_get_or(m, "c", 0));'),
            "true", "1", "3")

    def test_tombstones_do_not_wedge_a_full_table(self):
        # Tombstones count toward the load, so a table churned in place still
        # grows rather than filling with holes a probe cannot get past.
        self.assertPrints(self.collide(
            'let m: Map<str, int> = map_new(8, always_zero);\n'
            'for (let i = 0; i < 100; i = i + 1) {\n'
            '    map_set(m, "k" + int_to_str(i), i);\n'
            '    map_remove(m, "k" + int_to_str(i));\n'
            '}\n'
            'map_set(m, "last", 9);\n'
            'println(map_len(m)); println(map_get_or(m, "last", 0));'),
            "1", "9")


class TestGrowth(QuinTestCase):
    def test_every_entry_survives_a_rehash(self):
        self.assertPrints(program(MAPS,
            'let m: Map<int, int> = map_new(8, hash_int);\n'
            'for (let i = 0; i < 300; i = i + 1) { map_set(m, i, i + 1000); }\n'
            'println(map_len(m));\n'
            'let missing: int = 0;\n'
            'for (let i = 0; i < 300; i = i + 1) {\n'
            '    if (map_get_or(m, i, 0) != i + 1000) { missing = missing + 1; }\n'
            '}\n'
            'println(missing);'),
            "300", "0")

    def test_capacity_grows_and_stays_a_power_of_two(self):
        self.assertPrints(program(MAPS,
            'let m: Map<int, int> = map_new(8, hash_int);\n'
            'for (let i = 0; i < 300; i = i + 1) { map_set(m, i, i); }\n'
            'println(map_capacity(m));'),
            "512")

    def test_growth_drops_tombstones(self):
        self.assertPrints(program(MAPS,
            'let m: Map<int, int> = map_new(8, hash_int);\n'
            'for (let i = 0; i < 100; i = i + 1) { map_set(m, i, i); }\n'
            'for (let i = 0; i < 90; i = i + 1) { map_remove(m, i); }\n'
            'for (let i = 200; i < 300; i = i + 1) { map_set(m, i, i); }\n'
            'println(map_len(m)); println(map_get_or(m, 95, 0));'),
            "110", "95")

    def test_clear(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2);\n'
            'map_clear(m);\n'
            'println(map_len(m)); println(map_has(m, "a"));\n'
            'map_set(m, "c", 3); println(map_get_or(m, "c", 0));'),
            "0", "false", "3")


class TestIteration(QuinTestCase):
    def test_keys_are_every_live_entry(self):
        self.assertPrints(program(MAPS,
            'let m: Map<int, int> = map_new(8, hash_int);\n'
            'for (let i = 0; i < 50; i = i + 1) { map_set(m, i, i); }\n'
            'for (let i = 0; i < 20; i = i + 1) { map_remove(m, i); }\n'
            'let keys: Array<int> = map_keys(m);\n'
            'println(array_len(keys));\n'
            'let sum: int = 0;\n'
            'for (let i = 0; i < array_len(keys); i = i + 1) { sum = sum + keys[i]; }\n'
            'println(sum);'),
            "30", "1035")

    def test_foreach_visits_each_entry_once(self):
        # Compared as a set, not a sequence: slot order is not insertion order,
        # and nothing about a hash map promises one.
        out = run_source(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2); map_set(m, "c", 3);\n'
            'map_foreach(m, show);',
            "fn show(k: str, v: int): void { print(k); println(v); }\n")).stdout
        self.assertEqual(sorted(out.split()), ["a1", "b2", "c3"])

    def test_foreach_skips_removed_entries(self):
        out = run_source(program(MAPS,
            'let m: Map<str, int> = map_new(8, hash_str);\n'
            'map_set(m, "a", 1); map_set(m, "b", 2); map_set(m, "c", 3);\n'
            'map_remove(m, "b");\n'
            'map_foreach(m, show);',
            "fn show(k: str, v: int): void { print(k); println(v); }\n")).stdout
        self.assertEqual(sorted(out.split()), ["a1", "c3"])


class TestTheCollector(QuinTestCase):
    def test_reference_keys_and_values_survive(self):
        self.assertPrints(program(MAPS,
            'let m: Map<str, str> = map_new(8, hash_str);\n'
            'for (let i = 0; i < 40; i = i + 1) {\n'
            '    map_set(m, "k" + int_to_str(i), "v" + int_to_str(i));\n'
            '}\n'
            'gc();\n'
            'println(map_len(m));\n'
            'println(option_show(map_get(m, "k0"), show_str));\n'
            'println(option_show(map_get(m, "k39"), show_str));'),
            "40", "Some(v0)", "Some(v39)")

    def test_the_state_array_is_not_traced(self):
        # keys and values are Array<str>; state is Array<int>. The collector
        # decides from each array's own header, so the map needs nothing.
        vm, _ = run_and_inspect(program(MAPS,
            'let m: Map<str, str> = map_new(8, hash_str);\n'
            'map_set(m, "a", "b");'))
        from runtime.vm import KIND_REFARRAY, KIND_VALARRAY
        kinds = [vm._kind(h) for h in vm._blocks()]
        self.assertIn(KIND_REFARRAY, kinds)
        self.assertIn(KIND_VALARRAY, kinds)

    def test_the_map_roots_its_arrays_and_not_its_hash(self):
        # Whatever K and V are, a Map holds three heap references and one
        # function value -- and a function value is an index, not an address,
        # so the collector never sees it.
        compiled = compile_source(program(MAPS,
            'let m: Map<int, int> = map_new(8, hash_int);\n'
            'map_set(m, 1, 2);'))
        layout = next(s for s in compiled.structs if s and s.name == "Map<int,int>")
        by_name = {f.name: f.offset for f in layout.fields}
        for field in ("keys", "values", "state"):
            self.assertIn(by_name[field], layout.ref_offsets, field)
        self.assertNotIn(by_name["hash"], layout.ref_offsets)


class TestSet(QuinTestCase):
    def test_add_reports_whether_it_was_new(self):
        self.assertPrints(program(SETS,
            'let s: Set<str> = set_new(8, hash_str);\n'
            'println(set_add(s, "x")); println(set_add(s, "x"));\n'
            'println(set_len(s));'),
            "true", "false", "1")

    def test_has_and_remove(self):
        self.assertPrints(program(SETS,
            'let s: Set<str> = set_new(8, hash_str);\n'
            'set_add(s, "x"); set_add(s, "y");\n'
            'println(set_has(s, "x")); println(set_remove(s, "x"));\n'
            'println(set_has(s, "x")); println(set_remove(s, "x"));\n'
            'println(set_len(s));'),
            "true", "true", "false", "false", "1")

    def test_union(self):
        self.assertPrints(program(SETS,
            'let a: Set<str> = set_new(8, hash_str);\n'
            'set_add(a, "x"); set_add(a, "y");\n'
            'let b: Set<str> = set_new(8, hash_str);\n'
            'set_add(b, "y"); set_add(b, "z");\n'
            'println(set_len(set_union(a, b)));\n'
            'println(set_len(a)); println(set_len(b));'),
            "3", "2", "2")

    def test_intersection_and_difference(self):
        self.assertPrints(program(SETS,
            'let a: Set<str> = set_new(8, hash_str);\n'
            'set_add(a, "x"); set_add(a, "y");\n'
            'let b: Set<str> = set_new(8, hash_str);\n'
            'set_add(b, "y"); set_add(b, "z");\n'
            'println(str_join(set_items(set_intersection(a, b)), ","));\n'
            'println(str_join(set_items(set_difference(a, b)), ","));'),
            "y", "x")

    def test_is_subset(self):
        self.assertPrints(program(SETS,
            'let a: Set<int> = set_new(8, hash_int);\n'
            'set_add(a, 1);\n'
            'let b: Set<int> = set_new(8, hash_int);\n'
            'set_add(b, 1); set_add(b, 2);\n'
            'println(set_is_subset(a, b)); println(set_is_subset(b, a));'),
            "true", "false")

    def test_it_grows_like_the_map_underneath(self):
        self.assertPrints(program(SETS,
            'let s: Set<int> = set_new(8, hash_int);\n'
            'for (let i = 0; i < 200; i = i + 1) { set_add(s, i); }\n'
            'gc();\n'
            'println(set_len(s)); println(set_has(s, 199)); println(set_has(s, 200));'),
            "200", "true", "false")


if __name__ == "__main__":
    unittest.main()
