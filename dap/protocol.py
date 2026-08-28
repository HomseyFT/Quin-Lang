"""Message framing for the Debug Adapter Protocol.

A DAP message is an HTTP-style header block, a blank line, and a JSON body:

    Content-Length: 119\\r\\n
    \\r\\n
    {"seq":1,"type":"request","command":"initialize", ...}

Two details in that carry all of the bugs.

**Content-Length counts bytes, not characters.** A body containing anything
outside ASCII has a byte length larger than its character length, so measuring
the string instead of the encoded bytes truncates every message after the first
non-ASCII one -- and QuinLang programs print non-ASCII text.

**A message does not arrive in one read.** A pipe delivers whatever it has, so
the header, the body, and the start of the next message can land in any
grouping. Everything here reads through a buffer that survives across calls.

This module knows nothing about debugging. It moves dicts.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, BinaryIO, Dict, Optional

HEADER_TERMINATOR = b"\r\n\r\n"
CONTENT_LENGTH = "content-length"

# A header block is a few dozen bytes. Anything past this is not a header block
# and reading further would be waiting on a client that has lost the framing.
MAX_HEADER_BYTES = 8192


class ProtocolError(Exception):
    """The byte stream is not DAP. Not recoverable: framing errors desynchronise
    the stream, so there is no safe place to resume from."""


class MessageStream:
    """Reads and writes DAP messages over a pair of binary streams.

    Outgoing `seq` numbers are assigned here because they must be unique and
    increasing for the life of the connection, which is exactly this object's
    lifetime.

    Writing is thread-safe. Once a program runs on its own thread, both it and
    the request loop have things to say, and the guarantee that matters is that
    a frame reaches the client whole and each gets its own seq. A lock gives
    both directly. Queueing events for one writer to drain would give it too,
    but the drain only runs between requests -- so a program printing in a loop
    would appear to print nothing until the user next clicked something.
    """

    def __init__(self, reader: BinaryIO, writer: BinaryIO):
        self._reader = reader
        self._writer = writer
        self._buffer = bytearray()
        self._seq = 0
        self._write_lock = threading.Lock()

    # -- reading ---------------------------------------------------------

    def read(self) -> Optional[Dict[str, Any]]:
        """The next message, or None when the stream ends.

        None only at a clean boundary. A stream that ends part-way through a
        message is a ProtocolError, since the alternative is silently acting on
        half a request.
        """
        header = self._read_header()
        if header is None:
            return None
        length = self._content_length(header)
        body = self._read_exactly(length)
        if body is None:
            raise ProtocolError(
                f"stream ended after {len(self._buffer)} of {length} body bytes"
            )
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ProtocolError(f"message body is not JSON: {e}") from None

    def _read_header(self) -> Optional[bytes]:
        """Everything up to the blank line, or None at a clean end of stream.

        Read one byte at a time. The length is not known in advance, so a
        larger read could block waiting for bytes the client will not send
        until it has an answer -- the classic adapter hang.
        """
        while HEADER_TERMINATOR not in self._buffer:
            if len(self._buffer) > MAX_HEADER_BYTES:
                raise ProtocolError(
                    f"no header terminator in {MAX_HEADER_BYTES} bytes; "
                    f"the stream is not DAP"
                )
            chunk = self._reader.read(1)
            if not chunk:
                if self._buffer:
                    raise ProtocolError("stream ended part-way through a header")
                return None
            self._buffer.extend(chunk)
        index = self._buffer.index(HEADER_TERMINATOR)
        header = bytes(self._buffer[:index])
        del self._buffer[: index + len(HEADER_TERMINATOR)]
        return header

    @staticmethod
    def _content_length(header: bytes) -> int:
        """The declared body length. Every other header is ignored, which the
        protocol requires -- clients are free to send more."""
        for line in header.split(b"\r\n"):
            name, sep, value = line.partition(b":")
            if sep and name.strip().lower() == CONTENT_LENGTH.encode("ascii"):
                try:
                    length = int(value.strip())
                except ValueError:
                    raise ProtocolError(
                        f"Content-Length is not a number: {value!r}"
                    ) from None
                if length < 0:
                    raise ProtocolError(f"negative Content-Length: {length}")
                return length
        raise ProtocolError("message has no Content-Length header")

    def _read_exactly(self, count: int) -> Optional[bytes]:
        while len(self._buffer) < count:
            chunk = self._reader.read(count - len(self._buffer))
            if not chunk:
                return None
            self._buffer.extend(chunk)
        body = bytes(self._buffer[:count])
        del self._buffer[:count]
        return body

    # -- writing ---------------------------------------------------------

    def write(self, message: Dict[str, Any]) -> int:
        """Frame and send one message, returning the `seq` it was given."""
        with self._write_lock:
            return self._write_locked(message)

    def _write_locked(self, message: Dict[str, Any]) -> int:
        self._seq += 1
        message = dict(message, seq=self._seq)
        # ensure_ascii=False so the body carries real UTF-8 rather than \uXXXX
        # escapes. Escaping would make every body pure ASCII and the byte count
        # accidentally equal to the character count -- correct today, and
        # quietly wrong the first time anything stops escaping.
        body = json.dumps(message, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
        # len(body), not len(the string): the count is bytes, and a program's
        # output travels through here.
        self._writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        self._writer.write(body)
        self._writer.flush()
        return self._seq


# -- message constructors ------------------------------------------------
#
# `seq` is left to MessageStream.write, so nothing else has to track it.


def response(request: Dict[str, Any], body: Any = None, *,
             success: bool = True, message: str = None) -> Dict[str, Any]:
    """A response to `request`. `message` is the short error text a client
    shows when `success` is false."""
    out = {
        "type": "response",
        "request_seq": request.get("seq", 0),
        "success": success,
        "command": request.get("command", ""),
    }
    if body is not None:
        out["body"] = body
    if message is not None:
        out["message"] = message
    return out


def event(name: str, body: Any = None) -> Dict[str, Any]:
    out = {"type": "event", "event": name}
    if body is not None:
        out["body"] = body
    return out


def stdio_stream() -> MessageStream:
    """The adapter's own stdin and stdout, as binary.

    Binary matters on Windows, where a text-mode stream rewrites \\n to \\r\\n
    and corrupts both the header terminators and the byte count that describes
    the body.
    """
    return MessageStream(sys.stdin.buffer, sys.stdout.buffer)
