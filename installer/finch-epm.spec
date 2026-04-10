# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for finch-epm.

Build with: pyinstaller installer/finch-epm.spec

Produces a directory distribution (onedir) at dist/finch-epm/
containing finch-epm.exe and all dependencies.

Use onedir instead of onefile because:
    - DuckDB has known DLL loading issues in onefile mode
    - Startup is 4-5x faster (1-2 seconds vs 20-60 seconds)
    - Easier to debug packaging issues
"""

import os
import sys
from pathlib import Path

# Project root
ROOT = Path(os.path.abspath(os.path.join(SPECPATH, '..')))
SRC = ROOT / 'src'

block_cipher = None

a = Analysis(
    [str(ROOT / 'installer' / 'entry.py')],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        # Bundle web assets
        (str(SRC / 'finch_epm' / 'server' / 'static'), 'finch_epm/server/static'),
        (str(SRC / 'finch_epm' / 'server' / 'templates'), 'finch_epm/server/templates'),
        # Bundle example dashboards
        (str(ROOT / 'examples'), 'examples'),
    ],
    hiddenimports=[
        # Core
        'duckdb',
        'click',
        'yaml',
        'jwt',
        'httpx',
        'httpx._transports.default',
        'httpcore',
        'httpcore._backends.sync',
        'httpcore._backends.auto',
        'anyio',
        'anyio._backends._asyncio',
        'sniffio',
        'certifi',
        'h11',
        'idna',
        # Keyring
        'keyring',
        'keyring.backends',
        'keyring.backends.Windows',
        # Cryptography
        'cryptography',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.asymmetric.ec',
        'cryptography.hazmat.primitives.asymmetric.rsa',
        # Platform
        'platformdirs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional connectors from base install
        'snowflake',
        'google',
        'psycopg2',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='finch-epm',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Keep console for CLI usage
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='finch-epm',
)
