"""stackTrace, scopes, variables and evaluate.

The shape being tested is DAP's: the client is handed numbers, and every
further question is asked with one of them. A frame id gets scopes, a scope's
reference gets variables, and an expandable variable's reference gets one more
level -- which is what makes a cyclic structure walkable here where the
terminal front end has to stop at a fixed depth. `evaluate` is the same values
reached by name instead, for hover and watch.
"""

import unittest

from tests.harness import SPINNING, DapTestCase

#   1 fn inner   2 let doubled   3 return   4 }   5 blank
#   6 fn outer   7 return inner  8 }        9 blank
#  10 fn main   11 let start    12 return outer  13 }
NESTED = """fn inner(n: int): int {
    let doubled: int = n * 2;
    return doubled;
}

fn outer(n: int): int {
    return inner(n + 1);
}

fn main(): int {
    let start: int = 4;
    return outer(start) - outer(start);
}
"""

VALUES = """struct Node {
    value: int,
    next: Node,
}

enum Shape {
    Circle(int),
    Blank,
}

fn main(): int {
    let count: int = -3;
    let flag: bool = true;
    let ratio: float = 1.75;
    let label: str = "hi";
    let numbers: int[3];
    numbers[1] = 7;
    let head: Node = Node { value: 1, next: null };
    let round: Shape = Shape::Circle(9);
    let blank: Shape = Shape::Blank;
    let missing: Node = null;
    return 0;
}
"""
VALUES_LAST_LINE = 22

SHADOWED = """fn main(): int {
    let x: int = 1;
    {
        let x: int = 2;
        println(x);
    }
    return 0;
}
"""


class InspectionTestCase(DapTestCase):
    def stopped(self, source, line):
        client = self.client(source, launch=False)
        self.launch(client)
        self.set_breakpoints(client, line)
        self.configuration_done(client)
        self.assertStopped(client, "breakpoint")
        return client

    def frames(self, client, **arguments):
        client.send("stackTrace", threadId=1, **arguments)
        return client.wait_for_response("stackTrace")["body"]

    def locals_of(self, client, depth=0):
        frames = self.frames(client)["stackFrames"]
        client.send("scopes", frameId=frames[depth]["id"])
        scopes = client.wait_for_response("scopes")["body"]["scopes"]
        return self.expand(client, scopes[0]["variablesReference"])

    def expand(self, client, reference):
        client.send("variables", variablesReference=reference)
        return client.wait_for_response("variables")["body"]["variables"]

    def named(self, variables):
        return {v["name"]: v for v in variables}


class TestStackTrace(InspectionTestCase):
    def test_the_stack_is_innermost_first(self):
        client = self.stopped(NESTED, 2)
        names = [f["name"] for f in self.frames(client)["stackFrames"]]
        self.assertEqual(names, ["inner", "outer", "main"])

    def test_each_frame_carries_a_position(self):
        client = self.stopped(NESTED, 2)
        innermost = self.frames(client)["stackFrames"][0]
        self.assertEqual(innermost["line"], 2)
        self.assertGreater(innermost["column"], 0)
        self.assertEqual(innermost["source"]["path"], client.program_path)
        self.assertEqual(innermost["source"]["name"], "main.ql")

    def test_paging_reports_the_untruncated_count(self):
        client = self.stopped(NESTED, 2)
        page = self.frames(client, startFrame=1, levels=1)
        self.assertEqual([f["name"] for f in page["stackFrames"]], ["outer"])
        self.assertEqual(page["totalFrames"], 3)

    def test_it_is_refused_while_the_program_runs(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.send("stackTrace", threadId=1)
        reply = client.wait_for_response("stackTrace")
        self.assertFalse(reply["success"])
        self.assertIn("not suspended", reply["message"])


class TestScopes(InspectionTestCase):
    def test_a_frame_has_one_cheap_scope(self):
        client = self.stopped(NESTED, 2)
        frames = self.frames(client)["stackFrames"]
        client.send("scopes", frameId=frames[0]["id"])
        scopes = client.wait_for_response("scopes")["body"]["scopes"]
        self.assertEqual(len(scopes), 1, "no globals and no closures")
        self.assertEqual(scopes[0]["name"], "Locals")
        self.assertFalse(scopes[0]["expensive"])

    def test_an_unknown_frame_is_refused(self):
        client = self.stopped(NESTED, 2)
        client.send("scopes", frameId=9999)
        self.assertFalse(client.wait_for_response("scopes")["success"])


class TestVariables(InspectionTestCase):
    def values(self, client, depth=0):
        return {name: v["value"]
                for name, v in self.named(self.locals_of(client, depth)).items()}

    def test_scalars_read_back_as_written(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        v = self.values(client)
        self.assertEqual(v["count"], "-3", "raw words would show 65533")
        self.assertEqual(v["flag"], "true")
        self.assertEqual(v["ratio"], "1.75")
        self.assertEqual(v["label"], '"hi"')

    def test_a_type_is_reported_alongside_the_value(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        types = {name: v["type"]
                 for name, v in self.named(self.locals_of(client)).items()}
        self.assertEqual(types["count"], "int")
        self.assertEqual(types["numbers"], "int[3]")
        self.assertEqual(types["round"], "Shape", "the enum, not the variant")

    def test_a_null_reference_is_not_expandable(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        missing = self.named(self.locals_of(client))["missing"]
        self.assertEqual(missing["value"], "null")
        self.assertEqual(missing["variablesReference"], 0)

    def test_a_payload_free_variant_is_a_bare_name(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        blank = self.named(self.locals_of(client))["blank"]
        self.assertEqual(blank["value"], "Shape::Blank")
        self.assertEqual(blank["variablesReference"], 0,
                         "there is nothing inside it")

    def test_a_caller_frame_is_readable(self):
        client = self.stopped(NESTED, 2)
        self.assertEqual(self.values(client, 2)["start"], "4")

    def test_a_local_carries_an_evaluate_name(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        self.assertEqual(self.named(self.locals_of(client))["count"]["evaluateName"],
                         "count")


class TestExpansion(InspectionTestCase):
    def test_a_struct_expands_into_its_fields(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        head = self.named(self.locals_of(client))["head"]
        self.assertEqual(head["value"], "Node {…}")
        fields = self.named(self.expand(client, head["variablesReference"]))
        self.assertEqual(fields["value"]["value"], "1")
        self.assertEqual(fields["next"]["value"], "null")

    def test_an_array_expands_into_its_elements(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        numbers = self.named(self.locals_of(client))["numbers"]
        self.assertEqual(numbers["value"], "[0, 7, 0]")
        self.assertEqual(numbers["indexedVariables"], 3)
        elements = self.expand(client, numbers["variablesReference"])
        self.assertEqual([e["name"] for e in elements], ["[0]", "[1]", "[2]"])
        self.assertEqual([e["value"] for e in elements], ["0", "7", "0"])

    def test_a_variant_payload_is_positional(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        round_ = self.named(self.locals_of(client))["round"]
        self.assertEqual(round_["value"], "Shape::Circle(…)")
        payload = self.expand(client, round_["variablesReference"])
        self.assertEqual([(p["name"], p["value"]) for p in payload], [("[0]", "9")])

    def test_a_cycle_can_be_walked_a_level_at_a_time(self):
        # The terminal front end stops at MAX_STRUCT_DEPTH because its whole
        # answer has to fit on one line. Here the client drives, so a ring can
        # be followed as far as anyone cares to click.
        source = """struct Node { value: int, next: Node }
fn main(): int {
    let a: Node = Node { value: 1, next: null };
    let b: Node = Node { value: 2, next: a };
    a.next = b;
    return 0;
}
"""
        client = self.stopped(source, 6)
        reference = self.named(self.locals_of(client))["a"]["variablesReference"]
        seen = []
        for _ in range(6):
            fields = self.named(self.expand(client, reference))
            seen.append(fields["value"]["value"])
            reference = fields["next"]["variablesReference"]
            self.assertNotEqual(reference, 0)
        self.assertEqual(seen, ["1", "2", "1", "2", "1", "2"])


class TestShadowing(InspectionTestCase):
    def test_both_slots_are_shown_named_apart(self):
        # Which one is live at this pc is not knowable from the slot table, so
        # neither is presented as the real one.
        client = self.stopped(SHADOWED, 5)
        names = [v["name"] for v in self.locals_of(client)]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(name.startswith("x (slot ") for name in names), names)

    def test_a_shadowed_name_gets_no_evaluate_name(self):
        client = self.stopped(SHADOWED, 5)
        for entry in self.locals_of(client):
            self.assertNotIn("evaluateName", entry,
                             "it would resolve to a guess")


class TestEvaluate(InspectionTestCase):
    """Hover and watch, which is what `evaluate` is for here.

    Bare names only. A real expression means compiling a fragment against the
    frame's scope and running it on the suspended VM, which is a feature rather
    than something to approximate.
    """

    def evaluate(self, client, expression, **arguments):
        client.send("evaluate", expression=expression, **arguments)
        return client.wait_for_response("evaluate")

    def test_the_capability_is_declared(self):
        client = self.connect()
        client.send("initialize")
        self.assertTrue(client.wait_for_response("initialize")
                        ["body"]["supportsEvaluateForHovers"])

    def test_a_name_gives_its_value_and_type(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        body = self.evaluate(client, "count")["body"]
        self.assertEqual(body["result"], "-3")
        self.assertEqual(body["type"], "int")
        self.assertEqual(body["variablesReference"], 0)

    def test_an_expandable_value_can_be_expanded_from_a_watch(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        body = self.evaluate(client, "head")["body"]
        self.assertEqual(body["result"], "Node {…}")
        fields = self.named(self.expand(client, body["variablesReference"]))
        self.assertEqual(fields["value"]["value"], "1")

    def test_an_array_reports_its_length(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        body = self.evaluate(client, "numbers")["body"]
        self.assertEqual(body["indexedVariables"], 3)

    def test_a_frame_id_picks_which_activation_to_look_in(self):
        client = self.stopped(NESTED, 2)
        outer = self.frames(client)["stackFrames"][2]["id"]
        self.assertEqual(self.evaluate(client, "start", frameId=outer)["body"]["result"],
                         "4")
        self.assertFalse(self.evaluate(client, "start")["success"],
                         "start is not in scope in the innermost frame")

    def test_without_a_frame_id_the_innermost_frame_is_used(self):
        # DAP means the global scope by that, and QuinLang has none.
        client = self.stopped(NESTED, 2)
        self.assertEqual(self.evaluate(client, "n")["body"]["result"], "5")

    def test_an_unknown_name_is_refused(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        reply = self.evaluate(client, "nosuchthing")
        self.assertFalse(reply["success"])
        self.assertIn("no variable named", reply["message"])

    def test_anything_that_is_not_a_name_is_refused(self):
        client = self.stopped(VALUES, VALUES_LAST_LINE)
        for expression in ("count + 1", "head.value", "1", "", "count()"):
            reply = self.evaluate(client, expression)
            self.assertFalse(reply["success"], expression)
            self.assertIn("only variable names", reply["message"])

    def test_a_shadowed_name_is_refused_rather_than_guessed(self):
        client = self.stopped(SHADOWED, 5)
        reply = self.evaluate(client, "x")
        self.assertFalse(reply["success"])
        self.assertIn("more than one slot", reply["message"])

    def test_it_is_refused_while_the_program_runs(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        reply = self.evaluate(client, "x")
        self.assertFalse(reply["success"])
        self.assertIn("not suspended", reply["message"])


class TestHandles(InspectionTestCase):
    def test_a_handle_from_a_previous_stop_is_refused(self):
        client = self.client(NESTED, launch=False)
        self.launch(client)
        self.set_breakpoints(client, 2)
        self.configuration_done(client)
        self.assertStopped(client, "breakpoint")
        stale = self.frames(client)["stackFrames"][0]["id"]
        client.send("continue")
        self.assertStopped(client, "breakpoint")     # inner is called twice
        client.send("scopes", frameId=stale)
        self.assertFalse(client.wait_for_response("scopes")["success"],
                         "it named values the program has since left behind")

    def test_an_invented_reference_is_refused(self):
        client = self.stopped(NESTED, 2)
        client.send("variables", variablesReference=424242)
        self.assertFalse(client.wait_for_response("variables")["success"])

    def test_asking_twice_gives_the_same_frame_id(self):
        client = self.stopped(NESTED, 2)
        first = [f["id"] for f in self.frames(client)["stackFrames"]]
        second = [f["id"] for f in self.frames(client)["stackFrames"]]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
