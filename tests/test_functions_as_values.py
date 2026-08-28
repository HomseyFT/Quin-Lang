"""Functions as values: a name in a non-call position is the function it names.

A function value is one word holding an index into the program's function
table -- not a heap address. That single fact is what most of this file is
about: it is why there is no capture, why the collector never traces one, and
why calling through a variable costs one extra instruction rather than an
allocation. The type system carries the signature, so a call through a
variable is checked as strictly as a direct one; only the identity is deferred.
"""

import unittest

from compiler.compiler_types import (
    Bool, Int, Void, func_type, is_func_type, is_reference_type, type_from_name,
    word_count,
)
from compiler.bytecode import OpCode
from tests.harness import QuinTestCase, compile_source

ADD = "fn add(a: int, b: int): int { return a + b; }\n"
MUL = "fn mul(a: int, b: int): int { return a * b; }\n"
APPLY = "fn apply(f: fn(int, int): int, x: int, y: int): int { return f(x, y); }\n"


class TestTheType(unittest.TestCase):
    def test_a_signature_has_one_spelling(self):
        # An omitted return type is void, so both spellings are one type and
        # comparing types as names stays sound.
        self.assertEqual(type_from_name("fn(int)"), type_from_name("fn(int):void"))

    def test_the_canonical_spelling_drops_spaces(self):
        self.assertEqual(type_from_name("fn(int,int):int").name, "fn(int,int):int")

    def test_a_function_type_nests(self):
        t = type_from_name("fn(fn(int):int,int):bool")
        self.assertTrue(is_func_type(t))
        self.assertEqual([p.name for p in t.params], ["fn(int):int", "int"])
        self.assertEqual(t.ret, Bool)

    def test_it_is_one_word_and_never_traced(self):
        # The whole reason the type is this cheap. If this ever becomes True
        # the collector would follow a function index into the heap.
        t = func_type([Int], Int)
        self.assertEqual(word_count(t), 1)
        self.assertFalse(is_reference_type(t))

    def test_void_is_not_a_parameter_type(self):
        with self.assertRaises(Exception):
            type_from_name("fn(void):int")

    def test_an_array_is_not_a_parameter_type(self):
        with self.assertRaises(Exception):
            type_from_name("fn(int[3]):int")

    def test_a_malformed_signature_is_refused(self):
        for bad in ("fn(int", "fn(int):", "fn(int,):int"):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                type_from_name(bad)


class TestCalling(QuinTestCase):
    def test_a_function_passed_as_an_argument(self):
        self.assertPrints(
            ADD + APPLY + "fn main(): int { println(apply(add, 2, 3)); return 0; }",
            "5")

    def test_which_function_is_the_caller_s_choice(self):
        self.assertPrints(
            ADD + MUL + APPLY +
            "fn main(): int { println(apply(mul, 2, 3)); return 0; }",
            "6")

    def test_a_function_stored_in_a_local(self):
        self.assertPrints(
            ADD + "fn main(): int { let f: fn(int, int): int = add;"
                  " println(f(4, 5)); return 0; }",
            "9")

    def test_a_function_returned_from_a_function(self):
        self.assertPrints(
            ADD + MUL +
            "fn pick(sum: bool): fn(int, int): int {"
            "  if (sum) { return add; } return mul; }\n"
            "fn main(): int { let f: fn(int, int): int = pick(false);"
            " println(f(4, 5)); return 0; }",
            "20")

    def test_a_call_through_a_variable_recurses(self):
        self.assertPrints(
            "fn down(f: fn(int): int, n: int): int {"
            "  if (n <= 0) { return 0; } return n + down(f, f(n)); }\n"
            "fn dec(n: int): int { return n - 1; }\n"
            "fn main(): int { println(down(dec, 4)); return 0; }",
            "10")

    def test_a_void_function_value(self):
        self.assertPrints(
            "fn shout(s: str): void { println(s); }\n"
            "fn twice(f: fn(str): void, s: str): void { f(s); f(s); }\n"
            "fn main(): int { twice(shout, \"hi\"); return 0; }",
            "hi", "hi")

    def test_a_zero_argument_function_value(self):
        self.assertPrints(
            "fn answer(): int { return 42; }\n"
            "fn main(): int { let f: fn(): int = answer;"
            " println(f()); return 0; }",
            "42")

    def test_a_float_argument_crosses_an_indirect_call(self):
        # A float is one stack entry and two slots, so the calling convention
        # is the interesting part; CALL_INDIRECT shares it with CALL.
        self.assertPrints(
            "fn half(x: float): float { return x / 2.0; }\n"
            "fn use(f: fn(float): float, x: float): float { return f(x); }\n"
            "fn main(): int { println(use(half, 5.0)); return 0; }",
            "2.5")

    def test_a_struct_field_holds_a_function(self):
        self.assertPrints(
            ADD + "struct Op { apply: fn(int, int): int, name: str }\n"
            "fn main(): int { let o: Op = Op { apply: add, name: \"+\" };"
            " let f: fn(int, int): int = o.apply;"
            " println(f(1, 2)); println(o.name); return 0; }",
            "3", "+")


class TestTypeChecking(QuinTestCase):
    def test_too_few_arguments(self):
        self.assertCompileError(
            ADD + "fn main(): int { let f: fn(int, int): int = add;"
                  " println(f(1)); return 0; }",
            "expects 2 args, got 1")

    def test_a_wrong_argument_type(self):
        self.assertCompileError(
            ADD + "fn main(): int { let f: fn(int, int): int = add;"
                  " println(f(1, true)); return 0; }",
            "Argument type mismatch")

    def test_a_mismatched_signature_is_not_assignable(self):
        self.assertCompileError(
            ADD + "fn main(): int { let f: fn(int): int = add; return 0; }",
            "fn(int):int")

    def test_a_differing_return_type_is_a_different_type(self):
        self.assertCompileError(
            ADD + "fn main(): int { let f: fn(int, int): bool = add; return 0; }",
            "Type mismatch")

    def test_calling_a_non_function_variable(self):
        self.assertCompileError(
            "fn main(): int { let n: int = 3; println(n(1)); return 0; }",
            "not a function")

    def test_a_builtin_is_not_a_function_value(self):
        # Builtins lower to instructions at the call site, so there is no index
        # to refer to. Saying so beats 'undeclared'.
        self.assertCompileError(
            "fn main(): int { let f: fn(str): int = str_len; return 0; }",
            "is a builtin, not a function value")

    def test_an_unknown_name_is_still_undeclared(self):
        self.assertCompileError(
            "fn main(): int { let f: fn(int): int = nosuch; return 0; }",
            "Undeclared variable")

    def test_a_variable_shadows_a_function_of_the_same_name(self):
        # The rule everywhere else in the language, so a call obeys it too
        # rather than quietly reaching past the local to the function.
        self.assertCompileError(
            "fn f(): int { return 1; }\n"
            "fn main(): int { let f: int = 3; return f(); }",
            "not a function")


class TestCodegen(QuinTestCase):
    def test_a_direct_call_still_uses_CALL(self):
        # The indirect path must not cost the ordinary case anything.
        program = compile_source(ADD + "fn main(): int { return add(1, 2); }")
        ops = [i.op for i in program.code]
        self.assertIn(OpCode.CALL, ops)
        self.assertNotIn(OpCode.CALL_INDIRECT, ops)

    def test_a_call_through_a_variable_uses_CALL_INDIRECT(self):
        program = compile_source(
            ADD + "fn main(): int { let f: fn(int, int): int = add;"
                  " return f(1, 2); }")
        self.assertIn(OpCode.CALL_INDIRECT, [i.op for i in program.code])

    def test_a_function_value_is_not_a_gc_root(self):
        # A fn slot holding an index the collector mistook for an address is
        # the failure this rules out.
        program = compile_source(
            ADD + "struct Op { apply: fn(int, int): int, name: str }\n"
            "fn main(): int { let f: fn(int, int): int = add;"
            " let o: Op = Op { apply: add, name: \"+\" }; return 0; }")
        main = next(f for f in program.functions if f.name == "main")
        slots = {l.name: l.slot for l in main.locals_}
        self.assertNotIn(slots["f"], main.ref_slots)
        self.assertIn(slots["o"], main.ref_slots)

        op = next(s for s in program.structs if s.name == "Op")
        offsets = {f.name: f.offset for f in op.fields}
        self.assertNotIn(offsets["apply"], op.ref_offsets)
        self.assertIn(offsets["name"], op.ref_offsets)

    def test_a_function_value_survives_a_collection(self):
        self.assertPrints(
            ADD + "struct Node { next: Node }\n"
            "fn churn(): void { let n: Node = Node { next: null }; }\n"
            "fn main(): int {\n"
            "    let f: fn(int, int): int = add;\n"
            "    let i: int = 0;\n"
            "    while (i < 2000) { churn(); i = i + 1; }\n"
            "    gc();\n"
            "    println(f(20, 22));\n"
            "    return 0;\n"
            "}",
            "42")


class TestStdList(QuinTestCase):
    LIST = ('include "std/list.ql";\n'
            "fn double(n: int): int { return n * 2; }\n"
            "fn odd(n: int): bool { return n % 2 != 0; }\n"
            "fn show(n: int): void { print(n); }\n"
            "fn xs(): IntList { return list_push(list_push(list_push("
            "list_empty(), 3), 2), 1); }\n")

    def test_map(self):
        self.assertPrints(
            self.LIST + "fn main(): int { list_println(list_map(xs(), double));"
                        " return 0; }",
            "[2, 4, 6]")

    def test_map_of_an_empty_list(self):
        self.assertPrints(
            self.LIST + "fn main(): int { list_println(list_map(list_empty(),"
                        " double)); return 0; }",
            "[]")

    def test_filter(self):
        self.assertPrints(
            self.LIST + "fn main(): int { list_println(list_filter(xs(), odd));"
                        " return 0; }",
            "[1, 3]")

    def test_filter_keeping_nothing(self):
        self.assertPrints(
            self.LIST + "fn none(n: int): bool { return false; }\n"
                        "fn main(): int { list_println(list_filter(xs(), none));"
                        " return 0; }",
            "[]")

    def test_foreach(self):
        self.assertPrints(
            self.LIST + "fn main(): int { list_foreach(xs(), show);"
                        " println(\"\"); return 0; }",
            "123")

    def test_the_original_list_is_unchanged(self):
        self.assertPrints(
            self.LIST + "fn main(): int { let l: IntList = xs();"
                        " list_map(l, double); list_println(l); return 0; }",
            "[1, 2, 3]")


if __name__ == "__main__":
    unittest.main()
