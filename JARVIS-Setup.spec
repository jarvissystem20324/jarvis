# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JARVIS installer.

Bundles the already-built dist/JARVIS.exe as a payload, so build JARVIS.spec
first. build.py does both in the right order.
"""

from PyInstaller.utils.hooks import collect_all

datas = [
    ("dist/JARVIS.exe", "."),
    ("assets/jarvis.ico", "."),
    ("assets/version.txt", "."),  # written by build.py from jarvis.__version__
]
binaries = []
hiddenimports = [
    "win32com.client",  # shortcut creation via WScript.Shell
    "pythoncom",
    "pywintypes",
]

d, b, h = collect_all("customtkinter")
datas += d
binaries += b
hiddenimports += h

a = Analysis(
    ["installer.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyInstaller", "pytest", "matplotlib", "numpy", "openai", "sounddevice"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="JARVIS-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/jarvis.ico",
)
