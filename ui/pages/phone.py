"""Phone (10.0): the phone link (scan the QR code, then chat, send files and
swap clipboards from the phone's browser), casting to a TV, and smart plugs.
"""

from __future__ import annotations

import mimetypes
import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jarvis import dlna, kasa, phonelink
from jarvis.config import get_setting
from ui.pages.base import Hub, button, label, open_path, plain


class PhonePage(Hub):
    key = "phone"
    title = "Phone"
    icon = "📱"
    subtitle = "Use JARVIS from your phone, send files both ways, cast to the TV, and switch smart plugs."

    def build_body(self) -> None:
        c = self.colors
        link = self.card("Phone link", "Your phone must be on the same Wi-Fi. Nothing to install — it's a page in "
                                       "the phone's browser.", "📱", span=2)
        body = plain(link.inner)
        body.pack(fill="x")
        self.qr = tkinter.Label(body, bg=c["panel"])
        self.qr.pack(side="left", padx=(0, 16))
        side = plain(body)
        side.pack(side="left", fill="both", expand=True)
        self.link_var = tkinter.BooleanVar(value=phonelink.link.running)
        ctk.CTkSwitch(side, text="Phone link on", variable=self.link_var, command=self.toggle_link).pack(anchor="w")
        self.url = label(side, "", size=12, wrap=520)
        self.url.pack(anchor="w", pady=(8, 0))
        row = plain(side)
        row.pack(fill="x", pady=(6, 0))
        button(row, "⧉ Copy link", self.copy_link, height=26).pack(side="left")
        self.auto = tkinter.BooleanVar(value=get_setting("JARVIS_PHONE_LINK", "off").lower() in {"on", "1", "true"})
        ctk.CTkCheckBox(row, text="Start it with JARVIS", variable=self.auto, command=self.save_auto).pack(
            side="left", padx=12)
        label(side, "On your phone: scan the code with the camera and open the link. Chat, Send (photos and "
                    "files), Clipboard and Files are tabs on that page. The first time, Windows may ask to allow "
                    "JARVIS on private networks — allow it.", size=11, muted=True, wrap=520).pack(anchor="w",
                                                                                                 pady=(8, 0))

        got = self.card("From your phone", "Saved in Downloads › JARVIS from phone.", "📥")
        self.received = plain(got.inner)
        self.received.pack(fill="x")
        button(got.inner, "Open the folder", lambda: open_path(phonelink.inbox()), height=26).pack(anchor="w",
                                                                                                    pady=(6, 0))
        self.clip_note = label(got.inner, "", size=11, muted=True, wrap=420)
        self.clip_note.pack(anchor="w", pady=(6, 0))

        give = self.card("Send to your phone", "Shared files appear on the phone page's Files tab.", "📤")
        button(give.inner, "Share a file…", self.share_file, accent=True, height=28).pack(anchor="w")
        self.shared = plain(give.inner)
        self.shared.pack(fill="x", pady=(6, 0))

        cast = self.card("Cast to TV", "Most smart TVs play files sent this way (DLNA). Chromecast isn't covered.",
                         "📺")
        row = plain(cast.inner)
        row.pack(fill="x")
        button(row, "Find TVs", self.find_tvs, height=28).pack(side="left")
        self.tv_menu = ctk.CTkOptionMenu(row, values=["—"], width=200, fg_color=c["bg"], button_color=c["accent_dim"])
        self.tv_menu.pack(side="left", padx=6)
        row = plain(cast.inner)
        row.pack(fill="x", pady=(6, 0))
        button(row, "▶ Cast a file…", self.cast_file, accent=True, height=28).pack(side="left")
        button(row, "⏸", lambda: self.tv_command(dlna.pause), width=34, height=28).pack(side="left", padx=4)
        button(row, "⏹", lambda: self.tv_command(dlna.stop), width=34, height=28).pack(side="left")
        self.cast_note = label(cast.inner, "", size=11, muted=True, wrap=420)
        self.cast_note.pack(anchor="w", pady=(6, 0))
        self.tvs: list[dict] = []

        plugs = self.card("Smart plugs", "TP-Link Kasa plugs on this network. Tapo plugs need TP-Link's own app.", "🔌")
        button(plugs.inner, "Find plugs", self.find_plugs, height=28).pack(anchor="w")
        self.plug_box = plain(plugs.inner)
        self.plug_box.pack(fill="x", pady=(6, 0))
        self.every("link", 3000, self.refresh)

    def on_show(self) -> None:
        self.show_link()
        self.refresh()

    # --- the link ----------------------------------------------------------------------------------
    def toggle_link(self) -> None:
        if self.link_var.get():
            try:
                phonelink.link.start(self.app.jarvis)
            except OSError as exc:
                self.link_var.set(False)
                self.url.configure(text=str(exc))
                return
        else:
            phonelink.link.stop()
        self.show_link()

    def show_link(self) -> None:
        if not phonelink.link.running:
            self.qr.configure(image="", text="📱", font=("Segoe UI Emoji", 60), fg=self.colors["muted"])
            self.url.configure(text="Off. Switch it on, then scan the code with your phone.")
            return
        url = phonelink.link.url()
        try:
            import qrcode
            from PIL import ImageTk

            made = qrcode.make(url, box_size=6, border=2)
            picture = (made.get_image() if hasattr(made, "get_image") else made).convert("RGB")
            self._qr = ImageTk.PhotoImage(picture.resize((220, 220)), master=self)
            self.qr.configure(image=self._qr, text="")
        except Exception:
            self.qr.configure(image="", text="(QR code unavailable)")
        self.url.configure(text=url)

    def copy_link(self) -> None:
        if phonelink.link.running:
            self.clipboard_clear()
            self.clipboard_append(phonelink.link.url())

    def save_auto(self) -> None:
        from ui.settings import write_env

        write_env({"JARVIS_PHONE_LINK": "on" if self.auto.get() else "off"})

    def refresh(self) -> None:
        for child in self.received.winfo_children():
            child.destroy()
        rows = phonelink.link.received[:8]
        if not rows:
            label(self.received, "Nothing yet.", size=11, muted=True).pack(anchor="w")
        for row in rows:
            line = plain(self.received)
            line.pack(fill="x")
            label(line, f"{row['name']}  ({row['size'] / 1024 / 1024:.1f} MB)", size=12).pack(side="left")
            button(line, "Open", lambda p=row["path"]: open_path(p), height=22).pack(side="right")
        if phonelink.link.from_phone:
            text = phonelink.link.from_phone
            self.clip_note.configure(text="Clipboard from the phone: " + (text[:120] + "…" if len(text) > 120 else text))
        for child in self.shared.winfo_children():
            child.destroy()
        for key, path in list(phonelink.link.shared.items()):
            line = plain(self.shared)
            line.pack(fill="x")
            label(line, path.name, size=12).pack(side="left")
            button(line, "✕", lambda k=key: (phonelink.link.shared.pop(k, None), self.refresh()), width=26,
                   height=22).pack(side="right")

    def share_file(self) -> None:
        path = filedialog.askopenfilename(parent=self)
        if path:
            phonelink.link.share(Path(path))
            self.refresh()
            if not phonelink.link.running:
                self.url.configure(text="Shared — switch the phone link on so the phone can fetch it.")

    # --- TV ----------------------------------------------------------------------------------------
    def find_tvs(self) -> None:
        self.cast_note.configure(text="Looking for TVs…")

        def done(found):
            self.tvs = found if isinstance(found, list) else []
            names = [d["name"] for d in self.tvs] or ["—"]
            self.tv_menu.configure(values=names)
            self.tv_menu.set(names[0])
            self.cast_note.configure(text=f"Found {len(self.tvs)} TV(s)." if self.tvs else
                                     "No TV answered. Is it on, on this network, with DLNA/screen sharing on?")

        self.run(dlna.discover, done)

    def _tv(self) -> dict | None:
        return next((d for d in self.tvs if d["name"] == self.tv_menu.get()), None)

    def cast_file(self) -> None:
        tv = self._tv()
        if tv is None:
            self.cast_note.configure(text="Find TVs first.")
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("Video, music, photos",
                                                                    "*.mp4 *.mkv *.avi *.mov *.mp3 *.m4a *.jpg *.png"),
                                                                   ("All files", "*.*")])
        if not path:
            return
        try:
            if not phonelink.link.running:
                phonelink.link.start(self.app.jarvis)
                self.link_var.set(True)
                self.show_link()
            url = phonelink.link.cast_url(Path(path))
        except OSError as exc:
            self.cast_note.configure(text=str(exc))
            return
        mime = mimetypes.guess_type(path)[0] or "video/mp4"
        self.cast_note.configure(text=f"Sending {Path(path).name} to {tv['name']}…")
        self.run(lambda: dlna.play(tv, url, Path(path).stem, mime),
                 lambda _: self.cast_note.configure(text=f"Playing {Path(path).name} on {tv['name']}."),
                 lambda exc: self.cast_note.configure(text=str(exc)))

    def tv_command(self, action) -> None:
        tv = self._tv()
        if tv is not None:
            self.run(lambda: action(tv), lambda _: None, lambda exc: self.cast_note.configure(text=str(exc)))

    # --- plugs -------------------------------------------------------------------------------------
    def find_plugs(self) -> None:
        for child in self.plug_box.winfo_children():
            child.destroy()
        label(self.plug_box, "Looking…", size=11, muted=True).pack(anchor="w")

        def done(plugs):
            for child in self.plug_box.winfo_children():
                child.destroy()
            if not isinstance(plugs, list) or not plugs:
                label(self.plug_box, "No Kasa plugs answered.", size=11, muted=True).pack(anchor="w")
                return
            for plug in plugs:
                var = tkinter.BooleanVar(value=plug["on"])
                ctk.CTkSwitch(self.plug_box, text=f"{plug['name']}  ({plug['model']})", variable=var,
                              command=lambda p=plug, v=var: self.switch(p, v)).pack(anchor="w", pady=2)

        self.run(kasa.discover, done)

    def switch(self, plug: dict, var: tkinter.BooleanVar) -> None:
        on = var.get()

        def failed(exc):
            var.set(not on)
            label(self.plug_box, f"{plug['name']} didn't answer: {exc}", size=11, muted=True).pack(anchor="w")

        self.run(lambda: kasa.set_power(plug["ip"], on), lambda ok: None if ok else var.set(not on), failed)
