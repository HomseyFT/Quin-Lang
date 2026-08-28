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
from collections import Counter
from typing import Any, Callable, Dict, Iterator, List, Optional

from compiler.driver_vm import process_exit_code
from compiler.pipeline import CompileError, describe_error, program_for
from dap.protocol import MessageStream, ProtocolError, event, response
from dap.values import Handles, evaluation, variable
from runtime.debugger import (Breakpoint, Debugger, DebuggerError, Mode, Quit,
                              Stop, StopReason)
from runtime.vm import QuinVM, VMError

# What the adapter tells the client it can do. Declaring a capability that is
# not implemented is worse than omitting one: the client enables UI for it and
# the UI then fails. Everything here is switched on as its milestone lands.
CAPABILITIES = {
    "supportsConfigurationDoneRequest": True,
    "supportsTerminateRequest": True,
    "supportsCancelRequest": False,
    "supportsFunctionBreakpoints": True,
    "supportsEvaluateForHovers": True,
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


def is_identifier(text: str) -> bool:
    """The lexer's own rule for a name, so the adapter accepts what the language
    calls one and nothing else."""
    if not text or not (text[0].isalpha() or text[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in text[1:])


def resolved_path(path: str) -> str:
    """The spelling `Function.source_file` uses.

    The resolver stamps every function with an absolute, resolved path, and
    clients send absolute paths that may still differ by a symlink or a `..`.
    Resolving both sides makes them comparable; the client's own spelling is
    what gets echoed back, so its markers land on the file it opened.
    """
    try:
        return str(Path(path).resolve())
    except OSError:
        return path


@dataclass
class ClientBreakpoint:
    """One breakpoint as the client asked for it, and where it landed.

    Ids are the adapter's own rather than `Debugger`'s, for two reasons: a
    breakpoint set before anything is compiled has no `Debugger` breakpoint yet
    and still needs an id to be referred to by, and two requested lines that
    resolve to the same pc share a single `Debugger` breakpoint while remaining
    two separate markers in the client's UI.

    `function` names a function breakpoint; otherwise it is a line in a file.
    """
    id: int
    function: Optional[str] = None
    client_path: str = ""
    path: str = ""
    line: int = 0

    # Filled in by resolution, and `reported` is the last body the client was
    # told, so a re-resolve knows whether it has news.
    resolved_file: str = ""
    resolved_line: Optional[int] = None
    message: str = ""
    reported: Optional[Dict[str, Any]] = None

    def resolve(self, debugger: Debugger) -> Optional[Breakpoint]:
        try:
            if self.function is not None:
                bp = debugger.break_at_function(self.function)
            else:
                bp = debugger.break_at_line(self.line, self.path)
        except DebuggerError as e:
            self.resolved_file, self.resolved_line, self.message = "", None, str(e)
            return None
        self.resolved_file, self.resolved_line, self.message = bp.file, bp.line, ""
        return bp

    def body(self, source: Callable[[str], Dict[str, str]]) -> Dict[str, Any]:
        """The DAP `Breakpoint`.

        `line` is the resolved one, which is the point: `break_at_line` walks
        forward past a blank line or a closing brace to the next line carrying
        code, and DAP has a channel for saying so, so the client moves its
        marker to where the breakpoint really is.
        """
        verified = self.resolved_line is not None
        body: Dict[str, Any] = {"id": self.id, "verified": verified}
        if self.message:
            body["message"] = self.message
        if self.function is not None:
            if verified:
                # A function breakpoint names no file, so which one it landed
                # in is only known after resolving -- and that is the resolver's
                # spelling, which the client may not share.
                body["source"] = source(self.resolved_file)
                body["line"] = self.resolved_line
            return body
        body["line"] = self.resolved_line if verified else self.line
        # Exactly the path the client sent, not a lookup: this record is the
        # one place it is known for certain.
        body["source"] = {"path": self.client_path,
                          "name": Path(self.client_path).name}
        return body


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

        # The client's desired breakpoints, which outlive any one resolution:
        # they arrive before there is a program to resolve them against, and
        # are re-resolved whenever the set changes.
        self._source_breakpoints: Dict[str, List[ClientBreakpoint]] = {}
        self._function_breakpoints: List[ClientBreakpoint] = []
        self._next_breakpoint_id = 1
        self._hit_ids: Dict[int, List[int]] = {}

        # Resolved path -> the spelling the client used for it. See _source.
        self._client_paths: Dict[str, str] = {}

        self._handles = Handles()

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

        # Before compiling, so that even a program that fails to compile is
        # reported back under the name the client launched it by.
        self._remember_path(program_path)

        try:
            # Either a .ql source or a .qlc that kept its debug tables. A
            # stripped one loads and runs, with no lines to stop on.
            program, warnings = program_for(Path(program_path), self.std_path)
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
        # Before the program starts, so breakpoints already sent are resolved
        # and reported rather than missed on the first run.
        self._debugger = Debugger(program, self._on_stop)
        self.reply(request)
        self._rebuild_breakpoints()
        self._start_if_ready()

    def _on_configurationDone(self, request) -> None:
        self._configuration_done = True
        self.reply(request)
        self._start_if_ready()

    def _on_stackTrace(self, request) -> None:
        if not self._require_suspended(request):
            return
        args = request.get("arguments") or {}
        frames = self._debugger.frames(self._vm)
        start = int(args.get("startFrame") or 0)
        levels = int(args.get("levels") or 0)
        window = frames[start:start + levels] if levels else frames[start:]
        self.reply(request, {
            "stackFrames": [self._stack_frame(view) for view in window],
            # The untruncated count, so a client that paged knows there is more.
            "totalFrames": len(frames),
        })

    def _on_scopes(self, request) -> None:
        """One scope per frame: QuinLang has no globals and no closures."""
        if not self._require_suspended(request):
            return
        frame = self._frame_for((request.get("arguments") or {}).get("frameId"))
        if frame is None:
            self.reply(request, success=False, message="unknown frame")
            return
        self.reply(request, {"scopes": [{
            "name": "Locals",
            "presentationHint": "locals",
            "variablesReference": self._handles.locals(frame.depth),
            "expensive": False,
        }]})

    def _on_variables(self, request) -> None:
        if not self._require_suspended(request):
            return
        reference = int((request.get("arguments") or {})
                        .get("variablesReference") or 0)
        entry = self._handles.get(reference)
        if entry is None:
            # Either invented, or left over from a previous stop. Both are
            # answered the same way: the values it named are gone.
            self.reply(request, success=False,
                       message="unknown or stale variablesReference")
            return
        kind, payload = entry
        variables = (self._frame_variables(payload) if kind == "locals"
                     else self._child_variables(payload))
        self.reply(request, {"variables": variables})

    def _on_evaluate(self, request) -> None:
        """A bare variable name, which is what hover and watch ask for.

        Anything else is refused rather than approximated. Evaluating a real
        expression means compiling a fragment against this frame's scope and
        running it on the suspended VM without disturbing the operand-stack
        balance RET checks -- a feature, not a fallback.
        """
        if not self._require_suspended(request):
            return
        args = request.get("arguments") or {}
        frame = self._frame_for(args.get("frameId"))
        if frame is None:
            self.reply(request, success=False, message="unknown frame")
            return

        expression = (args.get("expression") or "").strip()
        if not is_identifier(expression):
            self.reply(request, success=False,
                       message="only variable names can be evaluated")
            return

        matches = self._debugger.lookup_name(frame, expression)
        if not matches:
            self.reply(request, success=False,
                       message=f"no variable named '{expression}' in {frame.function}")
            return
        if len(matches) > 1:
            # Shadowed, and the slot table has no scope ranges to say which one
            # is live here. The Locals view shows both, named by slot.
            slots = ", ".join(str(info.slot) for info in matches)
            self.reply(request, success=False,
                       message=f"'{expression}' names more than one slot here "
                               f"({slots}); see Locals")
            return

        value = self._debugger.describe_local(self._vm, frame, matches[0])
        self.reply(request, evaluation(value, self._handles.value(value)))

    def _frame_for(self, frame_id) -> Optional[Any]:
        """The frame a request named, or the innermost one when it named none.

        DAP treats a missing `frameId` as the global scope. QuinLang has no
        globals, so the innermost frame is the only sensible reading -- and it
        is what a hover means anyway.
        """
        frames = self._debugger.frames(self._vm)
        if frame_id is None:
            return frames[0] if frames else None
        entry = self._handles.get(int(frame_id))
        if entry is None or entry[0] != "frame" or entry[1] >= len(frames):
            return None
        return frames[entry[1]]

    def _stack_frame(self, view) -> Dict[str, Any]:
        frame: Dict[str, Any] = {
            "id": self._handles.frame(view.depth),
            "name": view.function,
            # 0 means "no position", which happens for code no statement
            # produced. Clients handle it; a wrong line would be worse.
            "line": view.line or 0,
            "column": view.col or 0,
        }
        if view.file:
            frame["source"] = self._source(view.file)
        return frame

    def _frame_variables(self, depth: int) -> List[Dict[str, Any]]:
        frames = self._debugger.frames(self._vm)
        if depth >= len(frames):
            return []
        frame = frames[depth]
        infos = self._debugger.locals_of(frame)
        # A shadowed name has two slots and the slot table carries no scope
        # ranges, so which one is live here is not knowable. Both are shown,
        # named apart by their slot, rather than one of them guessed at.
        seen = Counter(info.name for info in infos)
        variables = []
        for info in infos:
            value = self._debugger.describe_local(self._vm, frame, info)
            shadowed = seen[info.name] > 1
            variables.append(variable(
                f"{info.name} (slot {info.slot})" if shadowed else info.name,
                value, self._handles.value(value),
                evaluate_name=None if shadowed else info.name))
        return variables

    def _child_variables(self, value) -> List[Dict[str, Any]]:
        return [variable(name, child, self._handles.value(child))
                for name, child in self._debugger.children_of(self._vm, value)]

    def _on_setBreakpoints(self, request) -> None:
        """Replace this source's breakpoints with the ones requested.

        DAP is declarative and per-file: the request carries the complete set
        for one source. The response is positional -- one entry per requested
        breakpoint, in order, resolved or not -- because that is how the client
        matches them back to the lines it asked about.
        """
        args = request.get("arguments") or {}
        client_path = (args.get("source") or {}).get("path") or ""
        if not client_path:
            self.reply(request, success=False,
                       message="setBreakpoints needs a source path")
            return

        path = self._remember_path(client_path)
        wanted = args.get("breakpoints") or []
        records = [ClientBreakpoint(id=self._new_breakpoint_id(),
                                    client_path=client_path, path=path,
                                    line=int(want.get("line", 0)))
                   for want in wanted]
        self._source_breakpoints[path] = records
        self._rebuild_breakpoints()
        self.reply(request,
                   {"breakpoints": [r.body(self._source) for r in records]})

    def _on_setFunctionBreakpoints(self, request) -> None:
        args = request.get("arguments") or {}
        self._function_breakpoints = [
            ClientBreakpoint(id=self._new_breakpoint_id(),
                             function=str(want.get("name", "")))
            for want in args.get("breakpoints") or []
        ]
        self._rebuild_breakpoints()
        self.reply(request,
                   {"breakpoints": [r.body(self._source)
                                    for r in self._function_breakpoints]})

    def _on_threads(self, request) -> None:
        self.reply(request, dict(THREADS))

    def _on_continue(self, request) -> None:
        self._resume(request, Mode.RUN, {"allThreadsContinued": True})

    def _on_next(self, request) -> None:
        self._resume(request, Mode.STEP_OVER)

    def _on_stepIn(self, request) -> None:
        self._resume(request, Mode.STEP_IN)

    def _on_stepOut(self, request) -> None:
        # FINISH runs until this frame returns, which in `main` means to the
        # end of the program -- the same thing the client's button means.
        self._resume(request, Mode.FINISH)

    def _on_pause(self, request) -> None:
        """Ask for a stop; do not wait for one.

        The stop happens at the next instruction boundary and announces itself
        with a `stopped` event. Holding the response until then would block the
        request loop inside a request, which is the deadlock this whole design
        is arranged to avoid.

        Replying before setting the flag, for the same reason the resume
        requests reply before releasing: the program can stop between the two,
        and a `stopped` event that overtakes the response to the request which
        caused it reads as a stop the client never asked for.
        """
        if self._thread is None or not self._thread.is_alive():
            self.reply(request, success=False, message="no program is running")
            return
        self.reply(request)
        self._debugger.pause()

    def _on_disconnect(self, request) -> None:
        self.reply(request)
        self._end_session()

    def _on_terminate(self, request) -> None:
        self.reply(request)
        self._end_session()

    # -- source files ----------------------------------------------------

    def _source(self, path: str) -> Dict[str, str]:
        """A DAP `Source` for a file, named the way the client names it.

        Editors key open documents by path, so a frame or a breakpoint reported
        at `/private/var/...` when the user opened `/var/...` is a second
        document as far as the client is concerned: it opens a duplicate tab and
        the markers in the first one do not move. The resolver deliberately
        canonicalises -- that is what makes two spellings of one file comparable
        -- so the spelling the client used is remembered alongside and handed
        back here.

        A file the client never named -- anything under `std/`, reached by an
        include -- has no other spelling, and the resolved path is the answer.
        """
        return {"path": self._client_paths.get(path, path),
                "name": Path(path).name}

    def _remember_path(self, client_path: str) -> str:
        resolved = resolved_path(client_path)
        self._client_paths[resolved] = client_path
        return resolved

    # -- breakpoints -----------------------------------------------------

    def _new_breakpoint_id(self) -> int:
        self._next_breakpoint_id += 1
        return self._next_breakpoint_id - 1

    def _breakpoint_records(self) -> Iterator[ClientBreakpoint]:
        yield from self._function_breakpoints
        for records in self._source_breakpoints.values():
            yield from records

    def _rebuild_breakpoints(self) -> None:
        """Re-resolve every breakpoint, and report the ones that moved.

        Rebuilt from empty rather than patched. `Debugger` merges breakpoints
        that land on the same pc, so removing "the ones for this file" one at a
        time can take another file's with it; starting over cannot alias.

        Nothing stops the client changing breakpoints while the program runs,
        which leaves a window during the rebuild where one of them would not
        fire. It is as long as the list is short, and the alternative is
        refusing an edit the client considers always legal.
        """
        if self._debugger is not None:
            self._debugger.clear_breakpoints()
            self._hit_ids = {}
            for record in self._breakpoint_records():
                bp = record.resolve(self._debugger)
                if bp is not None:
                    self._hit_ids.setdefault(bp.id, []).append(record.id)

        for record in self._breakpoint_records():
            body = record.body(self._source)
            # Only news is worth an event, and only for one the client has
            # already been told about: the rest travel in the response.
            if record.reported is not None and record.reported != body:
                self.emit("breakpoint", {"reason": "changed", "breakpoint": body})
            record.reported = body

    # -- resuming --------------------------------------------------------

    def _require_suspended(self, request) -> bool:
        """Inspection reads VM state from this thread, which is safe only while
        the program's thread is parked. A request that arrives while it runs is
        refused rather than raced."""
        with self._condition:
            suspended = self._suspension is not None
        if not suspended:
            self.reply(request, success=False, message="the program is not suspended")
        return suspended

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

    def _resume(self, request, mode: Mode, body=None) -> None:
        refusal = self._refuse_resume()
        if refusal is not None:
            self.reply(request, success=False, message=refusal)
            return
        # Reply before releasing the program. Once it runs it may stop again
        # at once, and a `stopped` event that overtakes the response to the
        # request which caused it reads as a stop the client never asked for.
        self.reply(request, body)
        self._release(mode)

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
            # Every handle names state that is about to be replaced.
            self._handles.clear()
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
        if stop.breakpoint is not None:
            # The adapter's ids, and there can be more than one: two requested
            # lines resolving to the same pc are one breakpoint here and two
            # markers in the client.
            body["hitBreakpointIds"] = list(self._hit_ids.get(stop.breakpoint.id, []))
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
