"""GUI entry point for JARVIS 2.0."""

from __future__ import annotations

import sys
import traceback


def selftest() -> int:
    """Report which subsystems loaded. Written to a file next to the EXE.

    A windowed build has no console, so this is the only way to diagnose a
    broken install (missing audio DLLs, bad key, etc.).
    """
    from jarvis.config import get_base_dir, load_config

    load_config()
    from jarvis import __version__

    lines: list[str] = [f"JARVIS {__version__} self-test", "=" * 40]

    def check(label: str, fn) -> None:
        try:
            lines.append(f"[ OK ] {label}: {fn()}")
        except Exception as exc:
            lines.append(f"[FAIL] {label}: {type(exc).__name__}: {exc}")

    check("frozen", lambda: getattr(sys, "frozen", False))
    check("base dir", lambda: get_base_dir())

    import jarvis.voice as v

    lines.append(f"[{' OK ' if v._HAS_AUDIO else 'FAIL'}] sounddevice/numpy loaded: {v._HAS_AUDIO}")
    lines.append(f"[{' OK ' if v._HAS_PYTTSX3 else 'FAIL'}] pyttsx3 loaded: {v._HAS_PYTTSX3}")

    check("audio output devices", lambda: _count_devices(output=True))
    check("audio input devices", lambda: _count_devices(output=False))
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
