"""The VM thread, stops, and resuming.

The failure this milestone exists to prevent is a deadlock in the handoff
between the request loop and the program, so every test here drives a real
adapter over a socket and every wait has a deadline.
"""

import unittest

from tests.harness import DapTestCase

HELLO = 'fn main(): int { println("hello"); return 0; }'

SPINNING = """
fn main(): int {
    println("running");
    while (true) { let x: int = 1; }
    return 0;
}
"""

FAULTING = """
fn main(): int {
    let z: int = 0;
    println(10 / z);
    return 0;
}
"""


class TestStopOnEntry(DapTestCase):
    def test_the_program_stops_before_anything_runs(self):
        client = self.client(HELLO, stop_on_entry=True)
        self.assertStopped(client, "entry")
        self.assertEqual(client.output(), "",
                         "entry means before the first instruction, not after it")

    def test_continuing_from_entry_runs_to_completion(self):
        client = self.client(HELLO, stop_on_entry=True)
        self.assertStopped(client, "entry")
        client.send("continue")
        client.wait_for_event("terminated")
        self.assertIn("hello", client.output())
        self.assertEqual(client.events("exited")[0]["body"]["exitCode"], 0)

    def test_continue_reports_all_threads(self):
        client = self.client(HELLO, stop_on_entry=True)
        self.assertStopped(client, "entry")
        client.send("continue")
        body = client.wait_for_response("continue")["body"]
        self.assertTrue(body["allThreadsContinued"])

    def test_without_it_the_program_just_runs(self):
        client = self.client(HELLO)
        client.wait_for_event("terminated")
        self.assertEqual(client.events("stopped"), [],
                         "the entry stop is internal when nobody asked for it")
        self.assertIn("hello", client.output())

    def test_the_stopped_event_names_the_thread(self):
        client = self.client(HELLO, stop_on_entry=True)
        body = self.assertStopped(client, "entry")["body"]
        self.assertEqual(body["threadId"], 1)
        self.assertTrue(body["allThreadsStopped"])

    def test_threads_are_answered_while_stopped(self):
        # The request loop has to stay responsive with the VM thread parked;
        # that it answers at all is the point, not what it answers.
        client = self.client(HELLO, stop_on_entry=True)
        self.assertStopped(client, "entry")
        client.send("threads")
        names = client.wait_for_response("threads")["body"]["threads"]
        self.assertEqual(names[0]["name"], "main")


class TestPause(DapTestCase):
    def test_a_running_program_can_be_paused(self):
        client = self.client(SPINNING)
        # Wait until it is genuinely running, so the pause is not racing the
        # start of the thread.
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.send("pause")
        client.wait_for_response("pause")
        self.assertStopped(client, "pause")

    def test_a_paused_program_can_be_continued_and_paused_again(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        for _ in range(2):
            client.send("pause")
            client.wait_for_response("pause")
            self.assertStopped(client, "pause")
            client.send("continue")
            client.wait_for_response("continue")

    def test_pause_before_a_program_exists_is_refused(self):
        client = self.client(HELLO, launch=False)
        client.send("pause")
        self.assertFalse(client.wait_for_response("pause")["success"])


class TestResumeRefusals(DapTestCase):
    def test_continue_while_running_is_refused(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.send("continue")
        reply = client.wait_for_response("continue")
        self.assertFalse(reply["success"])
        self.assertIn("not suspended", reply["message"])

    def test_continue_after_a_fault_is_refused(self):
        # The instruction that raised never completed, so there is no coherent
        # state to run on from.
        client = self.client(FAULTING)
        self.assertStopped(client, "exception")
        client.send("continue")
        reply = client.wait_for_response("continue")
        self.assertFalse(reply["success"])
        self.assertIn("faulted", reply["message"])


class TestFaults(DapTestCase):
    def test_a_fault_stops_for_inspection(self):
        client = self.client(FAULTING)
        body = self.assertStopped(client, "exception")["body"]
        self.assertIn("Division by zero", body["text"])
        self.assertEqual(client.events("terminated"), [],
                         "the program is still there to be looked at")

    def test_the_error_reaches_the_console(self):
        client = self.client(FAULTING)
        self.assertStopped(client, "exception")
        self.assertIn("Division by zero", client.output("stderr"))

    def test_disconnecting_from_a_fault_reports_the_exit_code(self):
        client = self.client(FAULTING)
        self.assertStopped(client, "exception")
        client.send("disconnect")
        client.wait_for_response("disconnect")
        client.wait_for_event("terminated")
        self.assertEqual(client.events("exited")[0]["body"]["exitCode"], 3)


class TestEnding(DapTestCase):
    def test_disconnecting_while_stopped_abandons_the_program(self):
        client = self.client(HELLO, stop_on_entry=True)
        self.assertStopped(client, "entry")
        client.send("disconnect")
        client.wait_for_response("disconnect")
        client.wait_for_event("terminated")
        self.assertEqual(client.output(), "", "it never got to run")
        self.assertEqual(client.events("exited"), [],
                         "an abandoned program has no exit code")

    def test_disconnecting_stops_a_spinning_program(self):
        # The one that hangs the adapter if the pause flag is not used to bring
        # a freely running program to a stop.
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.send("disconnect")
        client.wait_for_response("disconnect")
        client.wait_for_event("terminated")

    def test_terminate_stops_a_spinning_program(self):
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.send("terminate")
        client.wait_for_response("terminate")
        client.wait_for_event("terminated")

    def test_a_client_that_vanishes_stops_the_program(self):
        # No `disconnect`, just a dead socket. The adapter has to notice and
        # take the program down with it rather than spinning forever.
        client = self.client(SPINNING)
        client.wait_for(lambda m: m["type"] == "event" and m["event"] == "output"
                        and "running" in m["body"]["output"], "the program to start")
        client.hang_up()

    def test_the_program_is_reported_over_once(self):
        client = self.client(HELLO)
        client.wait_for_event("terminated")
        client.send("disconnect")
        client.wait_for_response("disconnect")
        client.hang_up()
        self.assertEqual(len(client.events("terminated")), 1)
        self.assertEqual(len(client.events("exited")), 1)


if __name__ == "__main__":
    unittest.main()
