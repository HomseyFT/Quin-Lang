"""The adapter as a client spawns it, and the editor configuration that does so.

Every other DAP test builds a `DebugSession` in-process. This one runs the real
command line -- `python3 -m dap` in a subprocess, and the TCP mode beside it --
because that is the part an editor exercises and the part no in-process test
can be wrong about quietly.

The editor configurations in docs/ are checked here too. They are the seam
where a rename in the adapter stops matching what clients are told to send, and
nothing else would notice.
"""

import io
import json
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import dap.__main__
from dap.protocol import MessageStream
from dap.session import CAPABILITIES
from tests.harness import REPO_ROOT

DOCS = REPO_ROOT / "docs"
TIMEOUT_SECONDS = 30

HELLO = 'fn main(): int { println("hello"); return 0; }'


def requests(*pairs):
    """DAP request frames, sequenced, as bytes."""
    raw = b""
    for seq, (command, arguments) in enumerate(pairs, 1):
        body = json.dumps({"seq": seq, "type": "request", "command": command,
                           "arguments": arguments}).encode("utf-8")
        raw += f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    return raw


def read_all(reader):
    stream = MessageStream(reader, io.BytesIO())
    messages = []
    while True:
        message = stream.read()
        if message is None:
            return messages
        messages.append(message)


def stdout_of(messages):
    return "".join(m["body"]["output"] for m in messages
                   if m.get("event") == "output"
                   and m["body"]["category"] == "stdout")


class EntryPointTestCase(unittest.TestCase):
    def program(self, source=HELLO) -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "main.ql"
        path.write_text(source, encoding="utf-8")
        return str(path)

    def session(self, path):
        return requests(
            ("initialize", {"adapterID": "quinlang"}),
            ("launch", {"program": path}),
            ("configurationDone", {}),
            ("disconnect", {}),
        )


class TestStdio(EntryPointTestCase):
    def run_adapter(self, path, *args):
        result = subprocess.run(
            [sys.executable, "-m", "dap", *args],
            input=self.session(path), cwd=REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return read_all(io.BytesIO(result.stdout))

    def test_a_program_runs_end_to_end(self):
        messages = self.run_adapter(self.program())
        self.assertIn("hello", stdout_of(messages))
        exited = [m for m in messages if m.get("event") == "exited"]
        self.assertEqual(exited[0]["body"]["exitCode"], 0)

    def test_stdout_carries_nothing_but_the_protocol(self):
        # A stray print anywhere in the adapter corrupts the stream, and the
        # framing parser is what would notice.
        messages = self.run_adapter(self.program(
            'fn main(): int { println("not protocol"); return 0; }'))
        self.assertTrue(all(m["type"] in ("response", "event") for m in messages))
        self.assertIn("not protocol", stdout_of(messages))

    def test_the_standard_library_path_can_be_overridden(self):
        messages = self.run_adapter(self.program(), "--std", str(REPO_ROOT / "std"))
        self.assertIn("hello", stdout_of(messages))


class TestTcp(EntryPointTestCase):
    def test_a_client_can_connect_to_a_listening_adapter(self):
        # Port 0 so the test never collides with something already bound; the
        # adapter reports which one it got.
        adapter = subprocess.Popen(
            [sys.executable, "-m", "dap", "--server", "0"], cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(adapter.stderr.close)
        self.addCleanup(adapter.wait, TIMEOUT_SECONDS)
        self.addCleanup(adapter.terminate)

        announcement = adapter.stderr.readline().decode()
        port = re.search(r":(\d+)$", announcement.strip())
        self.assertIsNotNone(port, announcement)

        with socket.create_connection(("127.0.0.1", int(port.group(1))),
                                      timeout=TIMEOUT_SECONDS) as connection:
            connection.sendall(self.session(self.program()))
            with connection.makefile("rb") as reader:
                messages = read_all(reader)
        self.assertIn("hello", stdout_of(messages))

    def test_it_listens_on_loopback_only(self):
        # An adapter compiles and runs whatever it is told to. Reachable from
        # the network, that is remote code execution by design.
        self.assertEqual(dap.__main__.HOST, "127.0.0.1")


class TestEditorConfiguration(unittest.TestCase):
    """docs/ tells clients what to send. This is where that stops being true."""

    def setUp(self):
        self.manifest = json.loads((DOCS / "vscode" / "package.json").read_text())
        self.debugger = self.manifest["contributes"]["debuggers"][0]

    def test_the_extension_spawns_a_shim_that_exists(self):
        self.assertEqual(self.debugger["runtime"], "python3")
        self.assertTrue((DOCS / "vscode" / self.debugger["program"]).exists())

    def test_the_shim_finds_the_checkout_without_configuration(self):
        # It lives inside the repository so that it can; a moved docs/ breaks
        # this and should fail here rather than in someone's editor.
        shim = DOCS / "vscode" / "adapter.py"
        root = shim.resolve().parents[2]
        self.assertTrue((root / "dap" / "__main__.py").exists())

    def test_the_declared_attributes_are_the_ones_launch_reads(self):
        # Declaring an attribute the adapter ignores is worse than omitting it:
        # the client offers it and nothing happens.
        declared = set(self.debugger["configurationAttributes"]["launch"]
                       ["properties"])
        self.assertEqual(declared, {"program", "stopOnEntry", "args"})
        self.assertEqual(self.debugger["configurationAttributes"]["launch"]
                         ["required"], ["program"])

    def test_the_sample_configurations_use_the_adapter_type(self):
        for configuration in self.debugger["initialConfigurations"]:
            self.assertEqual(configuration["type"], self.debugger["type"])
            self.assertEqual(configuration["request"], "launch")

    def test_breakpoints_are_contributed_for_the_language(self):
        # Without this VS Code will not let anyone set one in a .ql file, and
        # every breakpoint capability behind it is unreachable.
        languages = {entry["language"]
                     for entry in self.manifest["contributes"]["breakpoints"]}
        self.assertIn(self.debugger["languages"][0], languages)

    def test_the_neovim_snippet_names_the_same_adapter(self):
        lua = (DOCS / "nvim-dap.lua").read_text()
        self.assertIn('args = { "-m", "dap" }', lua)
        self.assertIn(f'dap.adapters.{self.debugger["type"]}', lua)
        self.assertIn(f'dap.configurations.{self.debugger["type"]}', lua)

    def test_the_guide_only_promises_what_is_switched_on(self):
        guide = (DOCS / "editors.md").read_text()
        promised = {"supportsFunctionBreakpoints": "by line and by function",
                    "supportsEvaluateForHovers": "hover, watch"}
        for capability, claim in promised.items():
            self.assertTrue(CAPABILITIES[capability], capability)
            self.assertIn(claim, guide)

    def test_the_guide_says_input_does_not_work(self):
        # The one thing DAP cannot express here. Left unsaid, it reads as a bug.
        guide = (DOCS / "editors.md").read_text()
        self.assertIn("`read_line()` reports end of input", guide)


if __name__ == "__main__":
    unittest.main()
