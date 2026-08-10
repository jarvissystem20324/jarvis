"""Graphical installer for JARVIS 2.0.

Bundles JARVIS.exe and installs it per-user (no administrator rights needed):

  * copies the app to the chosen folder
  * writes the .env with the user's own OpenAI key
  * creates Desktop / Start Menu shortcuts
  * registers an entry in Add or Remove Programs
  * runs the app's self-test to confirm the install actually works

The user's API key is NEVER baked into this executable — it is typed in at
install time and written only to the local machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import traceback
import winreg
from pathlib import Path

import customtkinter as ctk

APP_NAME = "JARVIS"


def _app_version() -> str:
    """Version comes from a file build.py writes, so it cannot drift from the app.

    The `jarvis` package itself is not bundled into the installer, so importing
    it only works when running from source.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    stamp = base / "version.txt"
    if stamp.exists():
        text = stamp.read_text(encoding="utf-8").strip()
        if text:
            return text
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from jarvis import __version__

        return __version__
    except Exception:
        return "0.0"


APP_VERSION = _app_version()
PUBLISHER = "JARVIS"
EXE_NAME = "JARVIS.exe"
UNINSTALLER_NAME = "uninstall.exe"
REG_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"

# Where installed copies look for updates. Set this to your manifest URL before
# building the installer; blank simply disables update checks.
UPDATE_URL = os.environ.get("JARVIS_UPDATE_URL", "")

COLORS = {
    "bg": "#0a0e17",
    "panel": "#111827",
    "accent": "#00d4ff",
    "accent_dim": "#0e7490",
    "text": "#e2e8f0",
    "muted": "#64748b",
    "error": "#f87171",
    "ok": "#4ade80",
}

DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def resource_path(name: str) -> Path:
    """Path to a bundled file, whether frozen or running from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def running_frozen() -> bool:
    return getattr(sys, "frozen", False)


def shell_folder(name: str) -> Path | None:
    """Resolve Desktop / Start Menu via the shell, honouring redirection."""
    try:
        from win32com.client import Dispatch

        return Path(Dispatch("WScript.Shell").SpecialFolders(name))
    except Exception:
        fallback = {
            "Desktop": Path.home() / "Desktop",
            "Programs": Path(os.environ.get("APPDATA", ""))
            / "Microsoft/Windows/Start Menu/Programs",
        }.get(name)
        return fallback if fallback and fallback.parent.exists() else None


def create_shortcut(target: Path, link: Path, icon: Path | None = None) -> bool:
    try:
        from win32com.client import Dispatch

        link.parent.mkdir(parents=True, exist_ok=True)
        shortcut = Dispatch("WScript.Shell").CreateShortCut(str(link))
        shortcut.TargetPath = str(target)
        shortcut.WorkingDirectory = str(target.parent)
        shortcut.IconLocation = str(icon or target)
        shortcut.Description = f"{APP_NAME} {APP_VERSION}"
        shortcut.save()
        return True
    except Exception:
        traceback.print_exc()
        return False


def stop_running_app() -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", EXE_NAME],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def register_uninstaller(install_dir: Path, size_kb: int) -> None:
    uninstaller = install_dir / UNINSTALLER_NAME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
        values = {
            "DisplayName": f"{APP_NAME} {APP_VERSION}",
            "DisplayVersion": APP_VERSION,
            "Publisher": PUBLISHER,
            "InstallLocation": str(install_dir),
            "DisplayIcon": str(install_dir / EXE_NAME),
            "UninstallString": f'"{uninstaller}" --uninstall',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def unregister_uninstaller() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except FileNotFoundError:
        pass


def read_install_location() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
            return Path(winreg.QueryValueEx(key, "InstallLocation")[0])
    except OSError:
        return None


# --------------------------------------------------------------------------
# install / uninstall
# --------------------------------------------------------------------------


def do_install(
    install_dir: Path,
    api_key: str,
    desktop_shortcut: bool,
    menu_shortcut: bool,
    log,
) -> bool:
    log("Preparing...")
    stop_running_app()
    install_dir.mkdir(parents=True, exist_ok=True)

    source = resource_path(EXE_NAME)
    if not source.exists():
        log(f"Bundled {EXE_NAME} is missing from this installer.", error=True)
        return False

    log(f"Copying {EXE_NAME}...")
    target = install_dir / EXE_NAME
    shutil.copy2(source, target)

    icon_source = resource_path("jarvis.ico")
    icon_target = install_dir / "jarvis.ico"
    if icon_source.exists():
        shutil.copy2(icon_source, icon_target)
    else:
        icon_target = target

    log("Writing configuration...")
    env_path = install_dir / ".env"
    key_line = api_key.strip() or "sk-put-your-key-here"
    env_path.write_text(
        "\n".join(
            [
                f"OPENAI_API_KEY={key_line}",
                "JARVIS_MODEL=gpt-5.4-mini",
                "JARVIS_IMAGE_MODEL=gpt-image-2",
                "JARVIS_TTS_MODEL=gpt-4o-mini-tts",
                "JARVIS_STT_MODEL=gpt-4o-mini-transcribe",
                "JARVIS_TTS_VOICE=onyx",
                "JARVIS_VOICE=false",
                f"JARVIS_UPDATE_URL={UPDATE_URL}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (install_dir / "output" / "images").mkdir(parents=True, exist_ok=True)

    log("Installing uninstaller...")
    if running_frozen():
        shutil.copy2(sys.executable, install_dir / UNINSTALLER_NAME)

    if desktop_shortcut:
        folder = shell_folder("Desktop")
        if folder and create_shortcut(target, folder / f"{APP_NAME}.lnk", icon_target):
            log("Created Desktop shortcut.")
        else:
            log("Could not create Desktop shortcut.", warn=True)

    if menu_shortcut:
        folder = shell_folder("Programs")
        if folder and create_shortcut(target, folder / f"{APP_NAME}.lnk", icon_target):
            log("Created Start Menu shortcut.")
        else:
            log("Could not create Start Menu shortcut.", warn=True)

    try:
        size_kb = max(1, target.stat().st_size // 1024)
        register_uninstaller(install_dir, size_kb)
        log("Registered in Add or Remove Programs.")
    except OSError as exc:
        log(f"Could not register uninstaller: {exc}", warn=True)

    log("Verifying installation...")
    ok, report = run_selftest(target)
    if ok:
        log("Self-test passed — all components loaded.", ok=True)
    else:
        log("Self-test reported problems (see jarvis-selftest.txt).", warn=True)
        for line in report.splitlines():
            if "[FAIL]" in line:
                log("  " + line.strip(), warn=True)

    log(f"Installed to {install_dir}", ok=True)
    return True


def run_selftest(exe: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(exe), "--selftest"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, f"self-test could not run: {exc}"

    report_file = exe.parent / "jarvis-selftest.txt"
    report = ""
    if report_file.exists():
        report = report_file.read_text(encoding="utf-8", errors="replace")
    report = report or (result.stdout or "")
    return result.returncode == 0 and "[FAIL]" not in report, report


def do_uninstall(log) -> bool:
    install_dir = read_install_location()
    log("Stopping JARVIS...")
    stop_running_app()

    for name in ("Desktop", "Programs"):
        folder = shell_folder(name)
        link = folder / f"{APP_NAME}.lnk" if folder else None
        if link and link.exists():
            try:
                link.unlink()
                log(f"Removed {name} shortcut.")
            except OSError:
                log(f"Could not remove {name} shortcut.", warn=True)

    unregister_uninstaller()
    log("Removed Add or Remove Programs entry.")

    if install_dir and install_dir.exists():
        running_from = Path(sys.executable).resolve().parent
        if running_frozen() and running_from == install_dir.resolve():
            # Can't delete our own directory while running from it — hand the
            # job to a detached shell that waits for us to exit first.
            subprocess.Popen(
                [
                    "cmd", "/c",
                    f'ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{install_dir}"',
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log("Removing files...", ok=True)
        else:
            shutil.rmtree(install_dir, ignore_errors=True)
            log(f"Deleted {install_dir}", ok=True)
    else:
        log("No installation found.", warn=True)

    log("JARVIS has been uninstalled.", ok=True)
    return True


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class InstallerApp(ctk.CTk):
    def __init__(self, uninstall_mode: bool = False):
        super().__init__()
        self.uninstall_mode = uninstall_mode
        self.finished = False

        self.title(f"{APP_NAME} {APP_VERSION} " + ("Uninstaller" if uninstall_mode else "Setup"))
        self.geometry("620x560")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])

        try:
            icon = resource_path("jarvis.ico")
            if icon.exists():
                self.iconbitmap(str(icon))
        except Exception:
            pass

        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=90)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text=APP_NAME,
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(pady=(18, 0))
        ctk.CTkLabel(
            header,
            text="Just A Rather Very Intelligent System"
            + ("  —  Uninstaller" if self.uninstall_mode else f"  —  version {APP_VERSION}"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).pack()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        if self.uninstall_mode:
            self._build_uninstall(body)
        else:
            self._build_install(body)

        self.log_box = ctk.CTkTextbox(
            body,
            height=150,
            wrap="word",
            font=ctk.CTkFont(size=11),
            fg_color="#0f172a",
            text_color=COLORS["text"],
        )
        self.log_box.pack(fill="both", expand=True, pady=(12, 8))
        self.log_box.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 18))

        self.action_btn = ctk.CTkButton(
            footer,
            text="Uninstall" if self.uninstall_mode else "Install",
            width=140,
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
            command=self._start,
        )
        self.action_btn.pack(side="right")

        self.close_btn = ctk.CTkButton(
            footer,
            text="Cancel",
            width=100,
            height=42,
            fg_color="transparent",
            border_width=1,
            command=self.destroy,
        )
        self.close_btn.pack(side="right", padx=(0, 10))

    def _build_install(self, body) -> None:
        ctk.CTkLabel(
            body, text="Install location", text_color=COLORS["text"], anchor="w"
        ).pack(fill="x")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(4, 12))
        self.dir_entry = ctk.CTkEntry(row, height=36)
        self.dir_entry.insert(0, str(DEFAULT_DIR))
        self.dir_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Browse", width=90, height=36, command=self._browse).pack(
            side="left", padx=(8, 0)
        )

        ctk.CTkLabel(
            body, text="OpenAI API key", text_color=COLORS["text"], anchor="w"
        ).pack(fill="x")
        self.key_entry = ctk.CTkEntry(
            body, height=36, show="•", placeholder_text="sk-..."
        )
        self.key_entry.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(
            body,
            text="Stored only on this PC, in .env next to the app. "
            "You can leave this blank and fill it in later.",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["muted"],
            anchor="w",
            wraplength=540,
            justify="left",
        ).pack(fill="x", pady=(0, 10))

        self.desktop_var = ctk.BooleanVar(value=True)
        self.menu_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body, text="Create a Desktop shortcut", variable=self.desktop_var
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            body, text="Add to the Start Menu", variable=self.menu_var
        ).pack(anchor="w", pady=2)

    def _build_uninstall(self, body) -> None:
        location = read_install_location()
        ctk.CTkLabel(
            body,
            text="This will remove JARVIS from your computer.",
            text_color=COLORS["text"],
            anchor="w",
            font=ctk.CTkFont(size=14),
        ).pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(
            body,
            text=f"Location: {location or 'not found'}\n\n"
            "Images you generated are stored inside this folder and will be "
            "deleted too. Move them somewhere else first if you want to keep them.",
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=540,
        ).pack(fill="x")

    def _browse(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title="Choose install folder")
        if chosen:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, str(Path(chosen) / APP_NAME))

    def log(self, message: str, error: bool = False, warn: bool = False, ok: bool = False) -> None:
        def write():
            self.log_box.configure(state="normal")
            prefix = "[x] " if error else "[!] " if warn else "[+] " if ok else "    "
            self.log_box.insert("end", prefix + message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, write)

    def _start(self) -> None:
        self.action_btn.configure(state="disabled")
        self.close_btn.configure(state="disabled", text="Please wait")

        if self.uninstall_mode:
            worker = lambda: self._run(do_uninstall, self.log)  # noqa: E731
        else:
            install_dir = Path(self.dir_entry.get().strip() or DEFAULT_DIR)
            key = self.key_entry.get().strip()
            if key and not key.startswith("sk-"):
                self.log("That does not look like an OpenAI key (should start with 'sk-').", warn=True)
            worker = lambda: self._run(  # noqa: E731
                do_install,
                install_dir,
                key,
                self.desktop_var.get(),
                self.menu_var.get(),
                self.log,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _run(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:
            traceback.print_exc()
            self.log(f"Failed: {exc}", error=True)
        finally:
            self.after(0, self._done)

    def _done(self) -> None:
        self.finished = True
        self.close_btn.configure(state="normal", text="Close")
        if not self.uninstall_mode:
            self.action_btn.configure(
                state="normal", text="Launch JARVIS", command=self._launch
            )

    def _launch(self) -> None:
        exe = Path(self.dir_entry.get().strip() or DEFAULT_DIR) / EXE_NAME
        if exe.exists():
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        self.destroy()


def main() -> int:
    uninstall = "--uninstall" in sys.argv

    if uninstall and running_frozen():
        # Relocate to temp so we can delete the install folder we live in.
        here = Path(sys.executable).resolve()
        install_dir = read_install_location()
        if install_dir and here.parent == install_dir.resolve() and "--relocated" not in sys.argv:
            temp_copy = Path(os.environ["TEMP"]) / f"{APP_NAME}-uninstall.exe"
            try:
                shutil.copy2(here, temp_copy)
                subprocess.Popen([str(temp_copy), "--uninstall", "--relocated"])
                return 0
            except Exception:
                pass  # fall through and try in place

    InstallerApp(uninstall_mode=uninstall).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
