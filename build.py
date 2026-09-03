"""Build JARVIS.exe and the JARVIS-Setup.exe installer.

Order matters: the installer bundles the app EXE as a payload, so the app is
always built first.

    python build.py            build both
    python build.py --app      only JARVIS.exe
    python build.py --setup    only the installer (reuses dist/JARVIS.exe)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"


def run_pyinstaller(spec: str) -> int:
    print(f"\n=== Building {spec} ===")
    return subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", spec], cwd=ROOT
    ).returncode


def ensure_icon() -> None:
    if (ROOT / "assets" / "jarvis.ico").exists():
        return
    print("Generating assets/jarvis.ico ...")
    from PIL import Image, ImageDraw, ImageFont

    def logo(size: int) -> Image.Image:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([0, 0, size - 1, size - 1], fill="#0a0e17")
        inset = size // 12
        draw.ellipse(
            [inset, inset, size - inset, size - inset],
            outline="#00d4ff",
            width=max(2, size // 24),
        )
        try:
            font = ImageFont.truetype("arialbd.ttf", int(size * 0.5))
        except OSError:
            font = ImageFont.load_default()
        draw.text((size / 2, size / 2), "J", fill="#00d4ff", font=font, anchor="mm")
        return img

    sizes = [16, 24, 32, 48, 64, 128, 256]
    (ROOT / "assets").mkdir(exist_ok=True)
    logo(256).save(ROOT / "assets" / "jarvis.ico", sizes=[(s, s) for s in sizes])


def stamp_version() -> str:
    """Write assets/version.txt so the installer reports the same version."""
    sys.path.insert(0, str(ROOT))
    from jarvis import __version__

    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "version.txt").write_text(__version__, encoding="utf-8")
    return __version__


def main() -> int:
    args = sys.argv[1:]
    build_app = "--setup" not in args
    build_setup = "--app" not in args

    ensure_icon()
    stamp_version()

    if build_app:
        shutil.rmtree(ROOT / "build" / "JARVIS", ignore_errors=True)
        if run_pyinstaller("JARVIS.spec") != 0:
            return 1
        env_file = ROOT / ".env"
        if env_file.exists():
            shutil.copy2(env_file, DIST / ".env")
            print("Copied .env next to dist/JARVIS.exe for local testing.")
        if not verify_build(DIST / "JARVIS.exe"):
            return 1

    if build_app:
        write_manifest()

    if build_setup:
        if not (DIST / "JARVIS.exe").exists():
            print("dist/JARVIS.exe not found — build the app first.")
            return 1
        if not verify_build(DIST / "JARVIS.exe"):
            print("Refusing to bundle a broken app into the installer.")
            return 1
        shutil.rmtree(ROOT / "build" / "JARVIS-Setup", ignore_errors=True)
        if run_pyinstaller("JARVIS-Setup.spec") != 0:
            return 1

        RELEASE.mkdir(exist_ok=True)
        setup = DIST / "JARVIS-Setup.exe"
        shutil.copy2(setup, RELEASE / "JARVIS-Setup.exe")
        size_mb = setup.stat().st_size / 1024 / 1024
        print(f"\nInstaller: release/JARVIS-Setup.exe  ({size_mb:.1f} MB)")
        print("This installer contains NO API key — it prompts for one at install time.")

    print("\nBuild complete.")
    return 0


def verify_build(exe: Path) -> bool:
    """Run the frozen app's self-test and refuse to ship a build that fails.

    A windowed build reports nothing when it dies, so without this a corrupt
    EXE sails straight into release/ and out to users.
    """
    print(f"\n=== Verifying {exe.name} ===")
    report = exe.parent / "jarvis-selftest.txt"
    report.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            [str(exe), "--selftest"], cwd=str(exe.parent), timeout=300,
            capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        print("FAILED: the app hung on startup.")
        return False

    if result.returncode != 0 or not report.exists():
        print(f"FAILED: exit code {result.returncode}, no self-test report.")
        print("The packaged app does not run. Rebuild with:")
        print("  python -m PyInstaller --clean --noconfirm JARVIS.spec")
        return False

    text = report.read_text(encoding="utf-8", errors="replace")
    if "[FAIL]" in text:
        print("FAILED: self-test reported problems:")
        for line in text.splitlines():
            if "[FAIL]" in line:
                print("  " + line)
        return False

    print(f"OK: {text.splitlines()[0]}")
    return True


def write_manifest() -> None:
    """Emit release/update.json and a copy of the EXE for in-app updates.

    Upload both to your host, then point JARVIS_UPDATE_URL at the JSON.
    """
    import hashlib
    import json

    sys.path.insert(0, str(ROOT))
    from jarvis import __version__

    exe = DIST / "JARVIS.exe"
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()

    RELEASE.mkdir(exist_ok=True)
    shutil.copy2(exe, RELEASE / "JARVIS.exe")

    manifest_path = RELEASE / "update.json"
    existing = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            pass

    windows_url = existing.get("url", "https://REPLACE-ME/JARVIS.exe")

    # Keep the flat url/sha256 at the top level: every release published so far
    # looks like that, and clients already in the wild read only those fields.
    # New clients prefer the per-platform block, which is what stops a Mac
    # being handed a .exe.
    platforms = dict(existing.get("platforms") or {})
    platforms["windows"] = {"url": windows_url, "sha256": digest}

    manifest_path.write_text(
        json.dumps(
            {
                "version": __version__,
                "url": windows_url,
                "sha256": digest,
                "notes": existing.get("notes", f"JARVIS {__version__}"),
                "platforms": platforms,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Manifest : release/update.json  (v{__version__}, sha256 {digest[:16]}...)")
    macs = sorted(k for k in platforms if k.startswith("macos"))
    print(f"           platforms: {', '.join(sorted(platforms))}")
    if not macs:
        print("           no macOS build listed yet — see PUBLISHING-MAC.md")


if __name__ == "__main__":
    sys.exit(main())
