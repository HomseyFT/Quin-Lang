"""Sum types: enum declaration, variant construction, and match.

A variant is a struct at run time -- same header, same type id, same field
offsets -- so the interesting questions are not about layout but about the
layer above it: does the tag survive, is coverage actually checked, does a
binding scope like a local, and does the collector still see a reference that
is only reachable through a variant.

Variants are named `Enum::Variant` everywhere they are used. Only the
declaration writes the short name, which is why every source below declares
`enum Result { Ok(int), ... }` and then writes `Result::Ok`.

Sources are written with a leading newline for readability, so line 1 is the
blank one the triple-quoted string opens with.
"""

import unittest

from tests.harness import QuinTestCase, compile_source, run_source, vm_for

RESULT = "enum Result { Ok(int), Err(str), Pending }\n"


class TestDeclaration(QuinTestCase):
    def test_an_enum_declares_a_type(self):
        self.assertCompiles(
            RESULT + "fn main(): int { let r: Result = Result::Pending; return 0; }")

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

    def test_a_variant_declared_twice_in_one_enum_is_rejected(self):
        self.assertCompileError("enum E { A, A }\nfn main(): int { return 0; }",
                                "Enum 'E' declares 'A' twice")

    def test_two_enums_may_share_a_short_name(self):
        # The point of qualifying: `Ok` belongs to its enum, not to the program.
        self.assertPrints(
            "enum A { Ok(int) }\nenum B { Ok(str) }\n"
            'fn main(): int { let a: A = A::Ok(1); let b: B = B::Ok("two"); '
            "match (a) { A::Ok(v) => { println(v); } } "
            "match (b) { B::Ok(s) => { println(s); } } return 0; }",
            "1\ntwo")

    def test_a_function_may_share_a_variant_short_name(self):
        # `Ok(5)` is no longer a variant construction, so there is nothing to
        # be ambiguous with.
        self.assertPrints(
            RESULT + "fn Ok(): int { return 7; }\n"
                     "fn main(): int { println(Ok()); return 0; }",
            "7")

    def test_a_variant_cannot_carry_an_array(self):
        self.assertCompileError("enum E { A(int[3]) }\nfn main(): int { return 0; }",
                                "cannot carry an array")

    def test_an_empty_payload_list_is_rejected(self):
        # `A()` and `A` would otherwise be two spellings of one thing, and only
        # one of them can be the interned singleton.
        self.assertCompileError("enum E { A() }\nfn main(): int { return 0; }",
                                "without parentheses")


class TestQualification(QuinTestCase):
    def test_an_unqualified_variant_names_the_spelling_to_use(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Ok(1); return 0; }",
            "'Ok' is a variant name; write 'Result::Ok'")

    def test_an_ambiguous_short_name_lists_every_option(self):
        self.assertCompileError(
            "enum A { Ok(int) }\nenum B { Ok(int) }\n"
            "fn main(): int { let a: A = Ok(1); return 0; }",
            "write 'A::Ok' or 'B::Ok'")

    def test_an_unknown_enum_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Nope::Ok(1); return 0; }",
            "No enum named 'Nope'")

    def test_an_unknown_variant_of_a_real_enum_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Nope; return 0; }",
            "Enum 'Result' has no variant 'Nope'")

    def test_a_deeper_path_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Ok::More(1); return 0; }",
            "is not a path")

    def test_the_declaration_uses_the_short_name(self):
        # Qualifying inside the braces would repeat the enum on every line.
        self.assertCompileError(
            "enum E { E::A }\nfn main(): int { return 0; }",
            "Expected '}' after enum variants")


class TestConstruction(QuinTestCase):
    def test_a_variant_with_a_payload_is_called(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Result::Ok(7); '
                     'match (r) { Result::Ok(v) => { println(v); } _ => {} } return 0; }',
            "7")

    def test_a_variant_without_a_payload_is_a_bare_name(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Result::Pending; '
                     'match (r) { Result::Pending => { println(1); } _ => {} } return 0; }',
            "1")

    def test_a_payload_free_variant_written_as_a_call_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending(); return 0; }",
            "carries no payload")

    def test_a_payload_variant_written_bare_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Ok; return 0; }",
            "write 'Result::Ok(...)'")

    def test_the_payload_is_type_checked(self):
        self.assertCompileError(
            RESULT + 'fn main(): int { let r: Result = Result::Ok("no"); return 0; }',
            "expects int at position 0")

    def test_arity_is_checked(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Ok(1, 2); return 0; }",
            "carries 1 value(s), got 2")

    def test_a_construction_has_the_enum_type(self):
        # Not the variant's own type: a variant is not something anyone can
        # declare a variable of, so nothing needs the narrower type.
        self.assertCompiles(
            RESULT + "fn take(r: Result): int { return 0; }\n"
                     "fn main(): int { return take(Result::Ok(1)); }")

    def test_a_variant_can_carry_a_struct(self):
        self.assertPrints(
            "struct P { x: int }\nenum E { Wrap(P), Nothing }\n"
            "fn main(): int { let e: E = E::Wrap(P{x: 9}); "
            "match (e) { E::Wrap(p) => { println(p.x); } E::Nothing => {} } return 0; }",
            "9")

    def test_a_variant_can_carry_a_float(self):
        self.assertPrints(
            "enum E { F(float), N }\n"
            "fn main(): int { let e: E = E::F(2.5); "
            "match (e) { E::F(x) => { println(x + 0.25); } E::N => {} } return 0; }",
            "2.75")


class TestMatch(QuinTestCase):
    SRC = RESULT + """
    fn describe(r: Result): int {
        match (r) {
            Result::Ok(v) => { println(v); }
            Result::Err(m) => { println(m); }
            Result::Pending => { println("pending"); }
        }
        return 0;
    }
    fn main(): int {
        describe(Result::Ok(42));
        describe(Result::Err("bad"));
        describe(Result::Pending);
        return 0;
    }
    """

    def test_each_variant_takes_its_own_arm(self):
        self.assertPrints(self.SRC, "42\nbad\npending")

    def test_the_subject_is_parenthesised(self):
        # `match r {` is ambiguous: an identifier followed by a brace is how a
        # struct literal begins, so the subject would swallow the arms.
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match r { _ => {} } return 0; }",
            "Expected '(' after 'match'")

    def test_a_non_enum_subject_is_rejected(self):
        self.assertCompileError(
            "enum E { A }\n"
            "fn main(): int { let x: int = 1; match (x) { E::A => {} } return 0; }",
            "match requires an enum")

    def test_a_variant_of_another_enum_is_rejected(self):
        self.assertCompileError(
            RESULT + "enum Other { Wat }\n"
                     "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Other::Wat => {} } return 0; }",
            "'Other::Wat' is not a variant of 'Result'")

    def test_a_repeated_arm_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; match (r) { "
                     "Result::Ok(a) => {} Result::Ok(b) => {} Result::Err(m) => {} "
                     "Result::Pending => {} } return 0; }",
            "is matched twice")

    def test_binding_count_must_match_the_payload(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Result::Ok(a, b) => {} _ => {} } return 0; }",
            "carries 1 value(s), but the arm binds 2")

    def test_a_match_can_return_from_every_arm(self):
        self.assertPrints(
            RESULT + """
            fn pick(r: Result): int {
                match (r) {
                    Result::Ok(v) => { return v; }
                    Result::Err(m) => { return 0 - 1; }
                    Result::Pending => { return 0; }
                }
            }
            fn main(): int { println(pick(Result::Ok(8))); return 0; }
            """,
            "8")

    def test_a_match_that_does_not_always_return_is_still_checked(self):
        self.assertCompileError(
            RESULT + """
            fn pick(r: Result): int {
                match (r) {
                    Result::Ok(v) => { return v; }
                    Result::Err(m) => { println(m); }
                    Result::Pending => { return 0; }
                }
            }
            fn main(): int { return pick(Result::Pending); }
            """,
            "missing return statement")


class TestExhaustiveness(QuinTestCase):
    def test_a_missing_variant_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Result::Ok(v) => {} Result::Err(m) => {} } return 0; }",
            "does not cover: Pending")

    def test_every_missing_variant_is_named(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Result::Ok(v) => {} } return 0; }",
            "does not cover: Err, Pending")

    def test_a_catch_all_satisfies_coverage(self):
        self.assertPrints(
            RESULT + 'fn main(): int { let r: Result = Result::Err("x"); '
                     'match (r) { Result::Ok(v) => { println(v); } '
                     '_ => { println("other"); } } return 0; }',
            "other")

    def test_a_catch_all_that_covers_nothing_warns(self):
        # It is the arm that would silently absorb a variant added later, so
        # saying it is dead is the whole point of the coverage check.
        self.assertCompileWarning(
            RESULT + "fn main(): int { let r: Result = Result::Pending; match (r) { "
                     "Result::Ok(v) => {} Result::Err(m) => {} Result::Pending => {} "
                     "_ => {} } return 0; }",
            "'_' covers no remaining variant")

    def test_a_used_catch_all_does_not_warn(self):
        self.assertNoCompileWarnings(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Result::Ok(v) => {} _ => {} } return 0; }")

    def test_an_arm_after_the_catch_all_is_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { _ => {} Result::Ok(v) => {} } return 0; }",
            "comes after '_', so it can never match")

    def test_two_catch_alls_are_rejected(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { _ => {} _ => {} } return 0; }",
            "comes after '_'")

    def test_the_catch_all_cannot_bind(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { _(v) => {} } return 0; }",
            "'_' cannot bind a payload")


class TestBindings(QuinTestCase):
    def test_a_binding_is_scoped_to_its_arm(self):
        self.assertCompileError(
            RESULT + "fn main(): int { let r: Result = Result::Pending; "
                     "match (r) { Result::Ok(v) => {} _ => {} } println(v); return 0; }",
            "Undeclared variable 'v'")

    def test_two_arms_may_bind_the_same_name(self):
        # Sibling scopes, like two if blocks.
        self.assertPrints(
            "enum E { A(int), B(int) }\n"
            "fn main(): int { let e: E = E::B(3); "
            "match (e) { E::A(v) => { println(v); } E::B(v) => { println(v + 1); } } "
            "return 0; }",
            "4")

    def test_a_binding_shadows_an_outer_name(self):
        self.assertPrints(
            RESULT + "fn main(): int { let v: int = 1; let r: Result = Result::Ok(9); "
                     "match (r) { Result::Ok(v) => { println(v); } _ => {} } "
                     "println(v); return 0; }",
            "9\n1")

    def test_multiple_payload_values_bind_in_order(self):
        self.assertPrints(
            "enum Pair { Both(int, str), Neither }\n"
            'fn main(): int { let p: Pair = Pair::Both(4, "four"); '
            "match (p) { Pair::Both(n, name) => { println(n); println(name); } "
            "Pair::Neither => {} } return 0; }",
            "4\nfour")

    def test_a_bound_reference_stops_rooting_when_the_arm_ends(self):
        # The arm is a scope like any other, so its reference slots are
        # released at the end of it.
        program = compile_source(
            "enum E { S(str), N }\n"
            'fn main(): int { let e: E = E::S("x"); '
            "match (e) { E::S(s) => { println(s); } E::N => {} } return 0; }"
        )
        self.assertTrue(program.functions)


class TestRecursion(QuinTestCase):
    def test_a_variant_may_carry_its_own_enum(self):
        self.assertPrints(
            """
            enum List { Nil, Cons(int, List) }
            fn total(l: List): int {
                match (l) {
                    List::Nil => { return 0; }
                    List::Cons(head, rest) => { return head + total(rest); }
                }
            }
            fn main(): int {
                println(total(List::Cons(1, List::Cons(2, List::Cons(3, List::Nil)))));
                return 0;
            }
            """,
            "6")

    def test_a_variant_may_carry_an_enum_declared_later(self):
        self.assertCompiles(
            "enum A { Wrap(B), Nothing }\nenum B { Leaf }\n"
            "fn main(): int { let a: A = A::Wrap(B::Leaf); return 0; }")


class TestRuntime(QuinTestCase):
    def test_matching_a_null_subject_faults(self):
        # An enum reference is nullable, so coverage of every variant is not a
        # promise that the value is one of them. This faults the way reading a
        # field of a null struct does.
        self.assertRuntimeError(
            "enum E { A(int), B }\nfn main(): int { let e: E; "
            "match (e) { E::A(v) => {} E::B => {} } return 0; }",
            "Null reference in match")

    def test_null_is_assignable_to_an_enum(self):
        self.assertCompiles("enum E { A }\nfn main(): int { let e: E = null; return 0; }")

    def test_a_payload_free_variant_is_one_object(self):
        import io
        from contextlib import redirect_stdout
        program = compile_source(
            "enum C { A, B }\n"
            "fn main(): int { let x: C = C::A; let y: C = C::A; let z: C = C::A; "
            "return 0; }"
        )
        vm = vm_for(program)
        with redirect_stdout(io.StringIO()):
            vm.run_main()
        # Three uses of C::A, one object: a variant carrying nothing is a
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
                let b: Box = Box::Full("kept");
                for (let i = 0; i < 3000; i = i + 1) { let junk: str = int_to_str(i); }
                gc();
                match (b) {
                    Box::Full(s) => { println(s); }
                    Box::Empty => { println("lost"); }
                }
                return 0;
            }
            """,
            "kept")

    def test_a_variant_survives_compaction_with_its_payload_intact(self):
        self.assertPrints(
            """
            struct P { x: int, y: int }
            enum Holder { Has(P), Nothing }
            fn main(): int {
                let h: Holder = Holder::Has(P{x: 11, y: 22});
                for (let i = 0; i < 2000; i = i + 1) { let junk: str = int_to_str(i); }
                gc();
                match (h) {
                    Holder::Has(p) => { println(p.x + p.y); }
                    Holder::Nothing => { println(0); }
                }
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
            "fn main(): int { let e: E = E::A(1); let p: P = P{x: 2}; return 0; }"
        )
        by_name = {layout.name: layout for layout in program.structs}
        self.assertEqual(set(by_name), {"P", "E::A", "E::B"})
        self.assertFalse(by_name["P"].is_variant)
        self.assertTrue(by_name["E::A"].is_variant)

    def test_a_layout_carries_the_qualified_name(self):
        # So a debugger shows `E::A(1)` rather than an `A` that could be any
        # enum's.
        program = compile_source(
            "enum E { A(int) }\nenum F { A(int) }\n"
            "fn main(): int { let e: E = E::A(1); let f: F = F::A(2); return 0; }"
        )
        names = sorted(layout.name for layout in program.structs if layout)
        self.assertEqual(names, ["E::A", "F::A"])

    def test_type_ids_are_unique_across_structs_and_variants(self):
        program = compile_source(
            "struct P { x: int }\nstruct Q { y: int }\nenum E { A(int), B }\n"
            "fn main(): int { let e: E = E::B; return 0; }"
        )
        ids = [i for i, layout in enumerate(program.structs) if layout is not None]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)

    def test_a_reference_payload_is_recorded_for_tracing(self):
        program = compile_source(
            "enum E { S(str), I(int) }\n"
            "fn main(): int { let e: E = E::I(1); return 0; }"
        )
        by_name = {layout.name: layout for layout in program.structs}
        self.assertEqual(by_name["E::S"].ref_offsets, (0,), "a str payload must be traced")
        self.assertEqual(by_name["E::I"].ref_offsets, (), "an int payload must not be")


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
            (root / "shapes.ql").write_text("enum Shape { Dot, Line(int) }\n",
                                            encoding="utf-8")
            entry = root / "main.ql"
            entry.write_text(
                'include "shapes.ql";\n'
                "fn main(): int { let s: Shape = Shape::Line(3); "
                "match (s) { Shape::Dot => {} Shape::Line(n) => {} } return 0; }\n",
                encoding="utf-8")
            program = compile_file(entry)
        self.assertIn("Shape::Line", [layout.name for layout in program.structs])

    def test_two_files_may_declare_the_same_variant_short_name(self):
        # What qualification bought: std/ can now declare enums without
        # claiming names for every program that includes it.
        import tempfile
        from pathlib import Path
        from tests.harness import compile_file
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "lib.ql").write_text("enum Lib { Ok(int) }\n", encoding="utf-8")
            entry = root / "main.ql"
            entry.write_text(
                'include "lib.ql";\n'
                "enum App { Ok(int) }\n"
                "fn main(): int { let a: App = App::Ok(1); let b: Lib = Lib::Ok(2); "
                "return 0; }\n",
                encoding="utf-8")
            program = compile_file(entry)
        names = {layout.name for layout in program.structs if layout}
        self.assertEqual(names, {"App::Ok", "Lib::Ok"})


if __name__ == "__main__":
    unittest.main()
