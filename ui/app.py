"""JARVIS desktop UI built with CustomTkinter."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter
import traceback
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from jarvis import __version__
from jarvis.assistant import Jarvis, JarvisResponse
from jarvis.config import get_output_dir
from jarvis.images import DEFAULT_QUALITY, QUALITIES, SIZES
from jarvis import updater

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": "#0a0e17",
    "panel": "#111827",
    "accent": "#00d4ff",
    "accent_dim": "#0e7490",
    "text": "#e2e8f0",
    "user_bubble": "#1e3a5f",
    "jarvis_bubble": "#1a2332",
    "error": "#f87171",
}

PREVIEW_MAX = 420


def safe_after(widget, callback) -> None:
    """Marshal `callback` onto the Tk thread, tolerating a closed window.

    Worker threads outlive the window if the user quits mid-request; without
    this the thread dies on an unhandled TclError nobody ever sees.
    """
    try:
        widget.after(0, callback)
    except (RuntimeError, tkinter.TclError):
        pass


def _make_placeholder_logo(size: int = 96) -> Image.Image:
    """Simple ring-and-J mark, drawn at runtime so no asset file is needed."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = size // 12
    draw.ellipse(
        [inset, inset, size - inset, size - inset],
        outline=COLORS["accent"],
        width=max(2, size // 24),
    )
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.45))
    except OSError:
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), "J", fill=COLORS["accent"], font=font, anchor="mm")
    return image


class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("JARVIS 2.0")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(fg_color=COLORS["bg"])

        self.jarvis = Jarvis()
        self.current_image: Path | None = None
        self.active_tab = "chat"
        self._busy = False

        self._build_layout()
        self._show_tab("chat")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._append_message("JARVIS", self.jarvis.greet(), is_user=False)
        self.chat_input.focus_set()

        updater.cleanup_previous_update()
        # Quietly look for a new version a moment after the window settles.
        if updater.get_update_url():
            self.after(2500, lambda: self._check_updates(silent=True))

    # --- layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, fg_color=COLORS["panel"], width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(24, 8))

        self.logo_image = ctk.CTkImage(_make_placeholder_logo(64), size=(48, 48))
        ctk.CTkLabel(header, image=self.logo_image, text="").pack(side="left", padx=(0, 10))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(
            title_box,
            text="JARVIS",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")
        self.version_label = ctk.CTkLabel(
            title_box,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=11),
            text_color="#475569",
        )
        self.version_label.pack(anchor="w")

        ctk.CTkLabel(
            sidebar,
            text="Just A Rather Very\nIntelligent System",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
            justify="left",
        ).pack(fill="x", padx=16, pady=(0, 20))

        self.chat_tab_btn = ctk.CTkButton(
            sidebar,
            text="💬  Chat",
            anchor="w",
            height=40,
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent_dim"],
            command=lambda: self._show_tab("chat"),
        )
        self.chat_tab_btn.pack(fill="x", padx=16, pady=4)

        self.image_tab_btn = ctk.CTkButton(
            sidebar,
            text="🎨  Image Gen",
            anchor="w",
            height=40,
            fg_color="transparent",
            hover_color=COLORS["accent_dim"],
            command=lambda: self._show_tab("image"),
        )
        self.image_tab_btn.pack(fill="x", padx=16, pady=4)

        self.voice_btn = ctk.CTkButton(
            sidebar,
            text=self._voice_label(),
            anchor="w",
            height=40,
            fg_color="transparent",
            hover_color=COLORS["accent_dim"],
            command=self._toggle_voice,
        )
        self.voice_btn.pack(fill="x", padx=16, pady=4)

        ctk.CTkButton(
            sidebar,
            text="🗑  Clear Chat",
            anchor="w",
            height=40,
            fg_color="transparent",
            hover_color="#374151",
            command=self._clear_chat,
        ).pack(fill="x", padx=16, pady=4)

        self.update_btn = ctk.CTkButton(
            sidebar,
            text="⟳  Check for Updates",
            anchor="w",
            height=40,
            fg_color="transparent",
            hover_color=COLORS["accent_dim"],
            command=lambda: self._check_updates(silent=False),
        )
        self.update_btn.pack(fill="x", padx=16, pady=4)

        self.status_label = ctk.CTkLabel(
            sidebar,
            text="Ready",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
            wraplength=190,
        )
        self.status_label.pack(side="bottom", fill="x", padx=16, pady=16)

        # Main content area
        self.content = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_chat_tab()
        self._build_image_tab()

    def _build_chat_tab(self) -> None:
        self.chat_frame = ctk.CTkFrame(self.content, fg_color=COLORS["bg"])
        self.chat_frame.grid_rowconfigure(0, weight=1)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_log = ctk.CTkTextbox(
            self.chat_frame,
            wrap="word",
            font=ctk.CTkFont(size=14),
            fg_color=COLORS["panel"],
            text_color=COLORS["text"],
            activate_scrollbars=True,
        )
        self.chat_log.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        self._configure_tags()
        self.chat_log.configure(state="disabled")

        input_row = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        input_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        input_row.grid_columnconfigure(0, weight=1)

        self.chat_input = ctk.CTkEntry(
            input_row,
            placeholder_text="Ask JARVIS anything... (/image prompt to generate)",
            height=44,
            font=ctk.CTkFont(size=14),
        )
        self.chat_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.chat_input.bind("<Return>", lambda e: self._send_chat())

        self.mic_btn = ctk.CTkButton(
            input_row,
            text="🎤",
            width=44,
            height=44,
            command=self._listen,
        )
        self.mic_btn.grid(row=0, column=1, padx=(0, 8))

        self.send_btn = ctk.CTkButton(
            input_row,
            text="Send",
            width=88,
            height=44,
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
            command=self._send_chat,
        )
        self.send_btn.grid(row=0, column=2)

    def _build_image_tab(self) -> None:
        self.image_frame = ctk.CTkFrame(self.content, fg_color=COLORS["bg"])
        self.image_frame.grid_rowconfigure(1, weight=1)
        self.image_frame.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(self.image_frame, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkLabel(
            head,
            text="Image Generation",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")
        self.image_model_label = ctk.CTkLabel(
            head,
            text=f"Powered by {self.jarvis.images.model}",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        )
        self.image_model_label.pack(anchor="w")

        body = ctk.CTkFrame(self.image_frame, fg_color=COLORS["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.image_prompt = ctk.CTkTextbox(
            body,
            height=90,
            wrap="word",
            font=ctk.CTkFont(size=13),
            fg_color="#0f172a",
            text_color=COLORS["text"],
        )
        self.image_prompt.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        self.image_prompt.insert(
            "1.0",
            "A futuristic JARVIS AI interface, holographic blue glow, dark lab",
        )

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        ctk.CTkLabel(controls, text="Size:", text_color=COLORS["text"]).pack(
            side="left", padx=(0, 8)
        )
        self.size_menu = ctk.CTkOptionMenu(controls, values=list(SIZES.keys()), width=190)
        self.size_menu.set(next(iter(SIZES)))
        self.size_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(controls, text="Quality:", text_color=COLORS["text"]).pack(
            side="left", padx=(0, 8)
        )
        self.quality_menu = ctk.CTkOptionMenu(
            controls, values=[q.capitalize() for q in QUALITIES], width=110
        )
        self.quality_menu.set(DEFAULT_QUALITY.capitalize())
        self.quality_menu.pack(side="left")

        self.generate_btn = ctk.CTkButton(
            controls,
            text="Generate Image",
            width=150,
            height=36,
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
            command=self._generate_image,
        )
        self.generate_btn.pack(side="right")

        self.preview_label = ctk.CTkLabel(
            body,
            text="Generated image will appear here",
            text_color="#64748b",
        )
        self.preview_label.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)

        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

        ctk.CTkButton(
            footer,
            text="Open Folder",
            width=120,
            fg_color="transparent",
            border_width=1,
            command=self._open_output_folder,
        ).pack(side="left")

        self.open_image_btn = ctk.CTkButton(
            footer,
            text="Open Image",
            width=120,
            state="disabled",
            command=self._open_current_image,
        )
        self.open_image_btn.pack(side="left", padx=8)

    def _configure_tags(self) -> None:
        """Colour the sender names. CTkTextbox wraps a tk.Text underneath."""
        textbox = getattr(self.chat_log, "_textbox", self.chat_log)
        textbox.tag_config("user", foreground="#60a5fa")
        textbox.tag_config("jarvis", foreground=COLORS["accent"])

    def _show_tab(self, tab: str) -> None:
        self.active_tab = tab
        self.chat_frame.grid_forget()
        self.image_frame.grid_forget()

        if tab == "chat":
            self.chat_frame.grid(row=0, column=0, sticky="nsew")
            self.chat_tab_btn.configure(fg_color=COLORS["accent_dim"])
            self.image_tab_btn.configure(fg_color="transparent")
        else:
            self.image_frame.grid(row=0, column=0, sticky="nsew")
            self.image_tab_btn.configure(fg_color=COLORS["accent_dim"])
            self.chat_tab_btn.configure(fg_color="transparent")

    # --- chat -------------------------------------------------------------

    def _append_message(self, sender: str, text: str, is_user: bool) -> None:
        self.chat_log.configure(state="normal")
        tag = "user" if is_user else "jarvis"
        textbox = getattr(self.chat_log, "_textbox", self.chat_log)
        textbox.insert("end", f"{sender}:\n", tag)
        textbox.insert("end", f"{text}\n\n")
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

    def _set_busy(self, busy: bool, status: str = "Ready") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.send_btn, self.mic_btn, self.generate_btn, self.chat_input):
            widget.configure(state=state)
        self.status_label.configure(text=status)

    def _run_worker(self, work, status: str) -> None:
        """Run `work()` off-thread, marshalling results back to the Tk loop."""
        self._set_busy(True, status)
        threading.Thread(target=work, daemon=True).start()

    def _send_chat(self) -> None:
        if self._busy:
            return
        text = self.chat_input.get().strip()
        if not text:
            return
        self.chat_input.delete(0, "end")
        self._append_message("You", text, is_user=True)

        def work():
            try:
                response = self.jarvis.process(text)
                safe_after(self, lambda: self._handle_response(response))
            except Exception as exc:
                message = f"Error: {exc}"
                traceback.print_exc()
                safe_after(self, lambda: self._handle_error(message))

        self._run_worker(work, "Thinking...")

    def _handle_response(self, response: JarvisResponse) -> None:
        self._set_busy(False)
        self._append_message("JARVIS", response.text, is_user=False)
        if response.image_path:
            self.current_image = response.image_path
            self._show_image_preview(response.image_path)
            self._show_tab("image")
        if response.should_quit:
            self._on_close()

    def _handle_error(self, message: str) -> None:
        self._set_busy(False)
        self._append_message("JARVIS", message, is_user=False)

    def _listen(self) -> None:
        if self._busy:
            return

        def work():
            try:
                response = self.jarvis.listen_and_respond()
                safe_after(self, lambda: self._handle_voice(response))
            except Exception as exc:
                message = f"Voice error: {exc}"
                traceback.print_exc()
                safe_after(self, lambda: self._handle_error(message))

        self._run_worker(work, "Listening...")

    def _handle_voice(self, response: JarvisResponse | None) -> None:
        self._set_busy(False)
        if response is None:
            self._append_message("JARVIS", "No speech detected.", is_user=False)
            return
        self._append_message("JARVIS", response.text, is_user=False)
        if response.image_path:
            self.current_image = response.image_path
            self._show_image_preview(response.image_path)

    # --- images -----------------------------------------------------------

    def _generate_image(self) -> None:
        if self._busy:
            return
        prompt = self.image_prompt.get("1.0", "end").strip()
        if not prompt:
            self.status_label.configure(text="Enter a prompt first.")
            return

        size = SIZES[self.size_menu.get()]
        quality = self.quality_menu.get().lower()

        def work():
            try:
                response = self.jarvis.generate_image(prompt, size=size, quality=quality)
                safe_after(self, lambda: self._on_image_generated(response))
            except Exception as exc:
                message = str(exc)
                traceback.print_exc()
                safe_after(self, lambda: self._on_image_error(message))

        self._run_worker(work, "Generating image...")

    def _on_image_generated(self, response: JarvisResponse) -> None:
        self._set_busy(False)
        if response.image_path:
            self.current_image = response.image_path
            self._show_image_preview(response.image_path)
            self.status_label.configure(text="Image saved.")
        else:
            self._on_image_error(response.text)

    def _on_image_error(self, error: str) -> None:
        self._set_busy(False)
        self.preview_label.configure(image=None, text=f"Error: {error}")
        self.status_label.configure(text="Generation failed.")

    def _show_image_preview(self, path: Path) -> None:
        try:
            image = Image.open(path)
        except OSError as exc:
            self.preview_label.configure(image=None, text=f"Could not open image: {exc}")
            return

        width, height = image.size
        scale = min(PREVIEW_MAX / width, PREVIEW_MAX / height, 1.0)
        display = ctk.CTkImage(image, size=(int(width * scale), int(height * scale)))
        # Keep a reference or Tk will garbage-collect the image.
        self.preview_image = display
        self.preview_label.configure(image=display, text="")
        self.open_image_btn.configure(state="normal")

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606 - user-initiated
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            self.status_label.configure(text=f"Could not open: {exc}")

    def _open_output_folder(self) -> None:
        self._open_path(get_output_dir())

    def _open_current_image(self) -> None:
        if self.current_image and self.current_image.exists():
            self._open_path(self.current_image)

    # --- misc -------------------------------------------------------------

    def _voice_label(self) -> str:
        return "🔊  Voice: ON" if self.jarvis.voice_enabled else "🔇  Voice: OFF"

    def _toggle_voice(self) -> None:
        message = self.jarvis.toggle_voice()
        self.voice_btn.configure(text=self._voice_label())
        self._append_message("JARVIS", message, is_user=False)

    def _clear_chat(self) -> None:
        self.jarvis.brain.clear_history()
        self.chat_log.configure(state="normal")
        self.chat_log.delete("1.0", "end")
        self.chat_log.configure(state="disabled")
        self._append_message("JARVIS", "Conversation cleared.", is_user=False)

    # --- updates ----------------------------------------------------------

    def _check_updates(self, silent: bool = False) -> None:
        """Look for a newer release. `silent` suppresses 'nothing new' noise."""
        if not silent:
            self.update_btn.configure(state="disabled", text="⟳  Checking...")

        def work():
            try:
                info = updater.check_for_update()
                safe_after(self, lambda: self._on_update_result(info, None, silent))
            except updater.UpdateError as exc:
                message = str(exc)
                safe_after(self, lambda: self._on_update_result(None, message, silent))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, error: str | None, silent: bool) -> None:
        self.update_btn.configure(state="normal", text="⟳  Check for Updates")

        if error:
            if not silent:
                self._append_message("JARVIS", f"Update check failed. {error}", is_user=False)
            return

        if info is None:
            if not silent:
                self._append_message(
                    "JARVIS", f"You're on the latest version (v{__version__}).", is_user=False
                )
            return

        self.version_label.configure(text=f"v{__version__} → v{info.version}")
        UpdateDialog(self, info)

    def _on_close(self) -> None:
        try:
            self.jarvis.voice.stop()
        except Exception:
            pass
        self.destroy()


class UpdateDialog(ctk.CTkToplevel):
    """Shows the release notes, then downloads and installs on confirmation."""

    def __init__(self, parent: JarvisApp, info):
        super().__init__(parent)
        self.info = info
        self.downloaded: Path | None = None

        self.title("Update available")
        self.geometry("460x340")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        self.transient(parent)
        self.after(100, self.grab_set)  # wait for the window to exist

        ctk.CTkLabel(
            self,
            text=f"JARVIS {info.version} is available",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(pady=(20, 2), padx=20)
        ctk.CTkLabel(
            self,
            text=f"You have {__version__}",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        ).pack()

        notes = ctk.CTkTextbox(
            self,
            height=120,
            wrap="word",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["panel"],
            text_color=COLORS["text"],
        )
        notes.pack(fill="both", expand=True, padx=20, pady=12)
        notes.insert("1.0", info.notes or "No release notes provided.")
        notes.configure(state="disabled")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="#64748b"
        )
        self.status.pack()

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(4, 18))
        self.later_btn = ctk.CTkButton(
            row, text="Later", width=100, fg_color="transparent",
            border_width=1, command=self.destroy,
        )
        self.later_btn.pack(side="right", padx=(8, 0))
        self.install_btn = ctk.CTkButton(
            row, text="Update now", width=130,
            fg_color=COLORS["accent_dim"], hover_color=COLORS["accent"],
            command=self._install,
        )
        self.install_btn.pack(side="right")

    def _install(self) -> None:
        self.install_btn.configure(state="disabled")
        self.later_btn.configure(state="disabled")
        self.progress.pack(fill="x", padx=20, pady=(0, 4), before=self.status)
        self.status.configure(text="Downloading...")

        def progress(done: int, total: int) -> None:
            if total:
                safe_after(self, lambda: self.progress.set(done / total))
                mb = f"{done/1048576:.1f} / {total/1048576:.1f} MB"
            else:
                mb = f"{done/1048576:.1f} MB"
            safe_after(self, lambda: self.status.configure(text=f"Downloading... {mb}"))

        def work():
            try:
                path = updater.download_update(self.info, progress)
                safe_after(self, lambda: self.status.configure(text="Verified. Restarting..."))
                updater.apply_update(path)  # replaces the EXE and relaunches
            except updater.UpdateError as exc:
                message = str(exc)
                safe_after(self, lambda: self._failed(message))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, message: str) -> None:
        self.progress.pack_forget()
        self.status.configure(text=message, text_color=COLORS["error"])
        self.install_btn.configure(state="normal", text="Retry")
        self.later_btn.configure(state="normal", text="Close")


def main() -> None:
    app = JarvisApp()
    app.mainloop()


if __name__ == "__main__":
    main()
