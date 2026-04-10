"""Register .fdash file association on Windows.

Associates .fdash files with the finch-epm executable so that
double-clicking a .fdash file opens it in finch-epm.

Uses HKEY_CURRENT_USER so no administrator privileges are needed.
"""

from __future__ import annotations

import sys
from pathlib import Path


def register_fdash_association(exe_path: str | None = None) -> bool:
    """Register .fdash file association on Windows.

    Args:
        exe_path: Path to the finch-epm executable. If None, uses sys.executable.

    Returns:
        True if registration succeeded.
    """
    if sys.platform != "win32":
        print("File association registration is only supported on Windows.")
        return False

    import winreg

    if exe_path is None:
        exe_path = sys.executable

    exe_path = str(Path(exe_path).resolve())

    try:
        # Register the .fdash extension
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.fdash") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "finch-epm.fdash")

        # Register the ProgID
        prog_id = r"Software\Classes\finch-epm.fdash"

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prog_id) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "finch-epm Dashboard")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prog_id + r"\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')

        # Set a friendly type name
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prog_id + r"\DefaultIcon") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"{exe_path},0")

        print(f"Registered .fdash file association with: {exe_path}")
        return True

    except Exception as e:
        print(f"Failed to register file association: {e}")
        return False


def unregister_fdash_association() -> bool:
    """Remove .fdash file association from Windows registry."""
    if sys.platform != "win32":
        return False

    import winreg

    keys_to_delete = [
        r"Software\Classes\finch-epm.fdash\shell\open\command",
        r"Software\Classes\finch-epm.fdash\shell\open",
        r"Software\Classes\finch-epm.fdash\shell",
        r"Software\Classes\finch-epm.fdash\DefaultIcon",
        r"Software\Classes\finch-epm.fdash",
        r"Software\Classes\.fdash",
    ]

    for key_path in keys_to_delete:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    print("Removed .fdash file association.")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Register .fdash file association")
    parser.add_argument("--unregister", action="store_true", help="Remove file association")
    parser.add_argument("--exe", help="Path to finch-epm executable")
    args = parser.parse_args()

    if args.unregister:
        unregister_fdash_association()
    else:
        register_fdash_association(args.exe)
