# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JARVIS desktop app."""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# The built-in addons ride along as data and are copied out beside the EXE on
# first run, so users can read and edit them like any other addon.
datas = [
    ("assets/jarvis.ico", "assets"),
    ("addons", "addons"),
    # Seeds a starter .env on first run where no installer wrote one.
    (".env.example", "."),
]
binaries = []
hiddenimports = [
    "PIL._tkinter_finder",
    "PIL.ImageGrab",
    # pyttsx3 loads its Windows driver by name at runtime, so PyInstaller
    # cannot see the import statically.
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "comtypes.stream",
    # Addons are imported dynamically, so nothing they need is detectable by
    # static analysis — list their dependencies explicitly.
    "pypdf",
    # jarvis/net.py pins TLS verification to certifi's bundle. Without the
    # module present, frozen builds fall back to the OS certificate store and
    # fail on machines that lack the roots.
    "certifi",
]

# customtkinter ships its theme JSON as package data.
for pkg in ("customtkinter", "sounddevice", "comtypes"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# httpx/openai verify TLS against certifi's bundle.
datas += collect_data_files("certifi")
# tkinterdnd2 ships Tcl binaries that PyInstaller does not find on its
# own; without them drag-and-drop silently falls back to the button.
try:
    datas += collect_data_files("tkinterdnd2")
    hiddenimports += ["tkinterdnd2"]
except Exception:
    pass

# 6.0: natural voices, Word and PDF output, spreadsheets, PC status. All are
# imported inside functions, so they are listed rather than trusted to be
# found; docx and fpdf also carry templates and data files of their own.
for pkg in ("edge_tts", "docx", "fpdf", "openpyxl", "qrcode", "tzdata"):
    try:
        datas += collect_data_files(pkg)
        hiddenimports += [pkg]
    except Exception:
        pass
hiddenimports += ["psutil", "aiohttp", "docx.oxml", "fpdf.fonts"]
# 7.1: YouTube captions (it brings requests, and defusedxml for the caption XML).
try:
    hiddenimports += collect_submodules("youtube_transcript_api") + ["requests", "defusedxml"]
    datas += collect_data_files("youtube_transcript_api")
except Exception:
    pass

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
