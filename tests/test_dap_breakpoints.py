"""setBreakpoints and setFunctionBreakpoints.

DAP is declarative and per-file -- a request carries the complete desired set
for one source and replaces what was there -- while `Debugger` adds them one at
a time. Most of what is asserted here is that mismatch being handled: replacing
a set, clearing it, reporting a line that moved, and answering positionally so
the client can match entries back to the lines it asked about.
"""

import unittest

from tests.harness import DapTestCase

# Line numbers are the subject of these tests, so they are counted here once:
#
#   1 fn tick        2 let doubled    3 return        4 }           5 blank
#   6 fn main        7 let total      8 total = ...   9 blank
#  10 comment       11 total = ...   12 println      13 return     14 }
COUNTER = """fn tick(n: int): int {
    let doubled: int = n * 2;
    return doubled;
}

fn main(): int {
    let total: int = 0;
    total = total + tick(1);

    // nothing here
    total = total + tick(2);
    println(total);
    return 0;
}
"""

MISSING_LINE = 100


class BreakpointTestCase(DapTestCase):
    def armed(self, *lines, source=COUNTER, stop_on_entry=False):
        """A launched, configured client with these breakpoints set.

        Set between `launch` and `configurationDone`, which is where a client
        sends them and the last moment before the program starts.
        """
        client = self.client(source, launch=False)
        self.launch(client, stop_on_entry=stop_on_entry)
        reported = self.set_breakpoints(client, *lines)
        self.configuration_done(client)
        return client, reported


class TestStopping(BreakpointTestCase):
    def test_a_breakpoint_stops_the_program(self):
        client, _ = self.armed(12)
        self.assertStopped(client, "breakpoint")
        self.assertEqual(client.output(), "", "line 12 is the println itself")

    def test_continuing_runs_on_to_the_end(self):
        client, _ = self.armed(12)
        self.assertStopped(client, "breakpoint")
        client.send("continue")
        client.wait_for_event("terminated")
        self.assertEqual(client.output(), "6\n")

    def test_a_breakpoint_in_a_called_function_stops_every_call(self):
        client, _ = self.armed(2)
        for _ in range(2):
            self.assertStopped(client, "breakpoint")
            client.send("continue")
            client.wait_for_response("continue")
        client.wait_for_event("terminated")

    def test_the_stop_names_the_breakpoint_that_fired(self):
        client, reported = self.armed(12)
        body = self.assertStopped(client, "breakpoint")["body"]
        self.assertEqual(body["hitBreakpointIds"], [reported[0]["id"]])

    def test_no_breakpoints_means_no_stops(self):
        client, _ = self.armed()
        client.wait_for_event("terminated")
        self.assertEqual(client.events("stopped"), [])


class TestReporting(BreakpointTestCase):
    def test_a_line_with_code_is_verified_where_it_was_asked_for(self):
        _, reported = self.armed(12)
        self.assertTrue(reported[0]["verified"])
        self.assertEqual(reported[0]["line"], 12)

    def test_a_line_without_code_moves_to_the_next_one_that_has_some(self):
        # A comment: the debugger walks forward, and DAP has a channel for
        # saying so, so the client's marker follows.
        _, reported = self.armed(10)
        self.assertTrue(reported[0]["verified"])
        self.assertEqual(reported[0]["line"], 11)

    def test_a_line_past_the_end_is_unverified_with_a_reason(self):
        _, reported = self.armed(MISSING_LINE)
        self.assertFalse(reported[0]["verified"])
        self.assertIn("no code", reported[0]["message"])

    def test_the_response_is_positional(self):
        # One entry per requested line, in order, resolved or not: that is how
        # the client matches them back to its markers.
        _, reported = self.armed(12, MISSING_LINE, 7)
        self.assertEqual([b["verified"] for b in reported], [True, False, True])
        self.assertEqual([reported[0]["line"], reported[2]["line"]], [12, 7])

    def test_the_source_echoes_the_client_spelling(self):
        client, reported = self.armed(12)
        self.assertEqual(reported[0]["source"]["path"], client.program_path)

    def test_two_lines_landing_on_the_same_code_stay_two_breakpoints(self):
        # A blank line and a comment both walk forward to line 11. They are one
        # breakpoint inside the debugger and two markers in the client.
        client, reported = self.armed(9, 10)
        ids = [b["id"] for b in reported]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual([b["line"] for b in reported], [11, 11])
        body = self.assertStopped(client, "breakpoint")["body"]
        self.assertEqual(sorted(body["hitBreakpointIds"]), sorted(ids))


class TestReplacing(BreakpointTestCase):
    def test_a_second_request_replaces_the_first(self):
        # Line 2 is inside tick and would fire twice; line 12 fires once.
        client, _ = self.armed(2, stop_on_entry=True)
        self.assertStopped(client, "entry")
        self.set_breakpoints(client, 12)
        client.send("continue")
        self.assertStopped(client, "breakpoint")
        client.send("continue")
        client.wait_for_event("terminated")
        self.assertEqual(len(client.events("stopped")), 2,
                         "line 2 was replaced, not added to")

    def test_an_empty_request_clears_them(self):
        client, _ = self.armed(12, stop_on_entry=True)
        self.assertStopped(client, "entry")
        self.assertEqual(self.set_breakpoints(client), [])
        client.send("continue")
        client.wait_for_event("terminated")
        self.assertEqual(client.output(), "6\n")

    def test_one_can_be_added_while_the_program_is_stopped(self):
        client, _ = self.armed(7)
        self.assertStopped(client, "breakpoint")
        self.set_breakpoints(client, 7, 12)
        client.send("continue")
        self.assertStopped(client, "breakpoint")
        client.send("continue")
        client.wait_for_event("terminated")

    def test_another_source_is_left_alone(self):
        # Each request replaces one file's set, so a second source -- even an
        # unresolvable one -- must not disturb the first.
        client, _ = self.armed(12, stop_on_entry=True)
        self.assertStopped(client, "entry")
        other = self.set_breakpoints(client, 1, path="/nowhere/absent.ql")
        self.assertFalse(other[0]["verified"])
        client.send("continue")
        self.assertStopped(client, "breakpoint")


class TestBeforeLaunch(BreakpointTestCase):
    def test_they_are_unverified_until_there_is_a_program(self):
        client = self.client(COUNTER, launch=False)
        reported = self.set_breakpoints(client, 12)
        self.assertFalse(reported[0]["verified"])

    def test_launching_verifies_them_and_says_so(self):
        client = self.client(COUNTER, launch=False)
        before = self.set_breakpoints(client, 10)
        self.launch(client)
        changed = client.wait_for_event("breakpoint")["body"]
        self.assertEqual(changed["reason"], "changed")
        self.assertTrue(changed["breakpoint"]["verified"])
        self.assertEqual(changed["breakpoint"]["id"], before[0]["id"],
                         "the id has to survive, or the client cannot match it")
        self.assertEqual(changed["breakpoint"]["line"], 11)

    def test_a_buffered_breakpoint_still_fires(self):
        client = self.client(COUNTER, launch=False)
        self.set_breakpoints(client, 12)
        self.launch(client)
        self.configuration_done(client)
        self.assertStopped(client, "breakpoint")

    def test_unchanged_breakpoints_produce_no_event(self):
        client, _ = self.armed(12, stop_on_entry=True)
        self.assertStopped(client, "entry")
        self.set_breakpoints(client, 12)
        client.send("continue")
        self.assertStopped(client, "breakpoint")
        client.send("continue")
        client.wait_for_event("terminated")
        self.assertEqual(client.events("breakpoint"), [],
                         "only news is worth an event")


class TestFunctionBreakpoints(BreakpointTestCase):
    def test_the_capability_is_declared(self):
        client = self.client(COUNTER, launch=False)
        client.send("initialize")
        capabilities = client.wait_for_response("initialize")["body"]
        self.assertTrue(capabilities["supportsFunctionBreakpoints"])

    def test_a_named_function_stops_on_entry_to_it(self):
        client = self.client(COUNTER, launch=False)
        self.launch(client)
        reported = self.set_function_breakpoints(client, "tick")
        self.assertTrue(reported[0]["verified"])
        self.assertEqual(reported[0]["source"]["path"], client.program_path)
        self.configuration_done(client)
        self.assertStopped(client, "breakpoint")

    def test_an_unknown_name_is_unverified(self):
        client = self.client(COUNTER, launch=False)
        self.launch(client)
        reported = self.set_function_breakpoints(client, "nosuchfn")
        self.assertFalse(reported[0]["verified"])
        self.assertIn("nosuchfn", reported[0]["message"])

    def test_they_survive_a_source_request(self):
        # The two sets are independent; replacing one must not drop the other.
        client = self.client(COUNTER, launch=False)
        self.launch(client)
        self.set_function_breakpoints(client, "tick")
        self.set_breakpoints(client, 12)
        self.configuration_done(client)
        for _ in range(3):          # tick twice, then line 12
            self.assertStopped(client, "breakpoint")
            client.send("continue")
            client.wait_for_response("continue")
        client.wait_for_event("terminated")

    def test_an_empty_request_clears_them(self):
        client = self.client(COUNTER, launch=False)
        self.launch(client)
        self.set_function_breakpoints(client, "tick")
        self.assertEqual(self.set_function_breakpoints(client), [])
        self.configuration_done(client)
        client.wait_for_event("terminated")
        self.assertEqual(client.events("stopped"), [])


class TestMalformed(BreakpointTestCase):
    def test_a_request_without_a_source_path_is_refused(self):
        client = self.client(COUNTER, launch=False)
        client.send("setBreakpoints", source={}, breakpoints=[{"line": 1}])
        reply = client.wait_for_response("setBreakpoints")
        self.assertFalse(reply["success"])


if __name__ == "__main__":
    unittest.main()
