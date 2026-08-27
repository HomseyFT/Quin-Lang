"""Entry point for the QuinLang debug adapter.

    python3 -m dap                 # stdio: the client spawns this and speaks
                                   # DAP over its stdin and stdout
    python3 -m dap --server 4711   # TCP on localhost, for an editor that
                                   # connects to a running adapter, and for
                                   # debugging the adapter itself -- stdio is
                                   # occupied by the protocol
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

from compiler.pipeline import STD_PATH
from dap.protocol import MessageStream, stdio_stream
from dap.session import DebugSession

# Loopback only, never 0.0.0.0. A debug adapter compiles and runs whatever it
# is told to; exposing that to a network is remote code execution by design.
HOST = "127.0.0.1"


def serve_stdio(std_path: Path) -> None:
    DebugSession(stdio_stream(), std_path).serve()


def serve_tcp(port: int, std_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, port))
        listener.listen(1)
        # The port is printed so a caller that asked for 0 learns which one it
        # got, and so a human can see the adapter is ready.
        print(f"QuinLang debug adapter listening on {HOST}:{listener.getsockname()[1]}",
              file=sys.stderr, flush=True)
        connection, _ = listener.accept()
        with connection, connection.makefile("rb") as reader, \
                connection.makefile("wb") as writer:
            DebugSession(MessageStream(reader, writer), std_path).serve()


def main() -> None:
    ap = argparse.ArgumentParser(description="QuinLang debug adapter (DAP)")
    ap.add_argument("--server", type=int, metavar="PORT",
                    help=f"listen on {HOST}:PORT instead of using stdio")
    ap.add_argument("--std", type=Path, default=STD_PATH,
                    help="the standard library directory")
    args = ap.parse_args()

    if args.server is not None:
        serve_tcp(args.server, args.std)
    else:
        serve_stdio(args.std)


if __name__ == "__main__":
    main()
