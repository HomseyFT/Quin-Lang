#!/usr/bin/env python3
"""What VS Code spawns. Finds the QuinLang checkout, then runs the adapter.

The extension lives inside the repository it debugs, so the checkout is three
directories up and needs no configuration. Copying this folder somewhere else
breaks that, which is what QUINLANG_HOME is for.

Nothing here may write to stdout: it is carrying the protocol.
"""

import os
import sys
from pathlib import Path

home = os.environ.get("QUINLANG_HOME")
root = Path(home).expanduser().resolve() if home else Path(__file__).resolve().parents[2]

if not (root / "dap" / "__main__.py").exists():
    sys.exit(f"No QuinLang checkout at {root}. Set QUINLANG_HOME to yours.")

sys.path.insert(0, str(root))

from dap.__main__ import main       # noqa: E402  -- after sys.path is set up

main()
