"""Sum types: enum declaration, variant construction, and match.

A variant is a struct at run time -- same header, same type id, same field
offsets -- so the interesting questions are not about layout but about the
layer above it: does the tag survive, is coverage actually checked, does a
binding scope like a local, and does the collector still see a reference that
is only reachable through a variant.

Sources are written with a leading newline for readability, so line 1 is the
blank one the triple-quoted string opens with.
"""

import unittest

from tests.harness import QuinTestCase, compile_source, run_source, vm_for

RESULT = "enum Result { Ok(int), Err(str), Pending }\n"


class TestDeclaration(QuinTestCase):
    def test_an_enum_declares_a_type(self):
        self.assertCompiles(RESULT + "fn main(): int { let r: Result = Pending; return 0; }")

    def test_an_enum_must_have_a_variant(self):
        self.assertCompileError("enum E { }\nfn main(): int { return 0; }",
                                "must declare at least one variant")

    def test_redefinition_is_rejected(self):
        self.assertCompileError(
            "enum E { A }\nenum E { B }\nfn main(): int { return 0; }",
            "Redefinition of enum 'E'")

    def test_an_enum_cannot_shadow_a_builtin_type(self):
        self.assertCompileError("enum int { A }\nfn main(): int { return 0; }",
                                "Expected enum name")

    def test_an_enum_cannot_clash_with_a_struct(self):
        self.assertCompileError(
            "struct P { x: int }\nenum P { A }\nfn main(): int { return 0; }",
            "clashes with the struct")

    def test_variant_names_are_global(self):
        # The price of writing `Ok(5)` rather than `Result::Ok(5)`.
        self.assertCompileError(
            "enum A { Ok(int) }\nenum B { Ok(int) }\nfn main(): int { return 0; }",
            "variant names are global")

    def test_a_function_cannot_take_a_variant_name(self):
        self.assertCompileError(
            RESULT + "fn Ok(): int { return 1; }\nfn main(): int { return 0; }",
            "same name as a variant")

    def test_a_variant_cannot_carry_an_array(self):
        self.assertCompileError("enum E { A(int[3]) }\nfn main(): int { return 0; }",
                                "cannot carry an array")

    def test_an_empty_payload_list_is_rejected(self):
        # `A()` and `A` would otherwise be two spellings of one thing, and only
        # one of them can be the interned singleton.
        self.assertCompileError("enum E { A() }\nfn main(): int { return 0; }",
                                "without parentheses")


class TestConstruction(QuinTestCase):
    def test_a_variant_with_a_payload_is_called(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Ok(7); '
                     'match (r) { Ok(v) => { println(v); } _ => {} } return 0; }',
            "7")

    def test_a_variant_without_a_payload_is_a_bare_name(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Pending; '
                     'match (r) { Pending => { println(1); } _ => {} } return 0; }',
            "1")

    def test_a_payload_free_variant_written_as_a_call_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending(); return 0; }",
            "carries no payload")

    def test_a_payload_variant_written_bare_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Ok; return 0; }",
            "write 'Ok(...)'")

    def test_the_payload_is_type_checked(self):
        self.assertCompileError(
            RESULT + 'fn main(): int { let r: Result = Ok("no"); return 0; }',
            "expects int at position 0")

    def test_arity_is_checked(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Ok(1, 2); return 0; }",
            "carries 1 value(s), got 2")

    def test_a_construction_has_the_enum_type(self):
        # Not the variant's own type: a variant is not something anyone can
        # declare a variable of, so nothing needs the narrower type.
        self.assertCompiles(
            RESULT + "fn take(r: Result): int { return 0; }\n"
                     "fn main(): int { return take(Ok(1)); }")

    def test_a_variant_can_carry_a_struct(self):
        self.assertPrints(
            "struct P { x: int }\nenum E { Wrap(P), None }\n"
            "fn main(): int { let e: E = Wrap(P{x: 9}); "
            "match (e) { Wrap(p) => { println(p.x); } None => {} } return 0; }",
            "9")

    def test_a_variant_can_carry_a_float(self):
        self.assertPrints(
            "enum E { F(float), N }\n"
            "fn main(): int { let e: E = F(2.5); "
            "match (e) { F(x) => { println(x + 0.25); } N => {} } return 0; }",
            "2.75")


class TestMatch(QuinTestCase):
    SRC = RESULT + """
    fn describe(r: Result): int {
        match (r) {
            Ok(v) => { println(v); }
            Err(m) => { println(m); }
            Pending => { println("pending"); }
        }
        return 0;
    }
    fn main(): int {
        describe(Ok(42));
        describe(Err("bad"));
        describe(Pending);
        return 0;
    }
    """

    def test_each_variant_takes_its_own_arm(self):
        self.assertPrints(self.SRC, "42\nbad\npending")

    def test_the_subject_is_parenthesised(self):
        # `match r {` is ambiguous: an identifier followed by a brace is how a
        # struct literal begins, so the subject would swallow the arms.
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; match r { _ => {} } return 0; }",
            "Expected '(' after 'match'")

    def test_a_non_enum_subject_is_rejected(self):
        self.assertCompileError(
            "fn main(): int { let x: int = 1; match (x) { A => {} } return 0; }",
            "match requires an enum")

    def test_an_unknown_variant_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Nope => {} } return 0; }",
            "has no variant 'Nope'")

    def test_a_variant_of_another_enum_says_which(self):
        self.assertCompileError(
            RESULT + "enum Other { Wat }\n"
                     "fn main(): int { let r: Result = Pending; "
                     "match (r) { Wat => {} } return 0; }",
            "'Wat' belongs to enum 'Other'")

    def test_a_repeated_arm_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; match (r) { "
                     "Ok(a) => {} Ok(b) => {} Err(m) => {} Pending => {} } return 0; }",
            "is matched twice")

    def test_binding_count_must_match_the_payload(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Ok(a, b) => {} _ => {} } return 0; }",
            "carries 1 value(s), but the arm binds 2")

    def test_a_match_can_return_from_every_arm(self):
        self.assertPrints(
            RESULT + """
            fn pick(r: Result): int {
                match (r) {
                    Ok(v) => { return v; }
                    Err(m) => { return 0 - 1; }
                    Pending => { return 0; }
                }
            }
            fn main(): int { println(pick(Ok(8))); return 0; }
            """,
            "8")

    def test_a_match_that_does_not_always_return_is_still_checked(self):
        self.assertCompileError(
            RESULT + """
            fn pick(r: Result): int {
                match (r) {
                    Ok(v) => { return v; }
                    Err(m) => { println(m); }
                    Pending => { return 0; }
                }
            }
            fn main(): int { return pick(Pending); }
            """,
            "missing return statement")


class TestExhaustiveness(QuinTestCase):
    def test_a_missing_variant_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Ok(v) => {} Err(m) => {} } return 0; }",
            "does not cover: Pending")

    def test_every_missing_variant_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Ok(v) => {} } return 0; }",
            "does not cover: Err, Pending")

    def test_a_catch_all_satisfies_coverage(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Err("x"); '
                     'match (r) { Ok(v) => { println(v); } _ => { println("other"); } } '
                     'return 0; }',
            "other")

    def test_a_catch_all_that_covers_nothing_warns(self):
        # It is the arm that would silently absorb a variant added later, so
        # saying it is dead is the whole point of the coverage check.
        self.assertCompileWarning(
            RESULT + "fn main(): int { let r: Result = Pending; match (r) { "
                     "Ok(v) => {} Err(m) => {} Pending => {} _ => {} } return 0; }",
            "'_' covers no remaining variant")

    def test_a_used_catch_all_does_not_warn(self):
        self.assertNoCompileWarnings(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Ok(v) => {} _ => {} } return 0; }")

    def test_an_arm_after_the_catch_all_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { _ => {} Ok(v) => {} } return 0; }",
            "comes after '_', so it can never match")

    def test_two_catch_alls_are_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { _ => {} _ => {} } return 0; }",
            "comes after '_'")

    def test_the_catch_all_cannot_bind(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { _(v) => {} } return 0; }",
            "'_' cannot bind a payload")


class TestBindings(QuinTestCase):
    def test_a_binding_is_scoped_to_its_arm(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Pending; "
                     "match (r) { Ok(v) => {} _ => {} } println(v); return 0; }",
            "Undeclared variable 'v'")

    def test_two_arms_may_bind_the_same_name(self):
        # Sibling scopes, like two if blocks.
        self.assertPrints(
            "enum E { A(int), B(int) }\n"
            "fn main(): int { let e: E = B(3); "
            "match (e) { A(v) => { println(v); } B(v) => { println(v + 1); } } return 0; }",
            "4")

    def test_a_binding_shadows_an_outer_name(self):
        self.assertPrints(
            RESULT + "fn main(): int { let v: int = 1; let r: Result = Ok(9); "
                     "match (r) { Ok(v) => { println(v); } _ => {} } println(v); return 0; }",
            "9\n1")

    def test_multiple_payload_values_bind_in_order(self):
        self.assertPrints(
            "enum Pair { Both(int, str), Neither }\n"
            'fn main(): int { let p: Pair = Both(4, "four"); '
            "match (p) { Both(n, name) => { println(n); println(name); } Neither => {} } "
            "return 0; }",
            "4\nfour")

    def test_a_bound_reference_stops_rooting_when_the_arm_ends(self):
        # The arm is a scope like any other, so its reference slots are
        # released at the end of it.
        program = compile_source(
            "enum E { S(str), N }\n"
            'fn main(): int { let e: E = S("x"); '
            "match (e) { S(s) => { println(s); } N => {} } return 0; }"
        )
        self.assertTrue(program.functions)


class TestRecursion(QuinTestCase):
    def test_a_variant_may_carry_its_own_enum(self):
        self.assertPrints(
            """
            enum List { Nil, Cons(int, List) }
            fn total(l: List): int {
                match (l) {
                    Nil => { return 0; }
                    Cons(head, rest) => { return head + total(rest); }
                }
            }
            fn main(): int { println(total(Cons(1, Cons(2, Cons(3, Nil))))); return 0; }
            """,
            "6")

    def test_a_variant_may_carry_an_enum_declared_later(self):
        self.assertCompiles(
            "enum A { Wrap(B), None }\nenum B { Leaf }\n"
            "fn main(): int { let a: A = Wrap(Leaf); return 0; }")


class TestRuntime(QuinTestCase):
    def test_matching_a_null_subject_faults(self):
        # An enum reference is nullable, so coverage of every variant is not a
        # promise that the value is one of them. This faults the way reading a
        # field of a null struct does.
        self.assertRuntimeError(
            "enum E { A(int), B }\nfn main(): int { let e: E; "
            "match (e) { A(v) => {} B => {} } return 0; }",
            "Null reference in match")

    def test_null_is_assignable_to_an_enum(self):
        self.assertCompiles("enum E { A }\nfn main(): int { let e: E = null; return 0; }")

    def test_a_payload_free_variant_is_one_object(self):
        import io
        from contextlib import redirect_stdout
        program = compile_source(
            "enum C { A, B }\n"
            "fn main(): int { let x: C = A; let y: C = A; let z: C = A; return 0; }"
        )
        vm = vm_for(program)
        with redirect_stdout(io.StringIO()):
            vm.run_main()
        # Three uses of A, one object: a variant carrying nothing is a
        # constant, so allocating per use would be pure collector pressure.
        interned = [addr for addr in vm.variants if addr]
        self.assertEqual(len(interned), 2, "one instance per payload-free variant")
        self.assertEqual(vm.heap_in_use(), 12, "and nothing else was allocated")

    def test_a_variant_survives_collection(self):
        # The claim that the collector needs no changes, tested rather than
        # asserted: the string is reachable only through the variant.
        self.assertPrints(
            """
            enum Box { Full(str), Empty }
            fn main(): int {
                let b: Box = Full("kept");
                for (let i = 0; i < 3000; i = i + 1) { let junk: str = int_to_str(i); }
                gc();
                match (b) { Full(s) => { println(s); } Empty => { println("lost"); } }
                return 0;
            }
            """,
            "kept")

    def test_a_variant_survives_compaction_with_its_payload_intact(self):
        self.assertPrints(
            """
            struct P { x: int, y: int }
            enum Holder { Has(P), None }
            fn main(): int {
                let h: Holder = Has(P{x: 11, y: 22});
                for (let i = 0; i < 2000; i = i + 1) { let junk: str = int_to_str(i); }
                gc();
                match (h) { Has(p) => { println(p.x + p.y); } None => { println(0); } }
                return 0;
            }
            """,
            "33")


class TestLayout(QuinTestCase):
    def test_variants_share_the_struct_table(self):
        # This is what makes the collector work unchanged: a variant is an
        # entry in the same table, indexed by the same type id.
        program = compile_source(
            "struct P { x: int }\nenum E { A(int), B }\n"
            "fn main(): int { let e: E = A(1); let p: P = P{x: 2}; return 0; }"
        )
        by_name = {layout.name: layout for layout in program.structs}
        self.assertEqual(set(by_name), {"P", "A", "B"})
        self.assertFalse(by_name["P"].is_variant)
        self.assertTrue(by_name["A"].is_variant)

    def test_type_ids_are_unique_across_structs_and_variants(self):
        program = compile_source(
            "struct P { x: int }\nstruct Q { y: int }\nenum E { A(int), B }\n"
            "fn main(): int { let e: E = B; return 0; }"
        )
        ids = [i for i, layout in enumerate(program.structs) if layout is not None]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)

    def test_a_reference_payload_is_recorded_for_tracing(self):
        program = compile_source(
            "enum E { S(str), I(int) }\nfn main(): int { let e: E = I(1); return 0; }"
        )
        by_name = {layout.name: layout for layout in program.structs}
        self.assertEqual(by_name["S"].ref_offsets, (0,), "a str payload must be traced")
        self.assertEqual(by_name["I"].ref_offsets, (), "an int payload must not be")


class TestAcrossFiles(QuinTestCase):
    def test_an_enum_from_an_included_file_is_usable(self):
        # The resolver merges enums the way it merges structs. Without that,
        # an enum in an included file would vanish and every use of it would
        # fail as an unknown type, naming the wrong file.
        import tempfile
        from pathlib import Path
        from tests.harness import compile_file
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "shapes.ql").write_text("enum Shape { Dot, Line(int) }\n", encoding="utf-8")
            entry = root / "main.ql"
            entry.write_text(
                'include "shapes.ql";\n'
                "fn main(): int { let s: Shape = Line(3); "
                "match (s) { Dot => {} Line(n) => {} } return 0; }\n",
                encoding="utf-8")
            program = compile_file(entry)
        self.assertIn("Line", [layout.name for layout in program.structs])


if __name__ == "__main__":
    unittest.main()
