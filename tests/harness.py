"""Helpers for compiling and running QuinLang source inside tests.

Tests describe programs as strings and assert on what they print or which
error they raise, so they exercise the whole pipeline (lex, parse, resolve,
type-check, lower, interpret) rather than any single pass in isolation.
"""

from __future__ import annotations

import io
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from compiler.resolver import ImportResolver, ResolveError
from compiler.sema import SemanticAnalyzer, SemanticError
from compiler.codegen_vm import CodeGenVM, CodegenError
from dap.protocol import MessageStream, ProtocolError
from dap.session import DebugSession as DapSession
from runtime.program_io import CaptureIO
from runtime.vm import QuinVM, VMError

REPO_ROOT = Path(__file__).resolve().parent.parent
STD_PATH = REPO_ROOT / "std"
EXAMPLES_PATH = REPO_ROOT / "examples"
GOLDEN_PATH = Path(__file__).resolve().parent / "golden"

# Every way the front end can reject a program. Lexer and parser errors reach
# callers wrapped in ResolveError, because the resolver is what reads files.
COMPILE_ERRORS = (ResolveError, SemanticError, CodegenError)


@dataclass
class Run:
    """The observable result of running a program to completion."""
    stdout: str
    exit_value: int


def compile_file(path: Path):
    """Compile a .ql file to a CompiledProgram."""
    resolved = ImportResolver(STD_PATH).resolve(Path(path))
    ctx = SemanticAnalyzer().analyze(resolved.program)
    return CodeGenVM().generate(resolved.program, ctx)


def compile_source(source: str):
    """Compile source text by staging it as a file, so includes resolve."""
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        return compile_file(entry)


def warnings_for(source: str) -> list:
    """The compile-time warnings a program produces, as strings.

    Warnings live on the semantic Context, so tests can read them directly
    rather than capturing the driver's stderr.
    """
    with tempfile.TemporaryDirectory() as td:
        entry = Path(td) / "main.ql"
        entry.write_text(source, encoding="utf-8")
        resolved = ImportResolver(STD_PATH).resolve(entry)
        ctx = SemanticAnalyzer().analyze(resolved.program)
        return [str(w) for w in ctx.warnings]


def _run(program, stdin: str = "", args=None) -> Run:
    """Run a program with its I/O captured, never the process's.

    Output goes to a sink rather than through redirect_stdout, and input comes
    from `stdin` rather than the terminal the tests are running in. A test that
    reads input would otherwise block on whatever stdin the runner happened to
    have, which is not a thing to discover in CI.
    """
    sink = CaptureIO(stdin)
    exit_value = vm_for(program, sink, args).run_main()
    return Run(sink.text, exit_value)


def vm_for(program, io=None, args=None) -> QuinVM:
    """A VM loaded with a CompiledProgram, source map included, so a runtime
    error in a test reports the same location a user would see.

    `io` sends the program's output somewhere other than stdout, and `args` is
    what argc()/argv() report -- both of which anything embedding the VM
    supplies for itself.
    """
    return QuinVM(program.code, program.functions, program.strings,
                  program.structs, program.source_map, io, args)


def run_file(path: Path, stdin: str = None) -> Run:
    """Run a .ql file. Input comes from `<name>.in` beside it when it exists,
    so an example that reads can still have one fixed expected output."""
    if stdin is None:
        fixture = path.with_suffix(".in")
        stdin = fixture.read_text(encoding="utf-8") if fixture.exists() else ""
    return _run(compile_file(path), stdin)


def run_source(source: str, stdin: str = "", args=None) -> Run:
    return _run(compile_source(source), stdin, args)


class QuinTestCase(unittest.TestCase):
    """Assertions phrased in terms of what a QuinLang program does."""

    def assertOutput(self, source: str, expected: str, msg: Optional[str] = None):
        """Assert a program runs and prints exactly `expected`.

        `expected` is compared after stripping leading/trailing blank lines, so
        tests can use triple-quoted strings without fighting indentation.
        """
        actual = run_source(source).stdout
        self.assertEqual(actual.strip("\n"), expected.strip("\n"), msg)

    def assertPrints(self, source: str, *lines: str):
        """Assert a program prints exactly these lines, in order."""
        self.assertOutput(source, "\n".join(lines))

    def assertPrintsGiven(self, source: str, expected: str, stdin: str = "",
                          args=None):
        """assertOutput for a program that reads input or arguments."""
        actual = run_source(source, stdin, args).stdout
        self.assertEqual(actual.strip("\n"), expected.strip("\n"))

    def assertExprPrints(self, expr: str, expected: str):
        """Assert `println(<expr>);` inside a bare main prints `expected`."""
        self.assertOutput(f"fn main(): int {{ println({expr}); return 0; }}", expected)

    def assertCompileError(self, source: str, expected_substring: str) -> str:
        """Assert compilation fails with a message containing `expected_substring`."""
        try:
            compile_source(source)
        except COMPILE_ERRORS as e:
            message = str(e)
            self.assertIn(
                expected_substring, message,
                f"wrong compile error.\n  expected substring: {expected_substring!r}"
                f"\n  actual message:     {message!r}",
            )
            return message
        self.fail(
            f"expected a compile error containing {expected_substring!r}, "
            f"but the program compiled"
        )

    def assertRuntimeError(self, source: str, expected_substring: str) -> str:
        """Assert the program compiles but the VM faults at run time."""
        try:
            run_source(source)
        except VMError as e:
            message = str(e)
            self.assertIn(
                expected_substring, message,
                f"wrong runtime error.\n  expected substring: {expected_substring!r}"
                f"\n  actual message:     {message!r}",
            )
            return message
        self.fail(
            f"expected a runtime error containing {expected_substring!r}, "
            f"but the program ran to completion"
        )

    def assertCompileWarning(self, source: str, expected_substring: str) -> str:
        """Assert a program compiles and warns, with a message containing this.

        Deliberately not named assertWarns: unittest already defines that for
        Python's own warnings, and shadowing it would break every caller.
        """
        found = warnings_for(source)
        self.assertTrue(found, f"expected a warning containing {expected_substring!r}, got none")
        joined = " | ".join(found)
        self.assertIn(expected_substring, joined,
                      f"wrong warning.\n  expected substring: {expected_substring!r}"
                      f"\n  actual: {joined!r}")
        return joined

    def assertNoCompileWarnings(self, source: str):
        found = warnings_for(source)
        self.assertEqual(found, [], f"expected no warnings, got: {found}")

    def assertCompiles(self, source: str):
        """Assert a program type-checks and lowers without error."""
        try:
            compile_source(source)
        except COMPILE_ERRORS as e:
            self.fail(f"expected the program to compile, but got: {e}")


# -- debugger --------------------------------------------------------------
#
# The debugger drives itself through a callback, so a test supplies one instead
# of a terminal. Nothing here needs stdin, and the program's own output is kept
# apart from the session's so assertions can name one or the other.


def debug_trace(source: str, mode, setup=None, limit: int = 500):
    """(function, line) at every stop, running the whole program in one mode.

    `setup(debugger)` runs before the program does, which is where a test sets
    breakpoints. `limit` stops a test hanging if a step mode never advances.
    """
    from runtime.debugger import Debugger

    program = compile_source(source)
    stops = []

    def on_stop(dbg, vm, stop):
        stops.append((stop.frame.function, stop.frame.line))
        if len(stops) >= limit:
            raise AssertionError(f"more than {limit} stops; a step mode is not advancing")
        dbg.resume(mode, vm)

    debugger = Debugger(program, on_stop)
    if setup is not None:
        setup(debugger)
    debugger.run(vm_for(program, CaptureIO()))
    return stops


def debug_session(source: str, commands) -> str:
    """Everything the interactive front end printed, given these commands.

    The program's own stdout is captured separately and discarded: a test that
    cares about it uses run_source.
    """
    from compiler.debug import DebugSession

    program = compile_source(source)
    remaining = list(commands)
    transcript = io.StringIO()

    def read(_prompt: str) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    session = DebugSession(program, vm_for(program, CaptureIO()),
                           read=read, out=transcript)
    try:
        session.run()
    except VMError:
        pass              # a post-mortem session ends by re-raising the fault
    return transcript.getvalue()


def main_wrapping(body: str) -> str:
    """Wrap statements in a `fn main(): int` that returns 0."""
    return f"fn main(): int {{\n{body}\n    return 0;\n}}"


# -- the DAP adapter ---------------------------------------------------------
#
# The adapter is two threads, so a test that has decided every byte it will
# send before starting cannot drive one: it can never answer a `stopped` event.
# This client sits on a real socket, reads on its own thread, and waits for the
# message it expects with a deadline -- bounded, because a deadlock reported as
# a hang is a test that reports nothing at all.

# Generous: it only elapses when something is genuinely stuck, and the programs
# under test take milliseconds.
DAP_TIMEOUT_SECONDS = 10.0


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
        self.session = DapSession(MessageStream(self._files[2], self._files[3]),
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
        deadline = time.monotonic() + DAP_TIMEOUT_SECONDS
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
        self._serving.join(DAP_TIMEOUT_SECONDS)
        self._reading.join(DAP_TIMEOUT_SECONDS)
        if self._serving.is_alive():
            raise AssertionError("the adapter did not stop serving")


# Programs a DAP test needs by shape rather than by content: one that never
# stops on its own, and one that faults partway.
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


class DapTestCase(unittest.TestCase):
    """A test that drives the adapter through a LiveClient."""

    def write_program(self, source: str) -> str:
        """A .ql file that outlives the test, so a session can compile it."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "main.ql"
        path.write_text(source, encoding="utf-8")
        return str(path)

    def write_program_behind_a_symlink(self, source: str) -> str:
        """The same file, named through a symlinked directory.

        A path the client sends and the resolved one then differ, which is the
        ordinary case on macOS -- /tmp is /private/tmp -- and on any checkout
        reached through a link. Skips where symlinks need a privilege we may
        not have, which on Windows is the default.
        """
        real = self.write_program(source)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        link = Path(directory.name) / "link"
        try:
            link.symlink_to(Path(real).parent, target_is_directory=True)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"symlinks unavailable: {e}")
        return str(link / "main.ql")

    def connect(self) -> LiveClient:
        """An initialized client with nothing launched yet."""
        client = LiveClient()
        self.addCleanup(client.close)
        client.send("initialize")
        client.wait_for_response("initialize")
        return client

    def client(self, source, *, stop_on_entry=False, args=None, launch=True):
        """The common case: initialized, launched, and configured."""
        client = self.connect()
        client.program_path = self.write_program(source)
        if launch:
            self.launch(client, stop_on_entry=stop_on_entry, args=args)
            self.configuration_done(client)
        return client

    def launch(self, client, *, stop_on_entry=False, args=None):
        client.send("launch", program=client.program_path,
                    stopOnEntry=stop_on_entry, args=list(args or []))
        return client.wait_for_response("launch")

    def configuration_done(self, client):
        client.send("configurationDone")
        return client.wait_for_response("configurationDone")

    def set_breakpoints(self, client, *lines, path=None):
        """Replace one source's breakpoints; returns the reported array."""
        client.send("setBreakpoints",
                    source={"path": path or client.program_path},
                    breakpoints=[{"line": line} for line in lines])
        return client.wait_for_response("setBreakpoints")["body"]["breakpoints"]

    def set_function_breakpoints(self, client, *names):
        client.send("setFunctionBreakpoints",
                    breakpoints=[{"name": name} for name in names])
        return client.wait_for_response(
            "setFunctionBreakpoints")["body"]["breakpoints"]

    def assertStopped(self, client, reason):
        stopped = client.wait_for_event("stopped")
        self.assertEqual(stopped["body"]["reason"], reason)
        return stopped
