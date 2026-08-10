# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JARVIS desktop app."""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [("assets/jarvis.ico", "assets")]
binaries = []
hiddenimports = [
    "PIL._tkinter_finder",
    # pyttsx3 loads its Windows driver by name at runtime, so PyInstaller
    # cannot see the import statically.
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "comtypes.stream",
]

# customtkinter ships its theme JSON as package data.
for pkg in ("customtkinter", "sounddevice", "comtypes"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# httpx/openai verify TLS against certifi's bundle.
datas += collect_data_files("certifi")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyInstaller", "pytest", "matplotlib"],
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
    name="JARVIS",
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
