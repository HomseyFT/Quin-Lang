"""Where a running program's output goes.

The VM used to call `print()` directly. That is right for a terminal and wrong
everywhere else: a debug adapter speaks its protocol on stdout, so one `println`
from the debugged program corrupts the stream, and an editor embedding the VM
has nowhere to put the text at all. Routing output through an object makes the
destination the caller's choice rather than the interpreter's assumption.

This is the program's own I/O and nothing else. Compiler diagnostics, warnings
and the VM's error reports are the *tool* talking, not the program; they go to
stderr from the driver and do not come through here.

Reading arrives with the `read_line()` builtin. Until there is something to
read, this describes writing only -- an interface with a method no
implementation can honour is worse than one that grows when it needs to.
"""

from __future__ import annotations

import sys
from typing import List, Protocol


class ProgramIO(Protocol):
    def write(self, text: str) -> None:
        """Write exactly `text`, with no newline of its own.

        The VM sends the newline as part of the text, so that `print` and
        `println` differ only in what they pass here and an implementation
        never has to know which one it is serving.
        """


class ConsoleIO:
    """Straight to stdout, which is what a program run from a shell wants.

    `sys.stdout` is looked up on each call rather than captured at
    construction, so `contextlib.redirect_stdout` still works -- which is how
    the whole test suite reads program output.
    """

    def write(self, text: str) -> None:
        sys.stdout.write(text)


class CaptureIO:
    """Collects output instead of printing it.

    For tests, and the shape an adapter's implementation takes: what matters is
    not where the text ends up but that it does not end up on the process's
    stdout, where something else is already talking.
    """

    def __init__(self) -> None:
        self.chunks: List[str] = []

    def write(self, text: str) -> None:
        self.chunks.append(text)

    @property
    def text(self) -> str:
        return "".join(self.chunks)
