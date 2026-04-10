"""Build script for the finch-epm desktop installer.

Usage:
    python installer/build.py

Prerequisites:
    pip install pyinstaller

Produces:
    dist/finch-epm/         -- directory distribution
    dist/finch-epm/finch-epm.exe  -- the executable

To test the build:
    dist/finch-epm/finch-epm.exe --help
    dist/finch-epm/finch-epm.exe --version
    dist/finch-epm/finch-epm.exe open examples/site_pl.fdash
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build() -> None:
    root = Path(__file__).parent.parent
    spec_file = root / "installer" / "finch-epm.spec"

    if not spec_file.exists():
        print(f"Spec file not found: {spec_file}")
        sys.exit(1)

    # Check PyInstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Install with: pip install pyinstaller")
        sys.exit(1)

    print("Building finch-epm desktop application...")
    print(f"Spec file: {spec_file}")
    print(f"Output: {root / 'dist' / 'finch-epm'}")
    print()

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec_file), "--noconfirm"],
        cwd=str(root),
    )

    if result.returncode != 0:
        print("\nBuild failed.")
        sys.exit(1)

    dist_dir = root / "dist" / "finch-epm"
    exe_path = dist_dir / "finch-epm.exe"

    if exe_path.exists():
        print(f"\nBuild successful.")
        print(f"Executable: {exe_path}")
        print(f"Directory size: {sum(f.stat().st_size for f in dist_dir.rglob('*') if f.is_file()) / 1024 / 1024:.1f} MB")
        print()
        print("To register .fdash file association:")
        print(f'  python installer/register_fdash.py --exe "{exe_path}"')
        print()
        print("To test:")
        print(f'  "{exe_path}" --help')
        print(f'  "{exe_path}" open examples/site_pl.fdash')
    else:
        print(f"\nBuild completed but executable not found at: {exe_path}")
        print("Check the dist/ directory for output.")


if __name__ == "__main__":
    build()
