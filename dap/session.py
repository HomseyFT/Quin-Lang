"""The DAP session: lifecycle, request dispatch, and events.

What this milestone covers is a program run start to finish under a real
client, with its output in the debug console and an exit code at the end. No
breakpoints and no stepping yet, so there is no VM thread: the program runs on
the dispatch thread and nothing needs synchronising.

The one structural decision already made here is **compile and start are
different moments**. `launch` compiles; `configurationDone` starts. Clients
disagree about the order they send those two in, and about whether breakpoints
come before or after, so whichever arrives second is the one that starts the
program. That turns an ordering question into a flag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from compiler.driver_vm import process_exit_code
from compiler.pipeline import CompileError, compile_path, describe_error
from dap.protocol import MessageStream, ProtocolError, event, response
from runtime.vm import QuinVM, VMError

# What the adapter tells the client it can do. Declaring a capability that is
# not implemented is worse than omitting one: the client enables UI for it and
# the UI then fails. Everything here is switched on as its milestone lands.
CAPABILITIES = {
    "supportsConfigurationDoneRequest": True,
    "supportsTerminateRequest": True,
    "supportsFunctionBreakpoints": False,
    "supportsEvaluateForHovers": False,
    "supportsSetVariable": False,
    "supportsConditionalBreakpoints": False,
    "supportsHitConditionalBreakpoints": False,
    "supportsStepBack": False,
    "supportsRestartRequest": False,
    "supportsExceptionInfoRequest": False,
    "exceptionBreakpointFilters": [],
}

# QuinVM is single-threaded, but DAP has no way to say so: every stopped event
# and every stepping request names a thread, and clients show no call stack
# without one.
THREAD_ID = 1
THREADS = {"threads": [{"id": THREAD_ID, "name": "main"}]}

# The driver's exit code for a fault, reused so the debug console agrees with
# what the same program would report from a shell.
EXIT_RUNTIME_ERROR = 3


class AdapterIO:
    """Program output as `output` events, and no input.

    The adapter's own stdout is carrying the protocol, so a program that
    printed to it directly would corrupt the stream. This is why `ProgramIO`
    exists at all.
    """

    def __init__(self, session: "DebugSession"):
        self._session = session
        self._warned = False

    def write(self, text: str) -> None:
        self._session.emit_output(text)

    def read_line(self) -> str:
        """End of input, always.

        DAP has no standard reverse request for reading a line, so a program
        run under this adapter sees an empty stdin. `""` is exactly the
        end-of-input value -- a blank line would be `"\\n"` -- so a reading
        program terminates rather than misreading a blank line as data.

        Said once. A read loop would otherwise fill the console with the same
        notice.
        """
        if not self._warned:
            self._warned = True
            self._session.emit_output(
                "Program input is not available under the debugger; "
                "read_line() reports end of input.\n",
                category="console",
            )
        return ""


class DebugSession:
    """One client connection."""

    def __init__(self, stream: MessageStream, std_path: Path = None):
        self.stream = stream
        self.std_path = std_path
        self._running = True

        self._program = None          # set by launch, on success
        self._launch_args: Optional[Dict[str, Any]] = None
        self._configuration_done = False
        self._started = False

    # -- the loop --------------------------------------------------------

    def serve(self) -> None:
        """Read and dispatch until the client disconnects or the stream ends."""
        while self._running:
            try:
                request = self.stream.read()
            except ProtocolError as e:
                # The stream is desynchronised, so there is nothing to reply
                # to and nowhere to resume from.
                self.emit_output(f"Protocol error: {e}\n", category="stderr")
                return
            if request is None:
                return
            self._dispatch(request)

    def _dispatch(self, request: Dict[str, Any]) -> None:
        if request.get("type") != "request":
            return          # responses and events from a client are not ours
        handler = getattr(self, f"_on_{request.get('command', '')}", None)
        if handler is None:
            self.reply(request, success=False,
                       message=f"unsupported request '{request.get('command')}'")
            return
        handler(request)

    # -- sending ---------------------------------------------------------

    def reply(self, request, body=None, *, success=True, message=None) -> None:
        self.stream.write(response(request, body, success=success, message=message))

    def emit(self, name: str, body=None) -> None:
        self.stream.write(event(name, body))

    def emit_output(self, text: str, category: str = "stdout") -> None:
        """`stdout` is the program talking. `stderr` is a diagnostic about it.
        `console` is the adapter talking about itself, which clients style
        differently so the two are not confused."""
        self.emit("output", {"category": category, "output": text})

    # -- requests --------------------------------------------------------

    def _on_initialize(self, request) -> None:
        self.reply(request, dict(CAPABILITIES))
        # After the response, never before: a client that receives `initialized`
        # first has nothing to attach its breakpoint configuration to.
        self.emit("initialized")

    def _on_launch(self, request) -> None:
        args = request.get("arguments") or {}
        program_path = args.get("program")
        if not program_path:
            self.reply(request, success=False, message="launch needs a 'program' path")
            return

        try:
            program, warnings = compile_path(Path(program_path), self.std_path)
        except CompileError as e:
            text = describe_error(e)
            # Both channels: the response is what the client reports, the
            # output event is what the user actually reads.
            self.emit_output(text + "\n", category="stderr")
            self.reply(request, success=False, message=text)
            # Nothing ran, so there is no exit code and no `exited` event.
            self.emit("terminated")
            return

        for warning in warnings:
            self.emit_output(f"Warning: {warning}\n", category="stderr")

        self._program = program
        self._launch_args = args
        self.reply(request)
        self._start_if_ready()

    def _on_configurationDone(self, request) -> None:
        self._configuration_done = True
        self.reply(request)
        self._start_if_ready()

    def _on_threads(self, request) -> None:
        self.reply(request, dict(THREADS))

    def _on_disconnect(self, request) -> None:
        self.reply(request)
        self._running = False

    def _on_terminate(self, request) -> None:
        self.reply(request)
        self.emit("terminated")
        self._running = False

    # -- running ---------------------------------------------------------

    def _start_if_ready(self) -> None:
        """Start once both `launch` and `configurationDone` have arrived.

        Which of them is second varies by client, so neither one starts the
        program on its own.
        """
        if self._started or self._program is None or not self._configuration_done:
            return
        self._started = True
        self._run()

    def _run(self) -> None:
        args = self._launch_args or {}
        argv = [str(args.get("program", ""))] + list(args.get("args") or [])
        vm = QuinVM(self._program.code, self._program.functions,
                    self._program.strings, self._program.structs,
                    self._program.source_map, AdapterIO(self), argv)
        try:
            exit_value = vm.run_main()
        except VMError as e:
            # Without stops there is nowhere to pause and inspect, so the fault
            # is reported the way the CLI reports it and the session ends.
            self.emit_output(f"Runtime error: {e}\n", category="stderr")
            self.emit("exited", {"exitCode": EXIT_RUNTIME_ERROR})
            self.emit("terminated")
            return
        code = process_exit_code(exit_value)
        self.emit_output(f"Program exited with code {code}\n", category="console")
        self.emit("exited", {"exitCode": code})
        self.emit("terminated")
