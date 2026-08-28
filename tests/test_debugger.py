"""Breakpoints, stepping and inspection.

The debugger is driven by a callback rather than a terminal, so these tests
supply one and assert on where it stopped and what it could see. The front end
is exercised the same way, by handing it a list of commands.

Positions are asserted exactly. A debugger that stops on the wrong line, or
reads the slot next to the one you asked for, is worse than no debugger: it is
confidently wrong at the moment you are trusting it most.

Sources are written with a leading newline for readability, so line 1 is always
the blank one the triple-quoted string opens with.
"""

import unittest

from compiler.bytecode import SourceMapBuilder
from runtime.debugger import (
    MAX_STRUCT_DEPTH,
    Debugger,
    DebuggerError,
    Mode,
    ResumeNotChosen,
    StopReason,
    ValueKind,
)
from runtime.vm import VMError
from tests.harness import (
    QuinTestCase,
    compile_source,
    debug_session,
    debug_trace,
    vm_for,
)

# main is on line 6; the call to add is on line 7.
CALLS = """
fn add(a: int, b: int): int {
    let sum: int = a + b;
    return sum;
}
fn main(): int {
    let total: int = add(2, 3);
    println(total);
    return 0;
}
"""

TYPES = """
struct Point { x: int, y: int, tag: str }
fn main(): int {
    let p: Point = Point{x: 3, y: -4, tag: "origin"};
    let f: float = 0.5;
    let flag: bool = false;
    let arr: int[3];
    arr[1] = 7;
    let empty: str;
    let none: Point;
    return 0;
}
"""


def at_breakpoint(source: str, target):
    """Run until `target` is hit, and hand back (debugger, vm, frames) there.

    The stop is captured rather than resumed, so the caller inspects the frame
    exactly as it stood.
    """
    import io
    from contextlib import redirect_stdout

    program = compile_source(source)
    captured = {}

    def on_stop(dbg, vm, stop):
        if stop.reason is StopReason.BREAKPOINT and "frames" not in captured:
            captured["frames"] = dbg.frames(vm)
            captured["vm"] = vm
            captured["stop"] = stop
        dbg.resume(Mode.RUN, vm)

    debugger = Debugger(program, on_stop)
    if isinstance(target, int):
        debugger.break_at_line(target)
    else:
        debugger.break_at_function(target)
    with redirect_stdout(io.StringIO()):
        debugger.run(vm_for(program))
    if "frames" not in captured:
        raise AssertionError("the breakpoint was never hit")
    return debugger, captured["vm"], captured["frames"]


class TestSourceMapReverseLookup(unittest.TestCase):
    """Setting a breakpoint runs the map backwards, from a line to a pc."""

    def build(self):
        m = SourceMapBuilder()
        m.mark(0, 3, 1)
        m.mark(4, 5, 1)
        m.mark(9, 3, 12)
        return m.build()

    def test_the_lowest_pc_on_a_line_wins(self):
        # Line 3 is marked twice; a breakpoint belongs at the start of it.
        self.assertEqual(self.build().first_pc_on_line(3), 0)

    def test_a_line_with_no_code_has_no_pc(self):
        self.assertIsNone(self.build().first_pc_on_line(4))

    def test_the_range_excludes_other_functions(self):
        # The map covers the whole program, so line 3 exists in more than one
        # file. A range is what disambiguates it.
        self.assertEqual(self.build().first_pc_on_line(3, start=5), 9)
        self.assertIsNone(self.build().first_pc_on_line(3, start=1, end=9))

    def test_lines_in_reports_only_lines_carrying_code(self):
        self.assertEqual(self.build().lines_in(), (3, 5))
        self.assertEqual(self.build().lines_in(start=4, end=9), (5,))


class TestBreakpointResolution(QuinTestCase):
    def debugger(self, source: str) -> Debugger:
        return Debugger(compile_source(source))

    def test_a_function_breakpoint_lands_on_its_first_line(self):
        bp = self.debugger(CALLS).break_at_function("add")
        self.assertEqual(bp.function, "add")
        self.assertEqual(bp.line, 3, "the first statement, not the signature")

    def test_an_unknown_function_is_refused(self):
        with self.assertRaises(DebuggerError) as caught:
            self.debugger(CALLS).break_at_function("nope")
        self.assertIn("no function named 'nope'", str(caught.exception))

    def test_a_line_breakpoint_resolves_within_the_compiled_file(self):
        bp = self.debugger(CALLS).break_at_line(7)
        self.assertEqual((bp.function, bp.line), ("main", 7))

    def test_a_line_with_no_code_moves_to_the_next_that_has_some(self):
        # Line 5 is `}`, which emits nothing of its own.
        bp = self.debugger(CALLS).break_at_line(5)
        self.assertEqual(bp.line, 7, "forwarded to the next line with code")

    def test_a_line_past_the_end_is_refused(self):
        with self.assertRaises(DebuggerError) as caught:
            self.debugger(CALLS).break_at_line(400)
        self.assertIn("no code at or after line 400", str(caught.exception))

    def test_the_same_pc_twice_is_one_breakpoint(self):
        dbg = self.debugger(CALLS)
        first = dbg.break_at_function("add")
        second = dbg.break_at_line(3)
        self.assertIs(first, second)
        self.assertEqual(len(dbg.breakpoints), 1)

    def test_deleting_stops_it_firing(self):
        dbg = self.debugger(CALLS)
        bp = dbg.break_at_function("add")
        dbg.remove(bp.id)
        self.assertEqual(dbg.breakpoints, {})
        with self.assertRaises(DebuggerError):
            dbg.remove(bp.id)

    def test_a_disabled_breakpoint_is_kept_but_skipped(self):
        def setup(dbg):
            bp = dbg.break_at_function("add")
            dbg.set_enabled(bp.id, False)

        stops = debug_trace(CALLS, Mode.RUN, setup)
        self.assertEqual(stops, [("main", 7)], "only the stop at entry")

    def test_hits_are_counted(self):
        source = """
        fn tick(n: int): int { return n; }
        fn main(): int {
            let i: int = 0;
            while (i < 3) { i = i + tick(1); }
            return 0;
        }
        """
        holder = {}

        def setup(dbg):
            holder["bp"] = dbg.break_at_function("tick")

        debug_trace(source, Mode.RUN, setup)
        self.assertEqual(holder["bp"].hits, 3)


class TestCrossFileBreakpoints(QuinTestCase):
    SRC = ('include "std/math.ql";\n'
           "fn main(): int {\n    println(clamp(9, 1, 5));\n    return 0;\n}\n")

    def test_a_function_from_an_include_can_be_broken_on(self):
        bp = Debugger(compile_source(self.SRC)).break_at_function("clamp")
        self.assertTrue(bp.file.endswith("math.ql"))

    def test_a_bare_line_means_the_compiled_file(self):
        # Line 3 exists in std/math.ql too; without the file it is ambiguous.
        bp = Debugger(compile_source(self.SRC)).break_at_line(3)
        self.assertEqual(bp.function, "main")
        self.assertTrue(bp.file.endswith("main.ql"))

    def test_a_file_can_be_named_by_suffix(self):
        dbg = Debugger(compile_source(self.SRC))
        bp = dbg.break_at_line(29, "std/math.ql")
        self.assertEqual(bp.function, "clamp")

    def test_an_unknown_file_is_refused(self):
        with self.assertRaises(DebuggerError) as caught:
            Debugger(compile_source(self.SRC)).break_at_line(3, "nowhere.ql")
        self.assertIn("no source file matching", str(caught.exception))


class TestStepping(QuinTestCase):
    def test_step_enters_a_call(self):
        stops = debug_trace(CALLS, Mode.STEP_IN)
        self.assertIn(("add", 3), stops, "step should arrive inside add")

    def test_next_steps_over_a_call(self):
        stops = debug_trace(CALLS, Mode.STEP_OVER)
        self.assertNotIn("add", [name for name, _ in stops])
        self.assertEqual([line for _, line in stops], [7, 8, 9])

    def test_next_still_stops_at_a_breakpoint_inside_the_call(self):
        # Stepping over is not a promise that nothing inside will stop.
        stops = debug_trace(CALLS, Mode.STEP_OVER,
                            lambda dbg: dbg.break_at_function("add"))
        self.assertIn(("add", 3), stops)

    def test_finish_returns_to_the_caller(self):
        source = """
        fn inner(): int { let a: int = 1; let b: int = 2; return a + b; }
        fn main(): int {
            let v: int = inner();
            println(v);
            return 0;
        }
        """
        seen = []

        def on_stop(dbg, vm, stop):
            seen.append((stop.frame.function, stop.frame.line))
            # Step into inner, then run it out in one command.
            dbg.resume(Mode.FINISH if stop.frame.function == "inner" else Mode.STEP_IN, vm)

        import io
        from contextlib import redirect_stdout
        program = compile_source(source)
        dbg = Debugger(program, on_stop)
        with redirect_stdout(io.StringIO()):
            dbg.run(vm_for(program))

        self.assertEqual(seen[0], ("main", 4))
        self.assertEqual(seen[1], ("inner", 2), "stepped in")
        self.assertEqual(seen[2][0], "main", "finish came back out")

    def test_a_loop_body_stops_once_per_iteration(self):
        source = """
        fn main(): int {
            let i: int = 0;
            while (i < 3) {
                i = i + 1;
            }
            return 0;
        }
        """
        stops = debug_trace(source, Mode.RUN, lambda dbg: dbg.break_at_line(5))
        self.assertEqual([line for _, line in stops if line == 5], [5, 5, 5])

    def test_recursion_steps_into_each_activation(self):
        source = """
        fn down(n: int): int {
            if (n == 0) { return 0; }
            return down(n - 1);
        }
        fn main(): int { return down(2); }
        """
        stops = debug_trace(source, Mode.STEP_IN)
        self.assertGreaterEqual(len([s for s in stops if s[0] == "down"]), 3)


class TestBacktrace(QuinTestCase):
    def test_frames_are_innermost_first_and_numbered_from_zero(self):
        _, _, frames = at_breakpoint(CALLS, "add")
        self.assertEqual([f.function for f in frames], ["add", "main"])
        self.assertEqual([f.depth for f in frames], [0, 1])

    def test_a_caller_reports_the_line_it_will_resume_at(self):
        _, _, frames = at_breakpoint(CALLS, "add")
        self.assertEqual(frames[1].line, 7, "the call site, not the line after")

    def test_every_activation_of_a_recursive_call_appears(self):
        source = """
        fn down(n: int): int {
            if (n == 0) { return 0; }
            return down(n - 1);
        }
        fn main(): int { return down(2); }
        """
        seen = []

        def on_stop(dbg, vm, stop):
            seen.append(len(dbg.frames(vm)))
            dbg.resume(Mode.RUN, vm)

        import io
        from contextlib import redirect_stdout
        program = compile_source(source)
        dbg = Debugger(program, on_stop)
        dbg.break_at_line(3, "")
        with redirect_stdout(io.StringIO()):
            dbg.run(vm_for(program))
        self.assertEqual(max(seen), 4, "three activations of down, plus main")


class TestValueInspection(QuinTestCase):
    def values(self, source: str, target):
        dbg, vm, frames = at_breakpoint(source, target)
        frame = frames[0]
        return {li.name: dbg.format_local(vm, frame, li) for li in dbg.locals_of(frame)}

    def test_every_type_reads_back(self):
        # Line 11 is `return 0;`, by which point everything is assigned.
        v = self.values(TYPES, 11)
        self.assertEqual(v["f"], "0.5")
        self.assertEqual(v["flag"], "false")
        self.assertEqual(v["arr"], "[0, 7, 0]")
        self.assertEqual(v["p"], 'Point { x: 3, y: -4, tag: "origin" }')

    def test_a_negative_int_is_signed(self):
        v = self.values(TYPES, 11)
        self.assertIn("-4", v["p"], "raw words would show 65532")

    def test_an_unassigned_reference_reads_as_the_language_defines_it(self):
        v = self.values(TYPES, 11)
        # A str has no null, so an uninitialised one is the empty string; a
        # struct reference does, and is null until something is assigned. The
        # debugger reports what the program actually holds, not a tidier story.
        self.assertEqual(v["empty"], '""')
        self.assertEqual(v["none"], "null")

    def test_a_float_is_read_from_both_its_slots(self):
        source = """
        fn main(): int {
            let a: float = 1.5;
            let b: float = 2.25;
            return 0;
        }
        """
        v = self.values(source, 5)
        self.assertEqual((v["a"], v["b"]), ("1.5", "2.25"),
                         "reading one slot would truncate to the low half")

    def test_a_function_value_reads_as_the_function_it_names(self):
        # The slot holds an index; showing the number would be technically
        # true and useless.
        source = """
        fn add(a: int, b: int): int { return a + b; }
        struct Op { apply: fn(int, int): int }
        fn main(): int {
            let f: fn(int, int): int = add;
            let o: Op = Op { apply: add };
            return 0;
        }
        """
        v = self.values(source, 7)
        self.assertEqual(v["f"], "add")
        self.assertIn("apply: add", v["o"])

    def test_a_parameter_is_marked_as_one(self):
        dbg, _, frames = at_breakpoint(CALLS, "add")
        kinds = {li.name: li.is_param for li in dbg.locals_of(frames[0])}
        self.assertEqual(kinds, {"a": True, "b": True, "sum": False})

    def test_a_callers_frame_is_readable_too(self):
        source = """
        fn inner(): int { return 1; }
        fn main(): int {
            let outer_value: int = 42;
            return inner() + outer_value;
        }
        """
        dbg, vm, frames = at_breakpoint(source, "inner")
        caller = frames[1]
        info = dbg.lookup_name(caller, "outer_value")[0]
        self.assertEqual(dbg.format_local(vm, caller, info), "42")

    def test_a_shadowed_name_reports_every_declaration(self):
        source = """
        fn main(): int {
            let x: int = 1;
            if (true) { let x: int = 2; }
            return x;
        }
        """
        dbg, _, frames = at_breakpoint(source, 5)
        matches = dbg.lookup_name(frames[0], "x")
        self.assertEqual(len(matches), 2)
        self.assertNotEqual(matches[0].slot, matches[1].slot)

    def test_an_unknown_name_finds_nothing(self):
        dbg, _, frames = at_breakpoint(CALLS, "add")
        self.assertEqual(dbg.lookup_name(frames[0], "nope"), [])

    def test_a_nested_struct_expands(self):
        source = """
        struct Inner { v: int }
        struct Outer { inner: Inner, n: int }
        fn main(): int {
            let o: Outer = Outer{inner: Inner{v: 7}, n: 1};
            return 0;
        }
        """
        v = self.values(source, 6)
        self.assertEqual(v["o"], "Outer { inner: Inner { v: 7 }, n: 1 }")

    def test_a_cyclic_structure_terminates(self):
        source = """
        struct Node { next: Node, v: int }
        fn main(): int {
            let a: Node = Node{next: null, v: 1};
            a.next = a;
            return 0;
        }
        """
        v = self.values(source, 6)
        self.assertIn("Node", v["a"], "it still describes what it can")
        self.assertLess(len(v["a"]), 400, "expansion must stop, not recur forever")


class TestValueDescription(QuinTestCase):
    """The structured form both front ends read.

    `format_local` flattens it for a terminal; the adapter hands out a handle
    and expands one level per click. The two must not drift, so what is pinned
    here is that they describe the same value.
    """

    def describe(self, source: str, target, name: str):
        dbg, vm, frames = at_breakpoint(source, target)
        info = dbg.lookup_name(frames[0], name)[0]
        return dbg, vm, dbg.describe_local(vm, frames[0], info)

    def test_a_struct_elides_its_children_in_the_summary(self):
        dbg, vm, value = self.describe(TYPES, 11, "p")
        self.assertEqual(value.kind, ValueKind.STRUCT)
        self.assertEqual(value.summary, "Point {\u2026}")
        self.assertEqual(value.type_name, "Point")
        self.assertTrue(value.expandable)

    def test_children_are_one_level_and_named(self):
        dbg, vm, value = self.describe(TYPES, 11, "p")
        children = dbg.children_of(vm, value)
        self.assertEqual([name for name, _ in children], ["x", "y", "tag"])
        self.assertEqual([v.summary for _, v in children], ["3", "-4", '"origin"'])

    def test_a_scalar_has_nothing_to_expand(self):
        dbg, vm, value = self.describe(TYPES, 11, "f")
        self.assertEqual(value.kind, ValueKind.SCALAR)
        self.assertFalse(value.expandable)
        self.assertEqual(dbg.children_of(vm, value), [])

    def test_an_array_reads_its_elements_eagerly(self):
        # Its summary is the elements, so there is nothing to defer.
        dbg, vm, value = self.describe(TYPES, 11, "arr")
        self.assertEqual(value.summary, "[0, 7, 0]")
        self.assertEqual([name for name, _ in dbg.children_of(vm, value)],
                         ["[0]", "[1]", "[2]"])

    def test_a_variant_payload_is_numbered_not_named(self):
        # Its fields are called _0 and _1, and nothing in the language can name
        # one, so it reads like an array element instead.
        source = """
        enum Shape { Circle(int), Blank }
        fn main(): int {
            let s: Shape = Shape::Circle(9);
            let b: Shape = Shape::Blank;
            return 0;
        }
        """
        dbg, vm, value = self.describe(source, 6, "s")
        self.assertEqual(value.kind, ValueKind.VARIANT)
        self.assertEqual(value.summary, "Shape::Circle(\u2026)")
        self.assertEqual(value.type_name, "Shape", "the enum, not the variant")
        self.assertEqual([(n, v.summary) for n, v in dbg.children_of(vm, value)],
                         [("[0]", "9")])

    def test_a_variant_with_no_payload_has_nothing_inside(self):
        source = """
        enum Shape { Circle(int), Blank }
        fn main(): int {
            let b: Shape = Shape::Blank;
            return 0;
        }
        """
        dbg, vm, value = self.describe(source, 5, "b")
        self.assertEqual(value.summary, "Shape::Blank")
        self.assertFalse(value.expandable)


CYCLE = """
struct Node { value: int, next: Node }
fn main(): int {
    let a: Node = Node { value: 1, next: null };
    let b: Node = Node { value: 2, next: a };
    a.next = b;
    return 0;
}
"""


class TestCyclicValues(QuinTestCase):
    def test_the_flat_form_stops_at_the_depth_cap(self):
        dbg, vm, frames = at_breakpoint(CYCLE, 7)
        info = dbg.lookup_name(frames[0], "a")[0]
        text = dbg.format_local(vm, frames[0], info)
        self.assertEqual(text.count("Node {"), MAX_STRUCT_DEPTH,
                         "without a cap it would not return")
        self.assertIn("<Node at ", text)

    def test_expanding_one_level_at_a_time_never_recurses(self):
        # The same ring, walked by a front end that drives expansion. There is
        # no depth to cap because nothing here calls itself.
        dbg, vm, frames = at_breakpoint(CYCLE, 7)
        info = dbg.lookup_name(frames[0], "a")[0]
        value = dbg.describe_local(vm, frames[0], info)
        seen = []
        for _ in range(2 * MAX_STRUCT_DEPTH):
            children = dict(dbg.children_of(vm, value))
            seen.append(children["value"].summary)
            value = children["next"]
        self.assertEqual(seen, ["1", "2"] * MAX_STRUCT_DEPTH)


class TestFaultPostMortem(QuinTestCase):
    SRC = """
    fn risky(n: int): int {
        let z: int;
        return n / z;
    }
    fn main(): int {
        let a: int = 5;
        return risky(a);
    }
    """

    def stop(self):
        import io
        from contextlib import redirect_stdout
        program = compile_source(self.SRC)
        captured = {}

        def on_stop(dbg, vm, stop):
            if stop.reason is StopReason.FAULT:
                captured["stop"] = stop
                captured["frames"] = dbg.frames(vm)
                captured["dbg"] = dbg
                captured["vm"] = vm
            dbg.resume(Mode.RUN, vm)

        dbg = Debugger(program, on_stop)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(VMError):
                dbg.run(vm_for(program))
        return captured

    def test_a_fault_stops_before_it_propagates(self):
        self.assertIn("stop", self.stop())

    def test_the_frames_are_still_intact(self):
        # The VM does not unwind when it raises, which is what makes a
        # post-mortem possible at all.
        frames = self.stop()["frames"]
        self.assertEqual([f.function for f in frames], ["risky", "main"])

    def test_the_faulting_frame_can_be_inspected(self):
        c = self.stop()
        dbg, vm, frame = c["dbg"], c["vm"], c["frames"][0]
        info = dbg.lookup_name(frame, "z")[0]
        self.assertEqual(dbg.format_local(vm, frame, info), "0",
                         "the divisor that caused it")

    def test_the_error_is_carried_on_the_stop(self):
        self.assertIn("Division by zero", str(self.stop()["stop"].error))

    def test_the_error_still_propagates(self):
        # Inspecting a fault does not swallow it.
        self.stop()   # asserts the raise internally


class TestHookIsOffByDefault(QuinTestCase):
    def test_a_plain_run_installs_no_hook(self):
        program = compile_source("fn main(): int { return 0; }")
        vm = vm_for(program)
        self.assertIsNone(vm.hook)
        vm.run_main()
        self.assertIsNone(vm.hook)

    def test_attaching_during_a_run_has_no_effect(self):
        """Pins the trade that makes the hook free.

        The loop reads self.hook once into a local, so a hook installed after
        the run starts is never called. If someone later moves that read back
        inside the loop, this test fails and the 3% it costs gets a second
        look before it lands.
        """
        program = compile_source("fn main(): int { let i: int = 0; return i; }")
        vm = vm_for(program)
        called = []
        vm.hook = lambda v: (v.__setattr__("hook", lambda _: called.append(1)))
        vm.run_main()
        self.assertEqual(called, [])

    def test_the_hook_is_removed_after_a_debug_run(self):
        import io
        from contextlib import redirect_stdout
        program = compile_source("fn main(): int { return 0; }")
        vm = vm_for(program)
        with redirect_stdout(io.StringIO()):
            Debugger(program).run(vm)
        self.assertIsNone(vm.hook, "a later plain run must not pay for it")


class TestResumeContract(QuinTestCase):
    """A front end must say how to resume. This is the failure mode that is
    hardest to see from a distance: a step that silently became a continue
    looks like a breakpoint that did not fire."""

    # Several lines, so a step actually produces a second stop to forget at.
    SRC = "fn main(): int {\n    let a: int = 1;\n    let b: int = 2;\n    return a + b;\n}"

    def run_with(self, on_stop):
        import io
        from contextlib import redirect_stdout
        program = compile_source(self.SRC)
        dbg = Debugger(program, on_stop)
        with redirect_stdout(io.StringIO()):
            return dbg.run(vm_for(program))

    def test_returning_without_choosing_is_an_error(self):
        with self.assertRaises(ResumeNotChosen):
            self.run_with(lambda dbg, vm, stop: None)

    def test_the_error_says_what_to_call(self):
        with self.assertRaises(ResumeNotChosen) as caught:
            self.run_with(lambda dbg, vm, stop: None)
        self.assertIn("Debugger.resume()", str(caught.exception))

    def test_choosing_explicitly_is_fine(self):
        self.assertEqual(self.run_with(lambda dbg, vm, stop: dbg.resume(Mode.RUN, vm)), 3)

    def test_no_front_end_runs_to_completion(self):
        # The default is not a no-op: it chooses RUN, so "nobody chose" stays
        # an error rather than being the ordinary case.
        import io
        from contextlib import redirect_stdout
        program = compile_source(self.SRC)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Debugger(program).run(vm_for(program)), 3)

    def test_a_front_end_that_stops_choosing_partway_is_caught(self):
        # The realistic shape of the bug: a handler that chooses on some stops
        # and falls through on others.
        seen = []

        def on_stop(dbg, vm, stop):
            seen.append(stop.reason)
            if len(seen) == 1:
                dbg.resume(Mode.STEP_IN, vm)
            # second stop: forgets, which must not become a continue

        with self.assertRaises(ResumeNotChosen):
            self.run_with(on_stop)
        self.assertEqual(len(seen), 2, "it failed at the stop that forgot, not before")


class TestFrontEnd(QuinTestCase):
    """The REPL, driven by a list of commands instead of a terminal."""

    def test_it_stops_before_the_program_runs(self):
        out = debug_session(CALLS, ["quit"])
        self.assertIn("Stopped at main", out)
        self.assertIn("Abandoned.", out)

    def test_break_then_continue_reports_the_stop(self):
        out = debug_session(CALLS, ["break add", "continue", "quit"])
        self.assertIn("Breakpoint 1 at add", out)
        self.assertIn("Breakpoint 1, add", out)

    def test_locals_lists_the_frame(self):
        out = debug_session(CALLS, ["break add", "continue", "locals", "quit"])
        self.assertIn("a", out)
        self.assertIn("param", out)
        self.assertIn("int = 2", out)

    def test_print_names_one_variable(self):
        out = debug_session(CALLS, ["break add", "continue", "print b", "quit"])
        self.assertIn("b: int = 3", out)

    def test_print_of_an_unknown_name_is_reported_not_fatal(self):
        out = debug_session(CALLS, ["break add", "continue", "print nope", "locals", "quit"])
        self.assertIn("no variable 'nope'", out)
        self.assertIn("param", out, "the session carried on")

    def test_a_shadowed_name_says_so(self):
        source = """
        fn main(): int {
            let x: int = 1;
            if (true) { let x: int = 2; }
            return x;
        }
        """
        out = debug_session(source, ["break 5", "continue", "print x", "quit"])
        self.assertIn("shadowed", out)
        self.assertEqual(out.count("x: int ="), 2, "both declarations shown")

    def test_backtrace_marks_the_selected_frame(self):
        out = debug_session(CALLS, ["break add", "continue", "backtrace", "quit"])
        self.assertIn("-> #0 add", out)
        self.assertIn("#1 main", out)

    def test_frame_switches_what_print_reads(self):
        out = debug_session(CALLS, ["break add", "continue", "frame 1", "print total", "quit"])
        self.assertIn("total: int", out)

    def test_selecting_a_frame_that_does_not_exist_is_reported(self):
        out = debug_session(CALLS, ["break add", "continue", "frame 9", "quit"])
        self.assertIn("no frame 9", out)

    def test_an_empty_line_repeats_the_last_command(self):
        out = debug_session(CALLS, ["next", "", "", "quit"])
        # main has three lines carrying code, so the entry stop and two nexts
        # exhaust it; the third runs the program out and never stops again.
        self.assertEqual(out.count("main at"), 3)
        self.assertIn(":9", out, "the repeats did advance")

    def test_an_unknown_command_is_reported_not_fatal(self):
        out = debug_session(CALLS, ["wibble", "quit"])
        self.assertIn("Unknown command 'wibble'", out)

    def test_help_lists_the_commands(self):
        out = debug_session(CALLS, ["help", "quit"])
        for command in ("break", "continue", "step", "next", "finish", "print"):
            self.assertIn(command, out)

    def test_breakpoints_lists_them_with_hits(self):
        out = debug_session(CALLS, ["break add", "continue", "breakpoints", "quit"])
        self.assertIn("1 hit", out)

    def test_delete_removes_every_breakpoint(self):
        out = debug_session(CALLS, ["break add", "delete", "breakpoints", "quit"])
        self.assertIn("No breakpoints.", out)

    def test_end_of_input_ends_the_session(self):
        # Ctrl-D reaches the session as EOF, which must not look like a crash.
        out = debug_session(CALLS, ["break add"])
        self.assertIn("Abandoned.", out)

    def test_a_fault_offers_a_post_mortem_and_refuses_to_resume(self):
        source = """
        fn main(): int {
            let z: int;
            return 1 / z;
        }
        """
        out = debug_session(source, ["continue", "print z", "continue", "quit"])
        self.assertIn("Division by zero", out)
        self.assertIn("z: int = 0", out)
        self.assertIn("already faulted", out)


if __name__ == "__main__":
    unittest.main()
