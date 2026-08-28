"""next, stepIn and stepOut.

`stackTrace` is not implemented yet, so where a step landed is asserted from
what the program has printed by then. That is a weaker probe than a frame, but
it is the honest one available, and it happens to be the question that matters:
`next` over a call must run the call, and `stepIn` must not.
"""

import unittest

from tests.harness import FAULTING, SPINNING, DapTestCase

# Line numbers matter here:
#
#   1 fn helper   2 println   3 return   4 }   5 blank
#   6 fn main     7 println   8 helper() 9 println   10 return   11 }
NESTED = """fn helper(): int {
    println("in helper");
    return 1;
}

fn main(): int {
    println("one");
    helper();
    println("two");
    return 0;
}
"""


class SteppingTestCase(DapTestCase):
    def stopped_at_entry(self, source=NESTED):
        client = self.client(source, stop_on_entry=True)
        self.assertStopped(client, "entry")
        return client

    def step(self, client, command, reason="step"):
        client.send(command)
        client.wait_for_response(command)
        return self.assertStopped(client, reason)


class TestNext(SteppingTestCase):
    def test_one_line_runs(self):
        client = self.stopped_at_entry()
        self.step(client, "next")
        self.assertEqual(client.output(), "one\n")

    def test_a_call_runs_whole(self):
        client = self.stopped_at_entry()
        self.step(client, "next")
        self.step(client, "next")
        self.assertEqual(client.output(), "one\nin helper\n",
                         "next steps over the call, so the call happens")

    def test_stepping_off_the_end_finishes_the_program(self):
        client = self.stopped_at_entry()
        for _ in range(3):          # to line 8, 9, then 10 -- the return
            self.step(client, "next")
        client.send("next")
        client.wait_for_event("terminated")
        self.assertEqual(client.output(), "one\nin helper\ntwo\n")


class TestStepIn(SteppingTestCase):
    def test_a_call_is_entered(self):
        client = self.stopped_at_entry()
        self.step(client, "next")           # now on the call
        self.step(client, "stepIn")
        self.assertEqual(client.output(), "one\n",
                         "stopped inside helper, before its println")

    def test_a_line_without_a_call_behaves_like_next(self):
        client = self.stopped_at_entry()
        self.step(client, "stepIn")
        self.assertEqual(client.output(), "one\n")


class TestStepOut(SteppingTestCase):
    def test_the_rest_of_the_frame_runs(self):
        client = self.stopped_at_entry()
        self.step(client, "next")
        self.step(client, "stepIn")
        self.step(client, "stepOut")
        self.assertEqual(client.output(), "one\nin helper\n")

    def test_out_of_main_runs_to_the_end(self):
        # There is no caller to return to, which is also what the client's
        # button means at the outermost frame.
        client = self.stopped_at_entry()
        client.send("stepOut")
        client.wait_for_response("stepOut")
        client.wait_for_event("terminated")
        self.assertEqual(client.output(), "one\nin helper\ntwo\n")


class TestInteraction(SteppingTestCase):
    def test_a_step_that_lands_on_a_breakpoint_says_breakpoint(self):
        # The hook checks breakpoints before the step mode, and the more
        # specific reason is the one worth reporting.
        client = self.client(NESTED, launch=False)
        self.launch(client, stop_on_entry=True)
        reported = self.set_breakpoints(client, 9)
        self.configuration_done(client)
        self.assertStopped(client, "entry")
        self.step(client, "next")
        body = self.step(client, "next", reason="breakpoint")["body"]
        self.assertEqual(body["hitBreakpointIds"], [reported[0]["id"]])

    def test_stepping_can_follow_a_breakpoint(self):
        client = self.client(NESTED, launch=False)
        self.launch(client)
        self.set_breakpoints(client, 9)
        self.configuration_done(client)
        self.assertStopped(client, "breakpoint")
        self.step(client, "next")
        self.assertEqual(client.output(), "one\nin helper\ntwo\n")


class TestRefusals(SteppingTestCase):
    def test_stepping_a_running_program_is_refused(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        for command in ("next", "stepIn", "stepOut"):
            client.send(command)
            reply = client.wait_for_response(command)
            self.assertFalse(reply["success"])
            self.assertIn("not suspended", reply["message"])

    def test_stepping_after_a_fault_is_refused(self):
        client = self.client(FAULTING)
        self.assertStopped(client, "exception")
        for command in ("next", "stepIn", "stepOut"):
            client.send(command)
            reply = client.wait_for_response(command)
            self.assertFalse(reply["success"])
            self.assertIn("faulted", reply["message"])


if __name__ == "__main__":
    unittest.main()
