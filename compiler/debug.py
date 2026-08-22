"""The interactive front end for the debugger.

All of the session's I/O lives here and none of it in runtime/debugger.py, so
the state machine can be tested without a terminal and this can be tested by
feeding it a list of commands. It sits beside driver_vm.py because it plays the
same part: the compiler pipeline is already done by the time either runs, and
both exist to put a program in front of a user.

The command set is deliberately the one every debugger already has -- break,
step, next, finish, continue, print, backtrace -- because the value of a
familiar name is that it needs no documentation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, List, Optional

from runtime.debugger import (
    Debugger,
    DebuggerError,
    Mode,
    Quit,
    Stop,
    StopReason,
)
from runtime.vm import QuinVM, VMError

HELP = """\
  break <fn>            stop on entry to a function
  break <line>          stop at a line of the compiled file
  break <file>:<line>   stop at a line of an included file
  delete <id>           remove a breakpoint      (no id: remove all)
  enable/disable <id>   turn one on or off
  breakpoints           list them, with hit counts

  continue   c          run until the next breakpoint
  step       s          one line, entering calls
  next       n          one line, stepping over calls
  finish     f          run until this function returns

  backtrace  bt         the call stack
  frame <n>             select a frame for print and locals
  print <name>  p       show a variable
  locals                show every variable in the selected frame
  list [n]              show source around the current line
  help       h          this text
  quit       q          abandon the run\
"""

# What `list` shows either side of the current line.
LIST_CONTEXT = 4


class DebugSession:
    """One interactive run of one program."""

    def __init__(self, program, vm: QuinVM, read: Callable[[str], str] = input,
                 out=None):
        self.program = program
        self.vm = vm
        self.read = read
        self.out = out or sys.stdout
        self.debugger = Debugger(program, self._on_stop)
        self._frame_index = 0
        self._last_command = ""
        self._sources: dict = {}
        self._list_from: Optional[int] = None
        self._fault: Optional[VMError] = None

    # -- session ---------------------------------------------------------

    def run(self) -> Optional[int]:
        """Run the program to completion, returning main's exit value.

        None means the user quit, and the program never finished -- there is no
        value to report and nothing ran to completion.
        """
        self._say("QuinLang debugger. 'help' for commands.")
        try:
            return self.debugger.run(self.vm)
        except Quit:
            if self._fault is not None:
                # Leaving the session does not unmake the fault. Quit is how a
                # post-mortem ends, so the error still has to reach the driver
                # and still has to decide the exit status.
                raise self._fault
            self._say("Abandoned.")
            return None

    def _on_stop(self, dbg: Debugger, vm: QuinVM, stop: Stop) -> None:
        self._frame_index = 0
        self._list_from = None
        self._announce(stop)
        if stop.reason is StopReason.FAULT:
            # The frames are still intact here, so the run stops for good but
            # the user gets to look around before the error propagates.
            self._fault = stop.error
            self._say("The program cannot continue; inspect and then 'quit'.")
        self._prompt(stop)

    def _announce(self, stop: Stop) -> None:
        frame = stop.frame
        if stop.reason is StopReason.BREAKPOINT and stop.breakpoint:
            self._say(f"Breakpoint {stop.breakpoint.id}, {self._where(frame)}")
        elif stop.reason is StopReason.ENTRY:
            self._say(f"Stopped at {self._where(frame)}")
        elif stop.reason is StopReason.FAULT:
            self._say(f"Runtime error: {stop.error}")
            return
        else:
            self._say(self._where(frame))
        self._show_line(frame.line, frame.file)

    def _prompt(self, stop: Stop) -> None:
        """Read commands until one of them resumes execution."""
        while True:
            try:
                text = self.read("(qdb) ").strip()
            except (EOFError, KeyboardInterrupt):
                self._say("")
                raise Quit
            if not text:
                # An empty line repeats, so stepping is one keystroke.
                text = self._last_command
                if not text:
                    continue
            self._last_command = text
            try:
                if self._dispatch(text, stop):
                    return
            except DebuggerError as e:
                self._say(str(e))

    # -- commands --------------------------------------------------------

    def _dispatch(self, text: str, stop: Stop) -> bool:
        """Run one command. True means execution should resume."""
        word, _, rest = text.partition(" ")
        rest = rest.strip()
        dbg, vm = self.debugger, self.vm

        if word in ("continue", "c"):
            return self._resume(Mode.RUN, stop)
        if word in ("step", "s"):
            return self._resume(Mode.STEP_IN, stop)
        if word in ("next", "n"):
            return self._resume(Mode.STEP_OVER, stop)
        if word in ("finish", "f"):
            return self._resume(Mode.FINISH, stop)
        if word in ("quit", "q"):
            raise Quit

        if word in ("break", "b"):
            self._break(rest)
        elif word == "delete":
            self._delete(rest)
        elif word in ("enable", "disable"):
            bp = dbg.set_enabled(self._as_id(rest), word == "enable")
            self._say(f"Breakpoint {bp.id} {word}d")
        elif word in ("breakpoints", "info"):
            self._list_breakpoints()
        elif word in ("backtrace", "bt", "where"):
            self._backtrace()
        elif word == "frame":
            self._select_frame(rest)
        elif word in ("print", "p"):
            self._print(rest)
        elif word == "locals":
            self._locals()
        elif word in ("list", "l"):
            self._list_source(rest)
        elif word in ("help", "h", "?"):
            self._say(HELP)
        else:
            self._say(f"Unknown command '{word}'. 'help' for the list.")
        return False

    def _resume(self, mode: Mode, stop: Stop) -> bool:
        if stop.reason is StopReason.FAULT:
            # There is nothing to resume: the VM is mid-fault, and letting the
            # loop continue would run on from an instruction that failed.
            self._say("The program has already faulted; 'quit' to leave.")
            return False
        # Only finish is relative to the frame the user selected; stepping
        # always advances the innermost one, as it does everywhere else.
        depth = self._frame_index if mode is Mode.FINISH else 0
        self.debugger.resume(mode, self.vm, depth)
        return True

    def _break(self, rest: str) -> None:
        if not rest:
            raise DebuggerError("break needs a function, a line, or file:line")
        file, _, tail = rest.rpartition(":")
        target = tail if file else rest
        if target.lstrip("-").isdigit():
            bp = self.debugger.break_at_line(int(target), file)
        else:
            bp = self.debugger.break_at_function(rest)
        where = f"{Path(bp.file).name}:{bp.line}" if bp.file else f"line {bp.line}"
        self._say(f"Breakpoint {bp.id} at {bp.function} ({where})")

    def _delete(self, rest: str) -> None:
        if not rest:
            for bp_id in list(self.debugger.breakpoints):
                self.debugger.remove(bp_id)
            self._say("All breakpoints removed")
            return
        self.debugger.remove(self._as_id(rest))
        self._say(f"Breakpoint {rest} removed")

    @staticmethod
    def _as_id(rest: str) -> int:
        if not rest.isdigit():
            raise DebuggerError(f"expected a breakpoint number, got '{rest}'")
        return int(rest)

    def _list_breakpoints(self) -> None:
        if not self.debugger.breakpoints:
            self._say("No breakpoints.")
            return
        for bp in self.debugger.breakpoints.values():
            state = "" if bp.enabled else " (disabled)"
            hits = f", {bp.hits} hit" + ("s" if bp.hits != 1 else "") if bp.hits else ""
            name = Path(bp.file).name if bp.file else ""
            self._say(f"  {bp.id}: {bp.function} at {name}:{bp.line}{state}{hits}")

    def _backtrace(self) -> None:
        frames = self.debugger.frames(self.vm)
        width = max(len(f.function) for f in frames)
        for f in frames:
            marker = "->" if f.depth == self._frame_index else "  "
            line = f.line if f.line is not None else "?"
            self._say(f"{marker} #{f.depth} {f.function:<{width}} at {Path(f.file).name}:{line}")

    def _select_frame(self, rest: str) -> None:
        frames = self.debugger.frames(self.vm)
        if not rest.isdigit() or int(rest) >= len(frames):
            raise DebuggerError(f"no frame {rest}; the stack is {len(frames)} deep")
        self._frame_index = int(rest)
        self._list_from = None
        frame = frames[self._frame_index]
        self._say(self._where(frame))
        self._show_line(frame.line, frame.file)

    def _frame(self):
        frames = self.debugger.frames(self.vm)
        return frames[min(self._frame_index, len(frames) - 1)]

    def _print(self, rest: str) -> None:
        if not rest:
            raise DebuggerError("print needs a variable name")
        frame = self._frame()
        matches = self.debugger.lookup_name(frame, rest)
        if not matches:
            raise DebuggerError(f"no variable '{rest}' in {frame.function}")
        for info in matches:
            value = self.debugger.format_local(self.vm, frame, info)
            note = f"   (slot {info.slot}, one of {len(matches)} named '{rest}')" \
                if len(matches) > 1 else ""
            self._say(f"{info.name}: {info.type_name} = {value}{note}")
        if len(matches) > 1:
            # Which declaration is live needs the scope ranges the slot table
            # does not carry, so every candidate is shown rather than a guess.
            self._say(f"'{rest}' is shadowed; all declarations are shown.")

    def _locals(self) -> None:
        frame = self._frame()
        infos = self.debugger.locals_of(frame)
        if not infos:
            self._say(f"{frame.function} has no locals.")
            return
        width = max(len(i.name) for i in infos)
        for info in infos:
            kind = "param" if info.is_param else "local"
            value = self.debugger.format_local(self.vm, frame, info)
            self._say(f"  {info.name:<{width}}  {kind}  {info.type_name} = {value}")

    def _list_source(self, rest: str) -> None:
        frame = self._frame()
        if rest.isdigit():
            centre = int(rest)
        elif self._list_from is not None:
            centre = self._list_from
        else:
            centre = frame.line or 1
        lines = self._source(frame.file)
        if not lines:
            raise DebuggerError(f"cannot read {frame.file or 'the source file'}")
        first = max(1, centre - LIST_CONTEXT)
        last = min(len(lines), centre + LIST_CONTEXT)
        for n in range(first, last + 1):
            marker = "->" if n == frame.line else "  "
            self._say(f"{marker} {n:>4}  {lines[n - 1]}")
        # A bare `list` again continues past what was just shown.
        self._list_from = last + 1 + LIST_CONTEXT

    # -- output ----------------------------------------------------------

    def _source(self, path: str) -> List[str]:
        if path not in self._sources:
            try:
                self._sources[path] = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError:
                self._sources[path] = []
        return self._sources[path]

    def _where(self, frame) -> str:
        line = frame.line if frame.line is not None else "?"
        name = Path(frame.file).name if frame.file else ""
        return f"{frame.function} at {name}:{line}" if name else f"{frame.function} at line {line}"

    def _show_line(self, line: Optional[int], path: str) -> None:
        if line is None:
            return
        lines = self._source(path)
        if 1 <= line <= len(lines):
            self._say(f"{line:>5}  {lines[line - 1].strip()}")

    def _say(self, text: str) -> None:
        print(text, file=self.out)


def debug(program, vm: QuinVM) -> Optional[int]:
    """Run `program` under the interactive debugger."""
    return DebugSession(program, vm).run()
