"""The DAP session, driven by scripted requests instead of an editor.

Debugging an adapter through VS Code is miserable, so the session speaks to an
in-memory stream here and the tests read the messages it produced. This is the
same shape as tests/test_debugger.py driving `Debugger` with a scripted
`on_stop`.

The lifecycle is where adapters go wrong, and the specific trap is that clients
disagree about the order of `launch` and `configurationDone`. Both orderings are
tested, because supporting only the common one produces an adapter that works
for whoever wrote it and hangs for everyone else.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from dap.protocol import MessageStream
from dap.session import DebugSession


def run_session(requests, std_path=None):
    """Feed a list of requests to a session and return everything it sent."""
    raw = b""
    for seq, request in enumerate(requests, 1):
        body = json.dumps(dict(request, type="request", seq=seq)).encode("utf-8")
        raw += f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body

    out = io.BytesIO()
    DebugSession(MessageStream(io.BytesIO(raw), out), std_path).serve()

    reader = MessageStream(io.BytesIO(out.getvalue()), io.BytesIO())
    messages = []
    while True:
        message = reader.read()
        if message is None:
            return messages
        messages.append(message)


def responses(messages, command=None):
    return [m for m in messages if m["type"] == "response"
            and (command is None or m["command"] == command)]


def events(messages, name=None):
    return [m for m in messages if m["type"] == "event"
            and (name is None or m["event"] == name)]


def stdout_of(messages) -> str:
    return "".join(m["body"]["output"] for m in events(messages, "output")
                   if m["body"]["category"] == "stdout")


def stderr_of(messages) -> str:
    return "".join(m["body"]["output"] for m in events(messages, "output")
                   if m["body"]["category"] == "stderr")


class SessionTestCase(unittest.TestCase):
    def program(self, source: str) -> str:
        """A .ql file that outlives the test, so a session can compile it."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "main.ql"
        path.write_text(source, encoding="utf-8")
        return str(path)

    def launch(self, source: str, *, order="launch-first", args=None,
               extra=()) -> list:
        """Run a program to completion, in either client ordering."""
        path = self.program(source)
        launch = {"command": "launch",
                  "arguments": {"program": path, "args": list(args or [])}}
        done = {"command": "configurationDone"}
        pair = [launch, done] if order == "launch-first" else [done, launch]
        return run_session([{"command": "initialize"}] + pair + list(extra))


class TestInitialize(SessionTestCase):
    def test_capabilities_are_returned(self):
        messages = run_session([{"command": "initialize"}])
        body = responses(messages, "initialize")[0]["body"]
        self.assertTrue(body["supportsConfigurationDoneRequest"])

    def test_the_initialized_event_follows_the_response(self):
        # Before it, a client has nothing to attach its configuration to.
        messages = run_session([{"command": "initialize"}])
        kinds = [(m["type"], m.get("command") or m.get("event")) for m in messages]
        self.assertEqual(kinds, [("response", "initialize"), ("event", "initialized")])

    def test_unimplemented_capabilities_are_declared_false(self):
        # Declaring one you do not have is worse than omitting it: the client
        # enables UI that then fails.
        body = responses(run_session([{"command": "initialize"}]), "initialize")[0]["body"]
        self.assertFalse(body["supportsConditionalBreakpoints"])
        self.assertFalse(body["supportsSetVariable"])


class TestLifecycle(SessionTestCase):
    HELLO = 'fn main(): int { println("hi"); return 0; }'

    def test_launch_then_configuration_done_runs_the_program(self):
        self.assertEqual(stdout_of(self.launch(self.HELLO)), "hi\n")

    def test_configuration_done_then_launch_also_runs_it(self):
        # The other ordering clients produce. Supporting one and not the other
        # is an adapter that works only for whoever wrote it.
        self.assertEqual(stdout_of(self.launch(self.HELLO, order="done-first")), "hi\n")

    def test_the_program_runs_exactly_once(self):
        messages = self.launch(self.HELLO)
        self.assertEqual(stdout_of(messages).count("hi"), 1)
        self.assertEqual(len(events(messages, "exited")), 1)

    def test_launch_alone_does_not_start_it(self):
        path = self.program(self.HELLO)
        messages = run_session([{"command": "initialize"},
                                {"command": "launch", "arguments": {"program": path}}])
        self.assertEqual(stdout_of(messages), "", "configurationDone starts it")
        self.assertEqual(events(messages, "exited"), [])

    def test_configuration_done_alone_does_not_start_anything(self):
        messages = run_session([{"command": "initialize"},
                                {"command": "configurationDone"}])
        self.assertEqual(events(messages, "exited"), [])

    def test_exited_precedes_terminated(self):
        messages = self.launch(self.HELLO)
        order = [m["event"] for m in events(messages) if m["event"] in ("exited", "terminated")]
        self.assertEqual(order, ["exited", "terminated"])

    def test_disconnect_ends_the_session(self):
        messages = self.launch(self.HELLO, extra=[{"command": "disconnect"},
                                                  {"command": "threads"}])
        self.assertEqual(responses(messages, "threads"), [],
                         "requests after disconnect are not served")

    def test_threads_reports_the_one_thread(self):
        messages = run_session([{"command": "threads"}])
        self.assertEqual(responses(messages, "threads")[0]["body"],
                         {"threads": [{"id": 1, "name": "main"}]})


class TestExitCode(SessionTestCase):
    def code(self, source: str) -> int:
        return events(self.launch(source), "exited")[0]["body"]["exitCode"]

    def test_zero(self):
        self.assertEqual(self.code("fn main(): int { return 0; }"), 0)

    def test_a_nonzero_value(self):
        self.assertEqual(self.code("fn main(): int { return 42; }"), 42)

    def test_it_is_the_truncated_byte_the_shell_would_see(self):
        # Keeping the debugger honest about the `return 256` sharp edge rather
        # than papering over it.
        self.assertEqual(self.code("fn main(): int { return 256; }"), 0)


class TestFailures(SessionTestCase):
    def test_a_compile_error_fails_the_launch(self):
        messages = self.launch("fn main(): int { if (1) { } return 0; }")
        launch = responses(messages, "launch")[0]
        self.assertFalse(launch["success"])
        self.assertIn("If condition must be bool", launch["message"])

    def test_a_compile_error_also_reaches_the_console(self):
        # The response is what the client reports; the output event is what the
        # user actually reads.
        messages = self.launch("fn main(): int { if (1) { } return 0; }")
        self.assertIn("Semantic error", stderr_of(messages))

    def test_nothing_ran_so_there_is_no_exit_code(self):
        messages = self.launch("fn main(): int { if (1) { } return 0; }")
        self.assertEqual(events(messages, "exited"), [])
        self.assertEqual(len(events(messages, "terminated")), 1)

    def test_a_runtime_fault_is_reported_and_exits_three(self):
        messages = self.launch(
            'fn main(): int { println("before"); let z: int; return 1 / z; }')
        self.assertEqual(stdout_of(messages), "before\n", "output before it survives")
        self.assertIn("Division by zero", stderr_of(messages))
        self.assertEqual(events(messages, "exited")[0]["body"]["exitCode"], 3)

    def test_launch_without_a_program_is_refused(self):
        messages = run_session([{"command": "initialize"},
                                {"command": "launch", "arguments": {}}])
        self.assertFalse(responses(messages, "launch")[0]["success"])

    def test_an_unknown_request_does_not_end_the_session(self):
        messages = run_session([{"command": "initialize"},
                                {"command": "setBreakpoints"},
                                {"command": "threads"}])
        self.assertFalse(responses(messages, "setBreakpoints")[0]["success"])
        self.assertTrue(responses(messages, "threads")[0]["success"],
                        "the session carried on")

    def test_a_warning_reaches_the_console_without_stopping_the_run(self):
        messages = self.launch(
            "fn main(): int { return 300; }")   # exit code cannot represent it
        self.assertIn("Warning", stderr_of(messages))
        self.assertEqual(len(events(messages, "exited")), 1)


class TestProgramIO(SessionTestCase):
    def test_output_never_reaches_the_adapter_stdout(self):
        # The reason ProgramIO exists: the adapter's stdout is carrying the
        # protocol, so a println on it would corrupt the stream. Every message
        # parsing cleanly is the proof.
        messages = self.launch('fn main(): int { println("not protocol"); return 0; }')
        self.assertIn("not protocol", stdout_of(messages))
        self.assertTrue(all(m["type"] in ("response", "event") for m in messages))

    def test_arguments_reach_the_program(self):
        source = """
        fn main(): int {
            println(argc());
            for (let i = 1; i < argc(); i = i + 1) { println(argv(i)); }
            return 0;
        }
        """
        messages = self.launch(source, args=["alpha", "beta"])
        self.assertIn("alpha\nbeta\n", stdout_of(messages))

    def test_argv_zero_is_the_program(self):
        messages = self.launch("fn main(): int { println(argv(0)); return 0; }")
        self.assertIn("main.ql", stdout_of(messages))

    def test_reading_input_reports_end_of_input(self):
        # DAP has no reverse request for reading a line, so stdin is empty.
        # "" is exactly end of input -- a blank line would be "\n" -- so a
        # reading program terminates instead of misreading a blank line.
        messages = self.launch(
            'fn main(): int { println(str_len(read_line())); return 0; }')
        self.assertIn("0\n", stdout_of(messages))

    def test_the_input_notice_is_said_once(self):
        source = """
        fn main(): int {
            for (let i = 0; i < 5; i = i + 1) { let s: str = read_line(); }
            return 0;
        }
        """
        console = "".join(m["body"]["output"] for m in events(self.launch(source), "output")
                          if m["body"]["category"] == "console")
        self.assertEqual(console.count("not available"), 1,
                         "a read loop would otherwise flood the console")


class TestStreamHandling(SessionTestCase):
    def test_a_non_request_message_is_ignored(self):
        # Clients send responses to reverse requests; those are not ours to
        # dispatch.
        body = json.dumps({"seq": 1, "type": "event", "event": "whatever"}).encode()
        raw = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        out = io.BytesIO()
        DebugSession(MessageStream(io.BytesIO(raw), out)).serve()
        self.assertEqual(out.getvalue(), b"", "nothing to reply to")

    def test_a_malformed_stream_reports_and_stops(self):
        out = io.BytesIO()
        DebugSession(MessageStream(io.BytesIO(b"Content-Length: nope\r\n\r\n{}"),
                                   out)).serve()
        reader = MessageStream(io.BytesIO(out.getvalue()), io.BytesIO())
        self.assertIn("Protocol error", reader.read()["body"]["output"])


if __name__ == "__main__":
    unittest.main()
