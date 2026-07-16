from __future__ import annotations

import sys

from agent_side.app import run
from agent_side.cli import main as cli_main


if __name__ == "__main__":
    if "--cli" in sys.argv:
        cli_main()
    else:
        run()
