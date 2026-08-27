"""DAP message framing.

Two bugs live in this layer and both are silent. Content-Length is a count of
*bytes*, so measuring the string truncates every message after the first
non-ASCII one -- and program output travels through here. And a message does
not arrive in one read, so anything that assumes it does works perfectly until
the day a body straddles a packet boundary.

Both are tested directly rather than through a session, because a framing bug
found from inside a debugger session is nearly unreadable.
"""

import io
import json
import unittest

from dap.protocol import MessageStream, ProtocolError, event, response


def framed(*bodies: str) -> bytes:
    """The bytes a client would send for these JSON bodies."""
    out = b""
    for body in bodies:
        encoded = body.encode("utf-8")
        out += f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded
    return out


class Trickle(io.RawIOBase):
    """A reader that returns at most `chunk` bytes per call.

    A pipe behaves this way and BytesIO does not, so without it every test
    would read whole messages in one go and the split-body case would never be
    exercised.
    """

    def __init__(self, data: bytes, chunk: int = 1):
        self._data = data
        self._chunk = chunk
        self._pos = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._data) - self._pos
        take = min(size, self._chunk, len(self._data) - self._pos)
        out = self._data[self._pos:self._pos + take]
        self._pos += take
        return out


def read_all(data: bytes, chunk: int = 0):
    """Every message in `data`. `chunk` limits how much each read returns."""
    reader = Trickle(data, chunk) if chunk else io.BytesIO(data)
    stream = MessageStream(reader, io.BytesIO())
    messages = []
    while True:
        message = stream.read()
        if message is None:
            return messages
        messages.append(message)


class TestReading(unittest.TestCase):
    def test_one_message(self):
        self.assertEqual(read_all(framed('{"seq":1,"command":"initialize"}')),
                         [{"seq": 1, "command": "initialize"}])

    def test_several_messages_back_to_back(self):
        got = read_all(framed('{"a":1}', '{"b":2}', '{"c":3}'))
        self.assertEqual(got, [{"a": 1}, {"b": 2}, {"c": 3}])

    def test_an_empty_stream_ends_cleanly(self):
        self.assertEqual(read_all(b""), [])

    def test_a_body_split_across_reads(self):
        # One byte at a time: header, body and the next message's header all
        # straddle read boundaries.
        got = read_all(framed('{"a":1}', '{"b":2}'), chunk=1)
        self.assertEqual(got, [{"a": 1}, {"b": 2}])

    def test_a_body_split_at_an_awkward_size(self):
        got = read_all(framed('{"command":"setBreakpoints","lines":[1,2,3]}'), chunk=7)
        self.assertEqual(got, [{"command": "setBreakpoints", "lines": [1, 2, 3]}])

    def test_content_length_counts_bytes_not_characters(self):
        # The classic bug. This body is 20 characters and 24 bytes; a length
        # taken from the string would cut it short and desynchronise
        # everything after it.
        body = '{"output":"héllo"}'
        self.assertLess(len(body), len(body.encode("utf-8")))
        got = read_all(framed(body))
        self.assertEqual(got, [{"output": "héllo"}])

    def test_a_multibyte_body_split_mid_character(self):
        # The two bytes of an e-acute land in different reads.
        got = read_all(framed('{"output":"café"}'), chunk=1)
        self.assertEqual(got, [{"output": "café"}])

    def test_unknown_headers_are_ignored(self):
        body = b'{"a":1}'
        data = (b"Content-Type: application/vnd.dap\r\n"
                b"X-Whatever: 3\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        self.assertEqual(read_all(data), [{"a": 1}])

    def test_the_header_name_is_case_insensitive(self):
        body = b'{"a":1}'
        data = b"content-length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        self.assertEqual(read_all(data), [{"a": 1}])

    def test_an_empty_body_is_allowed_by_the_framing(self):
        # Zero-length is well-framed even though it is not valid DAP; it must
        # fail as bad JSON, not as a framing error, so the message is useful.
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: 0\r\n\r\n")
        self.assertIn("not JSON", str(caught.exception))


class TestMalformed(unittest.TestCase):
    """Framing errors are not recoverable: the stream is desynchronised, so
    there is nowhere safe to resume from. Each of these must say why."""

    def test_a_missing_content_length(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"X-Nothing: 1\r\n\r\n{}")
        self.assertIn("no Content-Length", str(caught.exception))

    def test_a_non_numeric_content_length(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: banana\r\n\r\n{}")
        self.assertIn("not a number", str(caught.exception))

    def test_a_negative_content_length(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: -5\r\n\r\n{}")
        self.assertIn("negative", str(caught.exception))

    def test_a_truncated_body(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: 50\r\n\r\n{\"a\":1}")
        self.assertIn("stream ended", str(caught.exception))

    def test_a_truncated_header(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: 7\r\n")
        self.assertIn("part-way through a header", str(caught.exception))

    def test_a_body_that_is_not_json(self):
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"Content-Length: 3\r\n\r\nnot")
        self.assertIn("not JSON", str(caught.exception))

    def test_a_stream_with_no_terminator_gives_up(self):
        # Otherwise a client that never sends \r\n\r\n hangs the adapter.
        with self.assertRaises(ProtocolError) as caught:
            read_all(b"A" * 9000)
        self.assertIn("not DAP", str(caught.exception))


class TestWriting(unittest.TestCase):
    def stream(self):
        out = io.BytesIO()
        return MessageStream(io.BytesIO(), out), out

    def test_a_message_round_trips(self):
        stream, out = self.stream()
        stream.write(event("stopped", {"reason": "breakpoint"}))
        self.assertEqual(read_all(out.getvalue()),
                         [{"seq": 1, "type": "event", "event": "stopped",
                           "body": {"reason": "breakpoint"}}])

    def test_the_declared_length_is_the_byte_length(self):
        stream, out = self.stream()
        stream.write(event("output", {"output": "héllo\n"}))
        raw = out.getvalue()
        header, _, body = raw.partition(b"\r\n\r\n")
        declared = int(header.split(b":")[1])
        self.assertEqual(declared, len(body))
        self.assertNotEqual(declared, len(body.decode("utf-8")),
                            "this case only proves anything if they differ")

    def test_seq_increases_per_message(self):
        stream, out = self.stream()
        stream.write(event("a"))
        stream.write(event("b"))
        stream.write(event("c"))
        self.assertEqual([m["seq"] for m in read_all(out.getvalue())], [1, 2, 3])

    def test_write_returns_the_seq_it_assigned(self):
        stream, _ = self.stream()
        self.assertEqual([stream.write(event("x")), stream.write(event("y"))], [1, 2])


class TestConstructors(unittest.TestCase):
    REQUEST = {"seq": 7, "type": "request", "command": "stackTrace"}

    def test_a_response_echoes_the_request(self):
        self.assertEqual(
            response(self.REQUEST, {"stackFrames": []}),
            {"type": "response", "request_seq": 7, "success": True,
             "command": "stackTrace", "body": {"stackFrames": []}})

    def test_a_failed_response_carries_a_message(self):
        out = response(self.REQUEST, success=False, message="not suspended")
        self.assertFalse(out["success"])
        self.assertEqual(out["message"], "not suspended")
        self.assertNotIn("body", out, "no body rather than a null one")

    def test_a_response_without_a_body_omits_it(self):
        self.assertNotIn("body", response(self.REQUEST))

    def test_an_event_without_a_body_omits_it(self):
        self.assertEqual(event("initialized"),
                         {"type": "event", "event": "initialized"})

    def test_constructors_leave_seq_to_the_stream(self):
        # One place assigns seq, so it cannot be assigned twice or skipped.
        self.assertNotIn("seq", response(self.REQUEST))
        self.assertNotIn("seq", event("initialized"))


if __name__ == "__main__":
    unittest.main()
