"""The VM thread, stops, and resuming.

These tests need a client that can *react*. The scripted transport in
tests/test_dap_session.py has decided every byte it will send before the
adapter says anything, so it can never answer a `stopped` event -- and every
failure worth catching here is one where the answer never arrives. So the
client here sits on a real socket, reads on its own thread, and waits for the
message it expects with a deadline.

Every wait is bounded. A deadlock in the handoff is the failure this milestone
exists to prevent, and a test that hangs forever reports it as nothing at all.
"""

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dap.protocol import MessageStream, ProtocolError
from dap.session import DebugSession

# Generous: it only ever elapses when something is genuinely stuck, and the
# programs under test take milliseconds.
TIMEOUT_SECONDS = 10.0


class LiveClient:
    """A DAP client on the other end of a socket pair."""

    def __init__(self, std_path=None):
        client_sock, adapter_sock = socket.socketpair()
        self._sockets = (client_sock, adapter_sock)
        # Kept so they can be closed explicitly: a BufferedWriter flushed by
        # the garbage collector after its socket is gone prints a traceback
        # nobody can catch.
        self._files = [sock.makefile(mode)
                       for sock in self._sockets for mode in ("rb", "wb")]
        self._stream = MessageStream(self._files[0], self._files[1])
        self.session = DebugSession(MessageStream(self._files[2], self._files[3]),
                                    std_path)

        self.messages = []
        self._cursor = 0
        self._closed = False
        self._condition = threading.Condition()

        self._serving = threading.Thread(target=self._serve, daemon=True)
        self._serving.start()
        self._reading = threading.Thread(target=self._drain, daemon=True)
        self._reading.start()

    # -- the two background threads --------------------------------------

    def _serve(self):
        try:
            self.session.serve()
        finally:
            # The client's reader is blocked on this socket; without the
            # shutdown it would wait out its deadline after a clean exit.
            self._shutdown(self._sockets[1])

    def _drain(self):
        while True:
            try:
                message = self._stream.read()
            except (OSError, ProtocolError, ValueError):
                message = None
            with self._condition:
                if message is None:
                    self._closed = True
                else:
                    self.messages.append(message)
                self._condition.notify_all()
                if message is None:
                    return

    @staticmethod
    def _shutdown(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # -- driving ---------------------------------------------------------

    def send(self, command, **arguments):
        self._stream.write({"type": "request", "command": command,
                            "arguments": arguments})

    def wait_for(self, predicate, what):
        """The next message matching `predicate`, consuming everything before it."""
        deadline = time.monotonic() + TIMEOUT_SECONDS
        with self._condition:
            while True:
                while self._cursor < len(self.messages):
                    message = self.messages[self._cursor]
                    self._cursor += 1
                    if predicate(message):
                        return message
                remaining = deadline - time.monotonic()
                if self._closed or remaining <= 0:
                    raise AssertionError(f"timed out waiting for {what}")
                self._condition.wait(remaining)

    def wait_for_event(self, name):
        return self.wait_for(lambda m: m["type"] == "event" and m["event"] == name,
                             f"event '{name}'")

    def wait_for_response(self, command):
        return self.wait_for(
            lambda m: m["type"] == "response" and m["command"] == command,
            f"response to '{command}'")

    def events(self, name):
        with self._condition:
            return [m for m in self.messages
                    if m["type"] == "event" and m["event"] == name]

    def output(self, category="stdout"):
        return "".join(m["body"]["output"] for m in self.events("output")
                       if m["body"]["category"] == category)

    def hang_up(self):
        """Vanish without a `disconnect`, the way a crashed client does."""
        for sock in self._sockets:
            self._shutdown(sock)
        self._join()

    def close(self):
        """Leave the way a client does, then tear the transport down."""
        try:
            self.send("disconnect")
            self.wait_for_response("disconnect")
        except (OSError, ValueError, AssertionError):
            pass            # already gone, or never got that far
        for sock in self._sockets:
            self._shutdown(sock)
        self._join()
        for stream in self._files:
            try:
                stream.close()
            except OSError:
                pass
        for sock in self._sockets:
            sock.close()

    def _join(self):
        self._serving.join(TIMEOUT_SECONDS)
        self._reading.join(TIMEOUT_SECONDS)
        if self._serving.is_alive():
            raise AssertionError("the adapter did not stop serving")


class ThreadingTestCase(unittest.TestCase):
    def client(self, source, *, stop_on_entry=False, args=None, launch=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "main.ql"
        path.write_text(source, encoding="utf-8")

        client = LiveClient()
        self.addCleanup(client.close)
        client.send("initialize")
        client.wait_for_response("initialize")
        if launch:
            client.send("launch", program=str(path), stopOnEntry=stop_on_entry,
                        args=list(args or []))
            client.wait_for_response("launch")
            client.send("configurationDone")
            client.wait_for_response("configurationDone")
        return client

    def assertStopped(self, client, reason):
        stopped = client.wait_for_event("stopped")
        self.assertEqual(stopped["body"]["reason"], reason)
        return stopped


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


class TestStopOnEntry(ThreadingTestCase):
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


class TestPause(ThreadingTestCase):
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


class TestResumeRefusals(ThreadingTestCase):
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


class TestFaults(ThreadingTestCase):
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


class TestEnding(ThreadingTestCase):
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
