"""Generics by monomorphization.

A generic declaration is a template. It is never compiled as written: each use
with concrete type arguments produces a copy under a mangled name, and
downstream of sema nothing knows what a template is -- `Vec<int>` is an ordinary
struct with its own type id, and `map<int,str>` an ordinary entry in the
function table.

The cases worth the most here are the ones where two instantiations of one
declaration have to differ: a `Vec<str>` holds a reference where a `Vec<int>`
holds a value, and the collector has to see that.
"""

import unittest

from compiler import ast as A
from compiler.bytecode import OpCode
from compiler.codegen_vm import CodegenError, MAX_TYPE_ID
from compiler.compiler_types import (
    generic_application, substitute_type_name, unify_type_name, UnknownTypeError,
)
from compiler.lexer import Lexer
from compiler.parser import Parser
from tests.harness import QuinTestCase, compile_source, main_wrapping

VEC = """
struct Vec<T> {
    data: Array<T>,
    len: int,
}

fn vec_new<T>(capacity: int): Vec<T> {
    return Vec { data: array_new(capacity), len: 0 };
}

fn vec_push<T>(v: Vec<T>, value: T): void {
    v.data[v.len] = value;
    v.len = v.len + 1;
}

fn vec_get<T>(v: Vec<T>, i: int): T {
    return v.data[i];
}
"""

OPTION = "enum Option<T> { Some(T), None }\n"


def emitted(source: str):
    return [f.name for f in compile_source(source).functions]


class TestSpellings(QuinTestCase):
    def test_an_application_splits_into_base_and_arguments(self):
        self.assertEqual(generic_application("Map<K,Vec<V>>"), ("Map", ["K", "Vec<V>"]))

    def test_a_function_type_ending_in_one_is_not_an_application(self):
        self.assertIsNone(generic_application("fn(int):Vec<int>"))

    def test_an_empty_argument_is_refused(self):
        with self.assertRaises(UnknownTypeError):
            generic_application("Vec<>")

    def test_substitution_reaches_into_nested_spellings(self):
        self.assertEqual(
            substitute_type_name("Vec<fn(T):Array<U>>", {"T": "int", "U": "str"}),
            "Vec<fn(int):Array<str>>")

    def test_substitution_is_not_textual(self):
        # A name that merely contains the parameter's letters is left alone.
        self.assertEqual(substitute_type_name("Total", {"T": "int"}), "Total")

    def test_unification_binds_through_structure(self):
        subs = {}
        self.assertTrue(unify_type_name("fn(T):Vec<U>", "fn(int):Vec<str>",
                                        {"T", "U"}, subs))
        self.assertEqual(subs, {"T": "int", "U": "str"})

    def test_unification_refuses_a_second_binding(self):
        subs = {}
        unify_type_name("T", "int", {"T"}, subs)
        self.assertFalse(unify_type_name("T", "str", {"T"}, subs))


class TestParsing(QuinTestCase):
    def _parse(self, source: str):
        return Parser(Lexer(source).tokenize()).parse()

    def test_declarations_bind_type_parameters(self):
        p = self._parse("struct S<T> { a: T }\nenum E<T> { V(T) }\n"
                        "fn f<T, U>(a: T): U { return a; }\n")
        self.assertEqual(p.structs[0].type_params, ["T"])
        self.assertEqual(p.enums[0].type_params, ["T"])
        self.assertEqual(p.functions[0].type_params, ["T", "U"])

    def test_a_duplicate_type_parameter_is_refused(self):
        self.assertCompileError("fn f<T, T>(a: T): T { return a; }\n"
                                + main_wrapping(""),
                                "Duplicate type parameter 'T'")

    def test_a_turbofish_is_not_a_qualified_name(self):
        call = self._parse("fn main(): int { f::<int>(1); return 0; }").functions[0].body[0].expr
        self.assertEqual((call.callee, call.type_args), ("f", ["int"]))

    def test_a_qualified_name_still_parses(self):
        init = self._parse("fn main(): int { let x = E::V; return 0; }").functions[0].body[0].init
        self.assertEqual(init.name, "E::V")

    def test_a_struct_literal_takes_its_arguments_in_its_name(self):
        lit = self._parse("fn main(): int { let v = Vec::<int> { len: 0 }; return 0; }"
                          ).functions[0].body[0].init
        self.assertEqual(lit.struct_name, "Vec<int>")

    def test_substitution_leaves_the_template_alone(self):
        fn = self._parse("fn f<T>(a: Vec<T>): T { return a; }").functions[0]
        import copy
        clone = copy.deepcopy(fn)
        A.substitute_types(clone, lambda n: substitute_type_name(n, {"T": "str"}))
        self.assertEqual(clone.params[0].type_name, "Vec<str>")
        self.assertEqual(fn.params[0].type_name, "Vec<T>")


class TestInference(QuinTestCase):
    def test_from_an_argument(self):
        self.assertPrints(VEC + main_wrapping("""
            let v: Vec<int> = vec_new(2);
            vec_push(v, 7);
            println(vec_get(v, 0));
        """), "7")

    def test_from_the_expected_type(self):
        # Nothing about vec_new(2) says what it builds; the annotation does.
        self.assertPrints(VEC + main_wrapping("""
            let v: Vec<str> = vec_new(2);
            vec_push(v, "hi");
            println(vec_get(v, 0));
        """), "hi")

    def test_from_a_turbofish(self):
        self.assertPrints(VEC + main_wrapping("""
            let v = vec_new::<str>(2);
            vec_push(v, "explicit");
            println(vec_get(v, 0));
        """), "explicit")

    def test_a_turbofish_beats_the_expected_type(self):
        self.assertCompileError(VEC + main_wrapping(
            "let v: Vec<int> = vec_new::<str>(2);"),
            "Type mismatch in initializer")

    def test_when_nothing_says(self):
        self.assertCompileError(VEC + main_wrapping("let v = vec_new(2);"),
                                "Cannot tell what 'T' is in this call to 'vec_new'")

    def test_a_conflicting_binding_is_caught_at_the_call(self):
        self.assertCompileError(
            "fn pair<T>(a: T, b: T): T { return a; }\n"
            + main_wrapping('println(pair(1, "x"));'),
            "Argument type mismatch in 'pair<int>'")

    def test_a_function_value_carries_its_binding(self):
        self.assertPrints("""
            fn twice<T>(f: fn(T): T, x: T): T { return f(f(x)); }
            fn inc(n: int): int { return n + 1; }
            fn main(): int { println(twice(inc, 5)); return 0; }
        """, "7")

    def test_a_turbofish_on_a_plain_function_is_refused(self):
        self.assertCompileError(
            "fn f(a: int): int { return a; }\n" + main_wrapping("println(f::<int>(1));"),
            "'f' takes no type arguments")

    def test_wrong_type_argument_count(self):
        self.assertCompileError(
            "struct Pair<A, B> { a: A, b: B }\n" + main_wrapping(
                "let p: Pair<int> = Pair::<int,int> { a: 1, b: 2 };"),
            "'Pair' takes 2 type argument(s), got 1")


class TestInstantiation(QuinTestCase):
    def test_a_template_emits_no_code(self):
        names = emitted(VEC + main_wrapping("println(1);"))
        self.assertEqual([n for n in names if n.startswith("vec")], [],
                         "nothing used them, so nothing should exist")

    def test_one_instantiation_per_argument_list(self):
        names = emitted(VEC + main_wrapping("""
            let a: Vec<int> = vec_new(1);
            let b: Vec<int> = vec_new(1);
            let c: Vec<str> = vec_new(1);
        """))
        self.assertEqual(sorted(n for n in names if n.startswith("vec_new")),
                         ["vec_new<int>", "vec_new<str>"])

    def test_instantiations_are_distinct_functions(self):
        names = emitted(VEC + """
            fn main(): int {
                let a: Vec<int> = vec_new(1);
                let b: Vec<str> = vec_new(1);
                vec_push(a, 1);
                vec_push(b, "x");
                return 0;
            }
        """)
        self.assertIn("vec_push<int>", names)
        self.assertIn("vec_push<str>", names)

    def test_a_mangled_call_reaches_the_right_one(self):
        self.assertPrints(VEC + main_wrapping("""
            let a: Vec<int> = vec_new(2);
            let b: Vec<str> = vec_new(2);
            vec_push(a, 42);
            vec_push(b, "text");
            println(vec_get(a, 0));
            println(vec_get(b, 0));
        """), "42", "text")

    def test_nested_instantiation(self):
        self.assertPrints(VEC + main_wrapping("""
            let outer: Vec<Vec<int>> = vec_new(1);
            let inner: Vec<int> = vec_new(1);
            vec_push(inner, 5);
            vec_push(outer, inner);
            println(vec_get(vec_get(outer, 0), 0));
        """), "5")

    def test_a_recursive_template_terminates(self):
        # Node<T> mentions itself, so registering it before resolving its fields
        # is what makes this finish.
        self.assertPrints("""
            struct Node<T> { value: T, next: Node<T> }
            fn main(): int {
                let n: Node<int> = Node { value: 1, next: null };
                let head: Node<int> = Node { value: 2, next: n };
                println(head.next.value);
                return 0;
            }
        """, "1")

    def test_runaway_instantiation_is_capped(self):
        message = self.assertCompileError("""
            struct Box<T> { v: T }
            fn deeper<T>(x: T): int { let b: Box<T> = Box { v: x }; return deeper(b); }
            fn main(): int { println(deeper(1)); return 0; }
        """, "is more than 32 deep")
        self.assertIn("... and", message, "the chain should be elided, not printed whole")

    def test_main_may_not_be_generic(self):
        self.assertCompileError("fn main<T>(): int { return 0; }",
                                "must not be generic")


class TestTheCollectorSeesEachInstantiation(QuinTestCase):
    def test_two_instantiations_get_distinct_layouts(self):
        program = compile_source(VEC + main_wrapping("""
            let a: Vec<int> = vec_new(1);
            let b: Vec<str> = vec_new(1);
        """))
        # A layout's type id is its index in this table, and that id is what a
        # heap header carries -- so two instantiations occupying one slot would
        # be two structs the collector could not tell apart.
        ids = {s.name: i for i, s in enumerate(program.structs) if s}
        self.assertNotEqual(ids["Vec<int>"], ids["Vec<str>"])
        layouts = {s.name: s for s in program.structs if s}
        self.assertEqual([f.type_name for f in layouts["Vec<int>"].fields],
                         ["Array<int>", "int"])
        self.assertEqual([f.type_name for f in layouts["Vec<str>"].fields],
                         ["Array<str>", "int"])

    def test_a_value_payload_and_a_reference_payload_differ(self):
        program = compile_source(OPTION + main_wrapping("""
            let a: Option<int> = Option::Some(1);
            let b: Option<str> = Option::Some("x");
        """))
        layouts = {s.name: s for s in program.structs if s}
        self.assertEqual(layouts["Option<int>::Some"].ref_offsets, ())
        self.assertEqual(layouts["Option<str>::Some"].ref_offsets, (0,))

    def test_stack_maps_differ_per_instantiation(self):
        program = compile_source(VEC + main_wrapping("""
            let a: Vec<int> = vec_new(1);
            let b: Vec<str> = vec_new(1);
            vec_push(a, 1);
            vec_push(b, "x");
        """))
        fns = {f.name: f for f in program.functions}
        # Both root the vector; only the str instantiation roots its value.
        self.assertEqual(fns["vec_push<int>"].ref_slots, (0,))
        self.assertEqual(fns["vec_push<str>"].ref_slots, (0, 1))

    def test_references_in_an_instantiation_survive_collection(self):
        self.assertPrints(VEC + main_wrapping("""
            let v: Vec<str> = vec_new(3);
            vec_push(v, "kept " + int_to_str(1));
            vec_push(v, "kept " + int_to_str(2));
            gc();
            println(vec_get(v, 0));
            println(vec_get(v, 1));
        """), "kept 1", "kept 2")

    def test_the_type_id_ceiling_is_refused(self):
        # 65536 instantiations is not reachable through source, so the table is
        # built past the limit directly.
        from compiler.codegen_vm import CodeGenVM
        from compiler.compiler_types import StructInfo
        from compiler.sema import Context
        ctx = Context()
        ctx.structs["Huge"] = StructInfo("Huge", type_id=MAX_TYPE_ID + 1)
        with self.assertRaises(CodegenError) as cm:
            CodeGenVM().generate(A.Program([], [], [], []), ctx)
        self.assertIn("16-bit type id", str(cm.exception))


class TestGenericEnums(QuinTestCase):
    def test_a_payload_fixes_the_parameter(self):
        self.assertPrints(OPTION + main_wrapping("""
            let o: Option<int> = Option::Some(3);
            match (o) {
                Option::Some(n) => { println(n); }
                Option::None => { println("none"); }
            }
        """), "3")

    def test_an_empty_variant_takes_the_expected_type(self):
        self.assertPrints(OPTION + main_wrapping("""
            let o: Option<str> = Option::None;
            match (o) {
                Option::Some(s) => { println(s); }
                Option::None => { println("none"); }
            }
        """), "none")

    def test_an_empty_variant_with_nothing_to_say(self):
        self.assertCompileError(OPTION + main_wrapping("let o = Option::None;"),
                                "Cannot tell what 'T' is in 'Option::None'")

    def test_two_parameters(self):
        self.assertPrints("""
            enum Result<T, E> { Ok(T), Err(E) }
            fn main(): int {
                let r: Result<int, str> = Result::Err("bad");
                match (r) {
                    Result::Ok(n) => { println(n); }
                    Result::Err(m) => { println(m); }
                }
                return 0;
            }
        """, "bad")

    def test_a_missing_arm_is_still_caught(self):
        self.assertCompileError(OPTION + main_wrapping("""
            let o: Option<int> = Option::Some(1);
            match (o) { Option::Some(n) => { println(n); } }
        """), "None")

    def test_a_duplicated_arm_is_still_caught(self):
        self.assertCompileError(OPTION + main_wrapping("""
            let o: Option<int> = Option::Some(1);
            match (o) {
                Option::Some(n) => { println(n); }
                Option::Some(m) => { println(m); }
                Option::None => { println(0); }
            }
        """), "matched twice")


class TestErrorsInsideTemplates(QuinTestCase):
    def test_the_chain_names_the_instantiation_and_the_site(self):
        message = self.assertCompileError("""
            struct Point { x: int }
            fn biggest<T>(a: T, b: T): T { if (a < b) { return b; } return a; }
            fn main(): int {
                let p: Point = Point { x: 1 };
                let q: Point = Point { x: 2 };
                println(biggest(p, q).x);
                return 0;
            }
        """, "Relational operators do not apply")
        self.assertIn("in biggest<Point>", message)
        self.assertIn("instantiated at", message)

    def test_the_same_template_is_fine_at_another_type(self):
        self.assertPrints("""
            fn biggest<T>(a: T, b: T): T { if (a < b) { return b; } return a; }
            fn main(): int { println(biggest(3, 9)); return 0; }
        """, "9")


class TestDebuggerNeedsNoChange(QuinTestCase):
    def test_a_generic_struct_shows_its_fields(self):
        from tests.harness import debug_session
        out = debug_session(OPTION + """
            struct Pair<T> { a: T, b: T }
            fn main(): int {
                let p: Pair<int> = Pair { a: 4, b: 9 };
                println(p.a);
                return 0;
            }
        """, ["break 6", "continue", "print p", "quit"])
        self.assertIn("Pair<int>", out)
        self.assertIn("9", out)


if __name__ == "__main__":
    unittest.main()
