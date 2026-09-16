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

import os
import sys
from typing import Dict, List, Protocol


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

    # -- files --------------------------------------------------------------
    #
    # Same argument as output: where a program's files come from is the caller's
    # choice, not the interpreter's assumption. A VM embedded in an editor may
    # want a virtual tree, a sandbox may want none at all, and a test wants
    # neither of those to involve a disk.
    #
    # Failure is reported by raising OSError, which is what the underlying calls
    # already do. **Refusing outright is a legitimate implementation**: raise
    # OSError("permission denied") and every file builtin reports it through
    # file_error(), with the program still running.

    def read_file(self, path: str) -> bytes:
        """The file's bytes. Raises OSError if it cannot be read."""

    def write_file(self, path: str, data: bytes, append: bool) -> None:
        """Write (or append) bytes, creating the file if needed. Raises OSError."""

    def file_exists(self, path: str) -> bool:
        """Whether a readable file is there. Never raises: not existing is an
        answer, not a failure."""

    def delete_file(self, path: str) -> None:
        """Remove a file. Raises OSError if it is not there or cannot go."""


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

    # The real filesystem, in bytes. A QuinLang str is one byte per character,
    # so there is no decoding step and none of its failure modes: a file of
    # arbitrary bytes reads back as exactly those bytes.

    def read_file(self, path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()

    def write_file(self, path: str, data: bytes, append: bool) -> None:
        with open(path, "ab" if append else "wb") as handle:
            handle.write(data)

    def file_exists(self, path: str) -> bool:
        return os.path.isfile(path)

    def delete_file(self, path: str) -> None:
        os.remove(path)


class CaptureIO:
    """Collects output instead of printing it.

    For tests, and the shape an adapter's implementation takes: what matters is
    not where the text ends up but that it does not end up on the process's
    stdout, where something else is already talking.
    """

    def __init__(self, stdin: str = "", files: Dict[str, bytes] = None) -> None:
        self.chunks: List[str] = []
        # An in-memory filesystem. Tests exercise the whole file path without
        # touching a disk, needing a temporary directory, or cleaning up after
        # themselves -- and a test that wants a file to already be there just
        # puts it here.
        self.files: Dict[str, bytes] = dict(files or {})
        # Split with the terminators kept, so the queue holds exactly what
        # read_line is supposed to return.
        self._pending: List[str] = stdin.splitlines(keepends=True)

    def write(self, text: str) -> None:
        self.chunks.append(text)

    def read_line(self) -> str:
        return self._pending.pop(0) if self._pending else ""

    def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(f"No such file: {path}")
        return self.files[path]

    def write_file(self, path: str, data: bytes, append: bool) -> None:
        self.files[path] = (self.files.get(path, b"") + data) if append else data

    def file_exists(self, path: str) -> bool:
        return path in self.files

    def delete_file(self, path: str) -> None:
        if path not in self.files:
            raise FileNotFoundError(f"No such file: {path}")
        del self.files[path]

    @property
    def text(self) -> str:
        return "".join(self.chunks)
