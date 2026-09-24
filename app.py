"""GUI entry point for JARVIS 2.0."""

from __future__ import annotations

import sys
import traceback


def selftest() -> int:
    """Report which subsystems loaded. Written to a file next to the EXE.

    A windowed build has no console, so this is the only way to diagnose a
    broken install (missing audio DLLs, bad key, etc.).
    """
    from jarvis.config import IS_MACOS, get_base_dir, load_config

    load_config()
    from jarvis import __version__

    lines: list[str] = [f"JARVIS {__version__} self-test", "=" * 40]

    def check(label: str, fn) -> None:
        try:
            lines.append(f"[ OK ] {label}: {fn()}")
        except Exception as exc:
            lines.append(f"[FAIL] {label}: {type(exc).__name__}: {exc}")

    def warn(label: str, fn) -> None:
        """Report something JARVIS can run without.

        Kept distinct from check() because the build gate fails on [FAIL].
        A machine with no sound card is a fact about the machine, not a broken
        build, and a CI runner has no audio at all.
        """
        try:
            lines.append(f"[ OK ] {label}: {fn()}")
        except Exception as exc:
            lines.append(f"[WARN] {label}: unavailable ({type(exc).__name__})")

    check("frozen", lambda: getattr(sys, "frozen", False))
    check("base dir", lambda: get_base_dir())

    import jarvis.voice as v

    lines.append(f"[{' OK ' if v._HAS_AUDIO else 'FAIL'}] sounddevice/numpy loaded: {v._HAS_AUDIO}")

    # Speech output differs by platform: Windows drives pyttsx3/SAPI, macOS the
    # built-in `say`. pyttsx3 is deliberately excluded from the Mac build, so
    # reporting its absence there as a failure would fail a healthy build.
    if IS_MACOS:
        import shutil as _shutil

        speaks = bool(_shutil.which("say"))
        lines.append(f"[{' OK ' if speaks else 'FAIL'}] macOS speech (say): {speaks}")
    else:
        lines.append(
            f"[{' OK ' if v._HAS_PYTTSX3 else 'FAIL'}] pyttsx3 loaded: {v._HAS_PYTTSX3}"
        )

    warn("audio output devices", lambda: _count_devices(output=True))
    warn("audio input devices", lambda: _count_devices(output=False))
    check("customtkinter", lambda: __import__("customtkinter").__version__)
    check("openai sdk", lambda: __import__("openai").__version__)

    from jarvis import providers
    from jarvis.config import get_image_provider

    # A configured provider is what makes the app usable at all, so name every
    # one rather than just reporting whether a single key exists.
    for label, configured, _note in providers.describe():
        lines.append(f"[{' OK ' if configured else '    '}] provider {label}: "
                     f"{'configured' if configured else 'not configured'}")

    check("chat chain", lambda: ", ".join(p.label for p in providers.chat_chain())
          or "NONE — add a free key, see README")
    check("speech-to-text", lambda: ", ".join(p.label for p in providers.stt_chain())
          or "none (needs a free Groq key or faster-whisper)")
    check("image backend", lambda: "OpenAI (paid)"
          if get_image_provider() == "openai"
          else "FLUX.1-dev on NVIDIA, Pollinations as fallback"
          if get_image_provider() in {"auto", "nvidia", "flux"} and providers.has_key(providers.NVIDIA)
          else "Pollinations (free, no key)")
    check("output dir", lambda: __import__(
        "jarvis.config", fromlist=["get_output_dir"]).get_output_dir())

    def _addons() -> str:
        from jarvis.addons import AddonManager

        manager = AddonManager(jarvis=None)
        manager.load_all()
        names = [entry.addon.name for entry in manager.loaded]
        report = f"{len(names)} loaded ({', '.join(names)})" if names else "none found"
        if manager.errors:
            report += f" | problems: {'; '.join(manager.errors)}"
        return report

    check("addons", _addons)

    def _tls() -> str:
        """Prove HTTPS actually verifies here.

        A missing certificate store only shows up on other people's machines,
        so make one real request rather than trusting that it works.
        """
        import urllib.error

        from jarvis import net

        source = "certifi bundle" if net.using_certifi() else "OS certificate store"
        try:
            with net.urlopen("https://example.com/", timeout=20) as response:
                code = response.status
        except urllib.error.HTTPError as exc:
            # The handshake completed and the certificate verified — that is
            # the whole point of this check. What the server then chose to
            # answer (403, 404, a rate limit) is not a TLS problem, and failing
            # the build on it once rejected a perfectly good macOS build.
            code = exc.code
        return f"verified via {source} (HTTP {code})"

    check("https/TLS", _tls)

    def _security() -> str:
        """The security features, and what this install itself looks like."""
        from jarvis import security as _sec

        problems = _sec.env_file_findings()
        high = [p for p in problems if p[0] == "high"]
        if high:
            # A real problem with this install should fail the build, not be
            # buried three lines into a passing report.
            raise RuntimeError("; ".join(f"{t} — {d}" for _l, t, d in high))
        state = "prompts on, audit on"
        if problems:
            state += f", {len(problems)} advisory"
        return state

    check("security", _security)

    def _dragdrop() -> str:
        """Drag-and-drop is optional, so report it rather than failing.

        It needs Tcl binaries that PyInstaller does not collect by itself, so
        this is exactly the kind of thing that works in development and is
        quietly missing from the build.
        """
        try:
            import tkinterdnd2
        except ImportError:
            return "not installed — the Attach button still works"
        from pathlib import Path as _P

        tcl = _P(tkinterdnd2.__file__).parent / "tkdnd"
        if not tcl.is_dir():
            return "package present but its Tcl library is missing"
        return f"available ({tkinterdnd2.__name__})"

    check("drag and drop", _dragdrop)

    # 6.0. Each of these is imported lazily at the moment it is used, which
    # is exactly how a library goes missing from a build without anyone
    # noticing until a user asks for it.
    def _voice() -> str:
        import edge_tts  # noqa: F401
        from jarvis import neural

        return f"natural voices available ({len(neural.VOICES)} offered)"

    check("natural voice", _voice)

    def _documents() -> str:
        import tempfile
        from pathlib import Path as _P

        from jarvis import writer

        folder = _P(tempfile.mkdtemp())
        written = [writer.to_docx("# Test\n**ş ğ ı**", folder / "t.docx"),
                   writer.to_pdf("# Test\n**ş ğ ı**", folder / "t.pdf")]
        return ", ".join(f"{p.suffix} {p.stat().st_size // 1024} KB" for p in written)

    check("Word + PDF output", _documents)
    check("spreadsheets", lambda: "openpyxl " + __import__("openpyxl").__version__)
    check("PC status", lambda: f"psutil, {__import__('psutil').cpu_count()} cores")

    def _vault() -> str:
        from jarvis import vault

        if not vault.available():
            return "not available on this platform"
        sealed = vault.protect(b"self-test")
        return "DPAPI round trip ok" if vault.unprotect(sealed) == b"self-test" else "MISMATCH"

    check("encryption", _vault)

    # 7.0
    def _zones() -> str:
        from jarvis import clock

        return clock.answer("15:00 utc in tokyo")

    check("time zones", _zones)
    check("QR codes", lambda: f"qrcode, {__import__('qrcode').make('jarvis').size[0]}px")
    check("calculator", lambda: __import__("jarvis.calc", fromlist=["solve"]).solve("15% of 240"))

    def _ocr() -> str:
        from jarvis import ocr

        if not ocr.available():
            return "not available on this platform"
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (700, 100), "white")
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except OSError:
            font = ImageFont.load_default()
        ImageDraw.Draw(image).text((20, 25), "JARVIS self test", fill="black", font=font)
        text = ocr.read_image_from(image)
        if "self test" not in text.lower():
            raise RuntimeError(f"read {text!r}")
        return "Windows OCR read a test image"

    check("screen text (OCR)", _ocr)

    from jarvis import config as _cfg
    if getattr(_cfg, "last_env_changes", None):
        for change in _cfg.last_env_changes:
            lines.append(f"[ OK ] .env updated: {change}")

    report = "\n".join(lines)
    print(report)
    try:
        (get_base_dir() / "jarvis-selftest.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    return 0 if "[FAIL]" not in report else 1


def _count_devices(output: bool) -> int:
    import sounddevice as sd

    key = "max_output_channels" if output else "max_input_channels"
    return sum(1 for d in sd.query_devices() if d.get(key, 0) > 0)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    try:
        from jarvis.config import load_config

        load_config()
        from ui.app import main as run_ui

        run_ui()
        return 0
    except Exception:
        traceback.print_exc()
        # A frozen windowed build has no console, so surface the error visibly.
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror("JARVIS failed to start", traceback.format_exc())
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
