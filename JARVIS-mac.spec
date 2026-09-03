# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JARVIS macOS .app bundle.

Separate from JARVIS.spec because the two platforms need genuinely different
things: no pyttsx3/comtypes SAPI driver here (macOS speaks through `say`), an
.icns instead of an .ico, and a BUNDLE step that writes the Info.plist macOS
reads for permission prompts and Gatekeeper.

Build on macOS only — PyInstaller does not cross-compile.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [
    ("addons", "addons"),
    # Seeds a starter .env into Application Support on first run; macOS has no
    # installer to write one.
    (".env.example", "."),
]
binaries = []
hiddenimports = [
    "PIL._tkinter_finder",
    "PIL.ImageGrab",
    # Addons are imported dynamically, so nothing they need is visible to
    # static analysis — list it explicitly.
    "pypdf",
    # jarvis/net.py pins TLS verification to certifi's bundle rather than the
    # system store.
    "certifi",
]

for pkg in ("customtkinter", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("certifi")

# pynput is optional: only the global hotkey uses it, and only when the user
# opts in by setting JARVIS_HOTKEY. Include it if it is installed.
try:
    d, b, h = collect_all("pynput")
    datas += d
    binaries += b
    hiddenimports += h
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
    excludes=[
        "PyInstaller", "pytest", "matplotlib",
        # Windows-only speech stack.
        "pyttsx3", "comtypes", "win32com", "winreg",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX mangles Mach-O binaries and breaks code signing outright.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,          # built for whatever the runner is
    codesign_identity=None,    # signing happens in CI, after the bundle exists
    entitlements_file=None,
    icon="assets/jarvis.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="JARVIS",
)

app = BUNDLE(
    coll,
    name="JARVIS.app",
    icon="assets/jarvis.icns",
    # Stable and reverse-DNS: macOS keys granted permissions to this string, so
    # changing it makes users re-approve the microphone every release.
    bundle_identifier="com.jarvissystem20324.jarvis",
    info_plist={
        "CFBundleName": "JARVIS",
        "CFBundleDisplayName": "JARVIS",
        "CFBundleExecutable": "JARVIS",
        "CFBundleShortVersionString": "2.6",
        "CFBundleVersion": "2.6",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # Without this the app is treated as a background agent and its window
        # never takes focus properly.
        "LSUIElement": False,
        "NSHumanReadableCopyright": "Ahmed Zahid Dilmen",
        # macOS shows these verbatim in the permission prompts. Vague text here
        # is a common reason users deny a permission and report the app broken.
        "NSMicrophoneUsageDescription":
            "JARVIS uses the microphone only while you hold the mic button, "
            "to turn what you say into text.",
        "NSAppleEventsUsageDescription":
            "JARVIS uses system speech to read its replies aloud.",
    },
)
