"""The DAP session: lifecycle, request dispatch, events, and the VM thread.

The program runs on its own thread so the request loop stays responsive while
it is stopped. The two threads meet in one place: `_on_stop` fills in a
`Suspension` and waits on a condition, and a resume request fills in the mode
and wakes it. Nothing else is shared, and inspection is only ever answered
while that handoff is parked.

The one other structural decision here is **compile and start are different
moments**. `launch` compiles; `configurationDone` starts. Clients disagree
about the order they send those two in, and about whether breakpoints come
before or after, so whichever arrives second is the one that starts the
program. That turns an ordering question into a flag.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from compiler.driver_vm import process_exit_code
from compiler.pipeline import CompileError, compile_path, describe_error
from dap.protocol import MessageStream, ProtocolError, event, response
from runtime.debugger import Debugger, Mode, Quit, Stop, StopReason
from runtime.vm import QuinVM, VMError

# What the adapter tells the client it can do. Declaring a capability that is
# not implemented is worse than omitting one: the client enables UI for it and
# the UI then fails. Everything here is switched on as its milestone lands.
CAPABILITIES = {
    "supportsConfigurationDoneRequest": True,
    "supportsTerminateRequest": True,
    "supportsCancelRequest": False,
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

# How long to wait for the program's thread after asking it to stop. A hung
# debuggee must not keep the adapter from closing.
JOIN_TIMEOUT_SECONDS = 5.0

# StopReason -> the DAP `reason` string clients display.
STOP_REASONS = {
    StopReason.ENTRY: "entry",
    StopReason.BREAKPOINT: "breakpoint",
    StopReason.STEP: "step",
    StopReason.PAUSE: "pause",
    StopReason.FAULT: "exception",
}


@dataclass
class Suspension:
    """The handoff between the two threads while the program is stopped.

    The program's thread fills in `stop` and waits; the request loop fills in
    `resume_mode` and wakes it. Both are guarded by the session's condition.

    Ending the session is *not* a field here, because a disconnect can arrive
    while the program is running freely and there is no suspension to write it
    into. It lives on the session instead.
    """
    stop: Stop
    resume_mode: Optional[Mode] = None


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
        self._stop_on_entry = False

        # Shared with the VM thread; every field below is read and written
        # only under the condition.
        self._condition = threading.Condition()
        self._suspension: Optional[Suspension] = None
        self._disconnecting = False
        self._ended = False

        self._thread: Optional[threading.Thread] = None
        self._debugger: Optional[Debugger] = None
        self._vm: Optional[QuinVM] = None
        self._faulted = False

    # -- the loop --------------------------------------------------------

    def serve(self) -> None:
        """Read and dispatch until the client disconnects or the stream ends."""
        try:
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
        finally:
            # The program outlives the request loop otherwise, writing events
            # into a stream nobody is reading.
            self._wait_for_program()

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
        self._send(response(request, body, success=success, message=message))

    def emit(self, name: str, body=None) -> None:
        self._send(event(name, body))

    def _send(self, message: Dict[str, Any]) -> None:
        """Write, unless the client has gone.

        Losing the transport mid-run is ordinary -- the user closed the editor
        -- and there is nobody left to report it to. The program's thread
        writes here too, so raising would kill it with a traceback on the way
        out of a session that is already over.
        """
        try:
            self.stream.write(message)
        except (OSError, ValueError):
            self._running = False

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
            self._end(None)
            return

        for warning in warnings:
            self.emit_output(f"Warning: {warning}\n", category="stderr")

        self._program = program
        self._launch_args = args
        self._stop_on_entry = bool(args.get("stopOnEntry"))
        self.reply(request)
        self._start_if_ready()

    def _on_configurationDone(self, request) -> None:
        self._configuration_done = True
        self.reply(request)
        self._start_if_ready()

    def _on_threads(self, request) -> None:
        self.reply(request, dict(THREADS))

    def _on_continue(self, request) -> None:
        refusal = self._refuse_resume()
        if refusal is not None:
            self.reply(request, success=False, message=refusal)
            return
        # Reply before releasing the program. Once it runs it may stop again
        # at once, and a `stopped` event that overtakes the response to the
        # request which caused it reads as a stop the client never asked for.
        self.reply(request, {"allThreadsContinued": True})
        self._release(Mode.RUN)

    def _on_pause(self, request) -> None:
        """Ask for a stop; do not wait for one.

        The stop happens at the next instruction boundary and announces itself
        with a `stopped` event. Holding the response until then would block the
        request loop inside a request, which is the deadlock this whole design
        is arranged to avoid.
        """
        if self._debugger is None:
            self.reply(request, success=False, message="no program is running")
            return
        self._debugger.pause()
        self.reply(request)

    def _on_disconnect(self, request) -> None:
        self.reply(request)
        self._end_session()

    def _on_terminate(self, request) -> None:
        self.reply(request)
        self._end_session()

    # -- resuming --------------------------------------------------------

    def _refuse_resume(self) -> Optional[str]:
        """Why the program cannot be resumed right now, or None if it can."""
        with self._condition:
            if self._suspension is None:
                return "the program is not suspended"
            if self._suspension.stop.reason is StopReason.FAULT:
                # The instruction that raised never completed, so there is no
                # coherent state to run on from.
                return "the program has faulted and cannot continue"
        return None

    def _release(self, mode: Mode) -> None:
        with self._condition:
            if self._suspension is not None:
                self._suspension.resume_mode = mode
                self._condition.notify_all()

    # -- running ---------------------------------------------------------

    def _start_if_ready(self) -> None:
        """Start once both `launch` and `configurationDone` have arrived.

        Which of them is second varies by client, so neither one starts the
        program on its own.
        """
        if self._started or self._program is None or not self._configuration_done:
            return
        self._started = True

        args = self._launch_args or {}
        argv = [str(args.get("program", ""))] + list(args.get("args") or [])
        self._vm = QuinVM(self._program.code, self._program.functions,
                          self._program.strings, self._program.structs,
                          self._program.source_map, AdapterIO(self), argv)
        self._debugger = Debugger(self._program, self._on_stop)
        # Daemon: a debuggee that ignores the pause flag -- a tight loop in the
        # VM's own C-level machinery, say -- must not keep the process alive.
        self._thread = threading.Thread(target=self._run_program,
                                        name="quinvm", daemon=True)
        self._thread.start()

    def _run_program(self) -> None:
        try:
            exit_value = self._debugger.run(self._vm)
        except Quit:
            # Abandoned: the client disconnected, or a fault was inspected and
            # then given up on.
            self._end(EXIT_RUNTIME_ERROR if self._faulted else None)
        except VMError as e:
            # Only reachable if the fault stop did not run; Debugger.run stops
            # first and re-raises, and that stop reports the error itself.
            self.emit_output(f"Runtime error: {e}\n", category="stderr")
            self._end(EXIT_RUNTIME_ERROR)
        except Exception as e:              # the thread must not die silently
            self.emit_output(f"Adapter error: {e}\n", category="stderr")
            self._end(None)
        else:
            code = process_exit_code(exit_value)
            self.emit_output(f"Program exited with code {code}\n", category="console")
            self._end(code)

    def _on_stop(self, debugger: Debugger, vm: QuinVM, stop: Stop) -> None:
        """The VM thread, parked. Runs only on that thread.

        Everything after the `stopped` event happens with the program frozen,
        which is what makes it safe for the request loop to read VM state.
        """
        if stop.reason is StopReason.ENTRY and not self._stop_on_entry:
            debugger.resume(Mode.RUN, vm)
            return
        if stop.reason is StopReason.FAULT:
            self._faulted = True
            self.emit_output(f"Runtime error: {stop.error}\n", category="stderr")

        with self._condition:
            if self._disconnecting:
                raise Quit()
            suspension = self._suspension = Suspension(stop)
            # Announced under the condition, so that a resume request arriving
            # the instant the client sees it finds a suspension to write into
            # rather than a program it is told is not stopped.
            self.emit("stopped", self._stopped_body(stop))
            while suspension.resume_mode is None and not self._disconnecting:
                self._condition.wait()
            self._suspension = None
            disconnecting = self._disconnecting

        if disconnecting:
            raise Quit()
        debugger.resume(suspension.resume_mode, vm)

    def _stopped_body(self, stop: Stop) -> Dict[str, Any]:
        body = {"reason": STOP_REASONS[stop.reason],
                "threadId": THREAD_ID,
                "allThreadsStopped": True}
        if stop.error is not None:
            # Clients show `description` in the stop banner and `text` in a
            # notification, so the full [line:col] message goes in the latter.
            body["description"] = "Runtime error"
            body["text"] = str(stop.error)
        return body

    # -- ending ----------------------------------------------------------

    def _end(self, exit_code: Optional[int]) -> None:
        """Report that the program is over, once.

        `None` means it was abandoned rather than finished, so there is no exit
        code: `exited` is omitted and only `terminated` is sent. Both threads
        can reach here -- the program ending and the client disconnecting race
        by nature -- so the guard is the point.
        """
        with self._condition:
            if self._ended:
                return
            self._ended = True
        if exit_code is not None:
            self.emit("exited", {"exitCode": exit_code})
        self.emit("terminated")

    def _end_session(self) -> None:
        """Stop the program, report it, and leave the request loop.

        A fault reports its exit code here rather than when it happened: the
        program was still there to be inspected until now.
        """
        self._kill_program()
        if self._started:
            self._end(EXIT_RUNTIME_ERROR if self._faulted else None)
        self._running = False

    def _wait_for_program(self) -> None:
        """Let the program finish on its own, then insist.

        A suspended program is skipped straight to insisting: it is parked
        waiting for a resume request, and the client that would send one is the
        one that just went away.
        """
        thread = self._thread
        if thread is None:
            return
        with self._condition:
            suspended = self._suspension is not None
        if not suspended:
            thread.join(JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            self._kill_program()

    def _kill_program(self) -> None:
        """Stop the program now, wherever it is.

        Two cases, and both are needed: if it is parked in `_on_stop` the flag
        alone wakes it, and if it is running freely the pause flag brings it to
        the next instruction boundary where it will see the flag.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        with self._condition:
            self._disconnecting = True
            self._condition.notify_all()
        self._debugger.pause()
        thread.join(JOIN_TIMEOUT_SECONDS)
