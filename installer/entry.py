"""Entry point for the PyInstaller-bundled finch-epm executable.

Handles two launch modes:
    1. CLI mode: `finch-epm.exe <command> [args]`
    2. Double-click mode: user double-clicks a .fdash file, which launches
       `finch-epm.exe open path/to/file.fdash` via file association.
"""

import sys
from pathlib import Path


def main() -> None:
    # If the first argument is a .fdash file (double-click), run open command
    if len(sys.argv) > 1 and sys.argv[1].endswith(".fdash"):
        fdash_path = sys.argv[1]
        if Path(fdash_path).exists():
            sys.argv = [sys.argv[0], "open", fdash_path]

    from finch_epm.cli.main import cli
    cli()


if __name__ == "__main__":
    main()
