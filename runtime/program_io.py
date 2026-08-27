"""Where a running program's output goes.

The VM used to call `print()` directly. That is right for a terminal and wrong
everywhere else: a debug adapter speaks its protocol on stdout, so one `println`
from the debugged program corrupts the stream, and an editor embedding the VM
has nowhere to put the text at all. Routing output through an object makes the
destination the caller's choice rather than the interpreter's assumption.

This is the program's own I/O and nothing else. Compiler diagnostics, warnings
and the VM's error reports are the *tool* talking, not the program; they go to
stderr from the driver and do not come through here.

Reading follows the same rule, and uses the convention `fgets` and Python's own
`readline` already use: a line comes back **with its terminator**, and the empty
string means end of input. That is what makes end of input unambiguous without
a second call to ask about it -- a blank line is `"\n"`, never `""`.
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

    def read_line(self) -> str:
        """The next line **including its terminator**, or `""` at end of input.

        Keeping the terminator is what makes the two cases distinguishable: a
        blank line is `"\n"` and only end of input is empty. An implementation
        that strips newlines makes the last line of input look like the end of
        it.

        Every character must fit in a byte, since that is what a QuinLang `str`
        holds. The VM checks rather than trusting this, because the check has
        to cover every implementation and not just the one below.
        """


class ConsoleIO:
    """Straight to stdout, which is what a program run from a shell wants.

    `sys.stdout` is looked up on each call rather than captured at
    construction, so `contextlib.redirect_stdout` still works -- which is how
    the whole test suite reads program output.
    """

    def write(self, text: str) -> None:
        sys.stdout.write(text)

    def read_line(self) -> str:
        """Read bytes, not text.

        QuinLang is byte-oriented -- one byte per character, which is why
        `str_char_at` returns 0..255 -- so input is taken from the binary
        buffer and mapped straight through. Reading `sys.stdin` as text would
        decode UTF-8 first and hand back characters that do not fit in a byte.

        The fallback covers a stdin with no binary buffer, which happens when
        something embeds the interpreter and substitutes a text stream.
        """
        buffer = getattr(sys.stdin, "buffer", None)
        if buffer is not None:
            return buffer.readline().decode("latin-1")
        return sys.stdin.readline()


class CaptureIO:
    """Collects output instead of printing it.

    For tests, and the shape an adapter's implementation takes: what matters is
    not where the text ends up but that it does not end up on the process's
    stdout, where something else is already talking.
    """

    def __init__(self, stdin: str = "") -> None:
        self.chunks: List[str] = []
        # Split with the terminators kept, so the queue holds exactly what
        # read_line is supposed to return.
        self._pending: List[str] = stdin.splitlines(keepends=True)

    def write(self, text: str) -> None:
        self.chunks.append(text)

    def read_line(self) -> str:
        return self._pending.pop(0) if self._pending else ""

    @property
    def text(self) -> str:
        return "".join(self.chunks)
