"""Type checking, the entry-point contract, and the array restrictions."""

import unittest

from tests.harness import QuinTestCase


class TestEntryPoint(QuinTestCase):
    def test_missing_main(self):
        self.assertCompileError("fn f(): int { return 1; }", "Missing entry point 'main'")

    def test_main_takes_no_parameters(self):
        self.assertCompileError(
            "fn main(x: int): int { return 0; }", "must not take parameters"
        )

    def test_main_must_return_int_or_void(self):
        self.assertCompileError('fn main(): str { return "x"; }', "must return int or void")

    def test_main_returning_int_is_allowed(self):
        self.assertCompiles("fn main(): int { return 0; }")

    def test_main_returning_void_is_allowed(self):
        self.assertCompiles("fn main(): void { }")

    def test_main_return_value_is_the_exit_value(self):
        from tests.harness import run_source
        self.assertEqual(run_source("fn main(): int { return 3; }").exit_value, 3)

    def test_negative_exit_value_is_signed(self):
        from tests.harness import run_source
        self.assertEqual(run_source("fn main(): int { return 0 - 1; }").exit_value, -1)


class TestFunctions(QuinTestCase):
    def test_redefinition(self):
        self.assertCompileError(
            "fn f(): int { return 1; } fn f(): int { return 2; } fn main(): int { return 0; }",
            "Redefinition of function 'f'",
        )

    def test_cannot_shadow_a_builtin(self):
        self.assertCompileError(
            "fn alloc(n: int): heapptr { return n; } fn main(): int { return 0; }",
            "Redefinition of function 'alloc'",
        )

    def test_call_before_definition(self):
        self.assertPrints(
            "fn main(): int { println(f()); return 0; } fn f(): int { return 9; }", "9"
        )

    def test_recursion(self):
        self.assertPrints(
            """
            fn fact(n: int): int {
                if (n <= 1) { return 1; }
                return n * fact(n - 1);
            }
            fn main(): int { println(fact(5)); return 0; }
            """,
            "120",
        )

    def test_unknown_function(self):
        self.assertCompileError(
            "fn main(): int { nope(); return 0; }", "Call to undeclared function 'nope'"
        )

    def test_argument_count(self):
        self.assertCompileError(
            "fn f(a: int): int { return a; } fn main(): int { f(1, 2); return 0; }",
            "expects 1 args, got 2",
        )

    def test_argument_type(self):
        self.assertCompileError(
            "fn f(a: int): int { return a; } fn main(): int { f(true); return 0; }",
            "Argument type mismatch",
        )

    def test_duplicate_parameter(self):
        self.assertCompileError(
            "fn f(a: int, a: int): int { return a; } fn main(): int { return 0; }",
            "Redeclaration of variable 'a'",
        )

    def test_arguments_are_passed_in_order(self):
        self.assertPrints(
            """
            fn sub(a: int, b: int): int { return a - b; }
            fn main(): int { println(sub(10, 3)); return 0; }
            """,
            "7",
        )


class TestReturnChecking(QuinTestCase):
    def test_missing_return(self):
        self.assertCompileError(
            "fn f(): int { println(1); } fn main(): int { return 0; }",
            "missing return statement",
        )

    def test_if_without_else_is_not_enough(self):
        self.assertCompileError(
            "fn f(): int { if (true) { return 1; } } fn main(): int { return 0; }",
            "missing return statement",
        )

    def test_if_with_both_branches_returning_is_enough(self):
        self.assertCompiles(
            "fn f(): int { if (true) { return 1; } else { return 2; } } "
            "fn main(): int { return 0; }"
        )

    def test_while_never_counts_as_returning(self):
        self.assertCompileError(
            "fn f(): int { while (true) { return 1; } } fn main(): int { return 0; }",
            "missing return statement",
        )

    def test_void_function_may_omit_return(self):
        self.assertCompiles("fn f(): void { } fn main(): int { return 0; }")

    def test_void_function_cannot_return_a_value(self):
        self.assertCompileError(
            "fn f(): void { return 1; } fn main(): int { return 0; }",
            "Void function cannot return a value",
        )

    def test_non_void_function_cannot_return_bare(self):
        self.assertCompileError(
            "fn f(): int { return; } fn main(): int { return 0; }",
            "Expected return value of type int",
        )

    def test_return_type_mismatch(self):
        self.assertCompileError(
            "fn f(): int { return true; } fn main(): int { return 0; }",
            "Return type mismatch",
        )


class TestVariables(QuinTestCase):
    def test_undeclared_read(self):
        self.assertCompileError(
            "fn main(): int { println(x); return 0; }", "Undeclared variable 'x'"
        )

    def test_undeclared_assignment(self):
        self.assertCompileError(
            "fn main(): int { x = 1; return 0; }", "Undeclared variable 'x'"
        )

    def test_redeclaration_in_same_scope(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let x: int; return 0; }",
            "Redeclaration of variable 'x'",
        )

    def test_type_inference_from_initializer(self):
        self.assertPrints(
            'fn main(): int { let x = 5; let s = "hi"; let b = true; '
            "println(x); println(s); println(b); return 0; }",
            "5", "hi", "true",
        )

    def test_cannot_infer_without_initializer(self):
        self.assertCompileError(
            "fn main(): int { let x; return 0; }", "Cannot infer type for 'x'"
        )

    def test_initializer_type_must_match_annotation(self):
        self.assertCompileError(
            "fn main(): int { let x: int = true; return 0; }", "Type mismatch in initializer"
        )

    def test_assignment_type_must_match(self):
        self.assertCompileError(
            "fn main(): int { let x: int; x = true; return 0; }", "Cannot assign bool to int"
        )

    def test_uninitialized_variables_are_zero(self):
        self.assertPrints("fn main(): int { let x: int; println(x); return 0; }", "0")

    def test_unknown_type_name(self):
        self.assertCompileError(
            "fn main(): int { let x: nope; return 0; }", "Unknown type 'nope'"
        )

    def test_void_value_cannot_be_assigned(self):
        self.assertCompileError(
            "fn f(): void { } fn main(): int { let x: int; x = f(); return 0; }",
            "Cannot assign void to int",
        )


class TestTypeRules(QuinTestCase):
    def test_bool_is_not_int(self):
        self.assertCompileError(
            "fn main(): int { println(true + 1); return 0; }",
            "Arithmetic operators require int operands",
        )

    def test_condition_must_be_bool(self):
        self.assertCompileError(
            "fn main(): int { if (1) { println(1); } return 0; }", "If condition must be bool"
        )

    def test_while_condition_must_be_bool(self):
        self.assertCompileError(
            "fn main(): int { while (1) { } return 0; }", "While condition must be bool"
        )

    def test_comparison_requires_matching_types(self):
        self.assertCompileError(
            "fn main(): int { if (1 == true) { } return 0; }",
            "Comparison requires operands of same type",
        )

    def test_logical_operators_require_bool(self):
        self.assertCompileError(
            "fn main(): int { if (1 && 2) { } return 0; }",
            "Logical && and || require bool operands",
        )

    def test_negation_requires_int(self):
        self.assertCompileError(
            "fn main(): int { let b: bool = true; println(0 - b); return 0; }",
            "Arithmetic operators require int operands",
        )

    def test_not_requires_bool(self):
        self.assertCompileError(
            "fn main(): int { println(!1); return 0; }", "Invalid unary op"
        )

    def test_modulo_requires_int(self):
        self.assertCompileError(
            "fn main(): int { println(true % 2); return 0; }",
            "Modulo operator requires int operands",
        )


class TestPrinting(QuinTestCase):
    def test_int_str_and_bool_are_printable(self):
        self.assertPrints(
            'fn main(): int { println(1); println("s"); println(true); return 0; }',
            "1", "s", "true",
        )

    def test_bool_prints_as_words(self):
        self.assertPrints(
            "fn main(): int { println(true); println(false); return 0; }", "true", "false"
        )

    def test_print_does_not_add_a_newline(self):
        self.assertOutput('fn main(): int { print("a"); print("b"); return 0; }', "ab")

    def test_ptr_is_not_printable(self):
        self.assertCompileError(
            "fn main(): int { let x: int; let p: ptr; p = @x; println(p); return 0; }",
            "print/println expect int, str, or bool",
        )

    def test_array_is_not_printable(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; println(a); return 0; }",
            "print/println expect int, str, or bool",
        )


class TestArrayRestrictions(QuinTestCase):
    def test_cannot_be_a_parameter(self):
        self.assertCompileError(
            "fn f(a: int[3]): int { return 0; } fn main(): int { return 0; }",
            "Array types are not supported for parameters",
        )

    def test_cannot_be_returned(self):
        self.assertCompileError(
            "fn f(): int[3] { } fn main(): int { return 0; }", "cannot return an array type"
        )

    def test_cannot_have_an_initializer(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2] = 0; return 0; }", "Type mismatch in initializer"
        )

    def test_cannot_be_assigned_wholesale(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; let b: int[2]; a = b; return 0; }",
            "Cannot assign to array variable 'a' as a whole",
        )

    def test_length_must_be_positive(self):
        self.assertCompileError(
            "fn main(): int { let a: int[0]; return 0; }", "Array length must be positive"
        )

    def test_index_must_be_int(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; a[true] = 1; return 0; }",
            "Array index must be int",
        )

    def test_elements_must_be_int(self):
        self.assertCompileError(
            "fn main(): int { let a: int[2]; a[0] = true; return 0; }",
            "Array elements must be int",
        )

    def test_cannot_index_a_scalar(self):
        self.assertCompileError(
            "fn main(): int { let x: int; println(x[0]); return 0; }",
            "Indexing requires int[N] array",
        )

    def test_arrays_start_zeroed(self):
        self.assertPrints(
            "fn main(): int { let a: int[3]; println(a[0]); println(a[2]); return 0; }",
            "0", "0",
        )


class TestLoopStatements(QuinTestCase):
    def test_for_condition_must_be_bool(self):
        self.assertCompileError(
            "fn main(): int { for (let i = 0; i; i = i + 1) { } return 0; }",
            "For condition must be bool",
        )

    def test_omitted_for_condition_is_allowed(self):
        self.assertCompiles(
            "fn main(): int { for (;;) { break; } return 0; }"
        )

    def test_for_never_counts_as_returning(self):
        self.assertCompileError(
            "fn f(): int { for (let i = 0; i < 1; i = i + 1) { return 1; } } "
            "fn main(): int { return 0; }",
            "missing return statement",
        )

    def test_break_outside_a_loop(self):
        self.assertCompileError(
            "fn main(): int { break; return 0; }", "'break' outside of a loop"
        )

    def test_continue_outside_a_loop(self):
        self.assertCompileError(
            "fn main(): int { continue; return 0; }", "'continue' outside of a loop"
        )

    def test_break_in_an_if_outside_a_loop(self):
        self.assertCompileError(
            "fn main(): int { if (true) { break; } return 0; }",
            "'break' outside of a loop",
        )

    def test_break_does_not_escape_the_function_that_loops(self):
        # The loop is in another function, so this break has nothing to bind to.
        self.assertCompileError(
            "fn looper(): void { while (true) { return; } }\n"
            "fn main(): int { break; return 0; }",
            "'break' outside of a loop",
        )

    def test_break_after_a_loop_has_closed(self):
        self.assertCompileError(
            "fn main(): int { while (false) { } break; return 0; }",
            "'break' outside of a loop",
        )

    def test_break_is_allowed_inside_a_nested_block(self):
        self.assertCompiles(
            "fn main(): int { while (true) { { break; } } return 0; }"
        )


if __name__ == "__main__":
    unittest.main()
