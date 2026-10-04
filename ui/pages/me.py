"""Memory and Voice (10.0).

Memory: everything JARVIS remembers about you, searchable and editable, plus
the AI tools (three AIs at once, another AI's answer, debates, picture styles,
rewriting). Voice: spoken replies, the voice and its speed, hands-free, and
the global hold-to-talk and selection shortcuts.
"""

from __future__ import annotations

import os
import tkinter

import customtkinter as ctk

from ui.pages.base import Hub, ResultView, button, label


class MemoryPage(Hub):
    key = "memory"
    title = "Memory"
    icon = "🧠"
    subtitle = "What JARVIS remembers about you — and the AI tools."

    def build_body(self) -> None:
        c = self.colors
        card = self.card("What I remember", "Facts JARVIS keeps across chats, sealed on this PC.", "🧠", span=2)
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        self.new_fact = ctk.CTkEntry(row, placeholder_text="Add a fact — “I prefer metric units”", fg_color=c["bg"])
        self.new_fact.pack(side="left", fill="x", expand=True)
        self.new_fact.bind("<Return>", lambda e: self.add())
        button(row, "Remember", self.add, accent=True).pack(side="left", padx=6)
        self.search = ctk.CTkEntry(card.inner, placeholder_text="Search…", fg_color=c["bg"])
        self.search.pack(fill="x", pady=4)
        self.search.bind("<KeyRelease>", lambda e: self.fill())
        self.facts_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.facts_box.pack(fill="x")
        self.section("AI tools")
        self.tools("ask3", "regenerate", "debate", "imagestyle", "rewrite", "compare", "persona", "instructions")

    def _memory(self):
        entry = next((e for e in self.app.jarvis.addons.loaded if e.addon.name == "memory"), None)
        return (entry.addon, self.app.jarvis.addons.ctx) if entry else (None, None)

    def on_show(self) -> None:
        self.fill()

    def fill(self) -> None:
        for child in self.facts_box.winfo_children():
            child.destroy()
        addon, ctx = self._memory()
        if addon is None:
            label(self.facts_box, "The memory addon isn't loaded.", muted=True).pack(anchor="w")
            return
        words = self.search.get().lower().split()
        facts = addon._load(ctx)
        shown = 0
        for number, fact in enumerate(facts, 1):
            text = fact.get("text", "")
            if words and not all(w in text.lower() for w in words):
                continue
            row = ctk.CTkFrame(self.facts_box, fg_color=self.colors["bg"], corner_radius=6)
            row.pack(fill="x", pady=1)
            label(row, f"{text}", size=12, wrap=700).pack(side="left", padx=8, pady=4)
            label(row, fact.get("added", ""), size=10, muted=True).pack(side="left")
            button(row, "🗑", lambda n=number: (addon.forget(ctx, str(n)), self.fill()), width=30,
                   height=22).pack(side="right", padx=4)
            button(row, "Edit", lambda n=number, t=text: self.edit(n, t), width=44, height=22).pack(side="right")
            shown += 1
        if not shown:
            label(self.facts_box, "Nothing yet." if not facts else "Nothing matches.", muted=True).pack(anchor="w")

    def add(self) -> None:
        text = self.new_fact.get().strip()
        addon, ctx = self._memory()
        if text and addon is not None:
            addon.remember(ctx, text)
            self.new_fact.delete(0, "end")
            self.fill()

    def edit(self, number: int, text: str) -> None:
        dialog = ctk.CTkInputDialog(text="Change this fact:", title="Edit")
        new = (dialog.get_input() or "").strip()
        addon, ctx = self._memory()
        if new and addon is not None:
            facts = addon._load(ctx)
            if 0 < number <= len(facts):
                facts[number - 1]["text"] = new
                addon._save(ctx, facts)
            self.fill()


class VoicePage(Hub):
    key = "voice"
    title = "Voice"
    icon = "🎧"
    subtitle = "How JARVIS speaks and listens — and talking to it from any app."

    def build_body(self) -> None:
        from jarvis import neural
        from jarvis.config import get_setting

        c = self.colors
        card = self.card("Speaking", "Spoken replies, the voice and its speed.", "🔊")
        self.voice_var = tkinter.BooleanVar(value=bool(getattr(self.app.jarvis.voice, "enabled", False)))
        ctk.CTkSwitch(card.inner, text="Speak my answers", variable=self.voice_var,
                      command=self.app._toggle_voice).pack(anchor="w")
        voices = dict(neural.VOICES)
        self.voice_menu = ctk.CTkOptionMenu(card.inner, values=list(voices.values()), width=280, fg_color=c["bg"],
                                            button_color=c["accent_dim"])
        current = get_setting("JARVIS_NEURAL_VOICE", neural.DEFAULT_VOICE)
        self.voice_menu.set(voices.get(current, voices[neural.DEFAULT_VOICE]))
        self.voice_menu.pack(anchor="w", pady=6)
        self._voice_codes = {v: k for k, v in voices.items()}
        label(card.inner, "Speed", size=11, muted=True).pack(anchor="w")
        rate = get_setting("JARVIS_VOICE_RATE", "+0%").rstrip("%")
        self.rate = ctk.CTkSlider(card.inner, from_=-50, to=50, number_of_steps=20)
        try:
            self.rate.set(int(rate))
        except ValueError:
            self.rate.set(0)
        self.rate.pack(fill="x")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x", pady=6)
        button(row, "▶ Preview", self.preview).pack(side="left")
        button(row, "💾 Save", self.save, accent=True).pack(side="left", padx=6)
        self.note = label(card.inner, "", size=11, muted=True)
        self.note.pack(anchor="w")
        keys = self.card("Talk from anywhere", "Global shortcuts (type 'off' to disable; restart to apply).", "⌨")
        self.entries = {}
        for env, text, default in (("JARVIS_PTT_HOTKEY", "Hold to talk to JARVIS", "ctrl+alt+v"),
                                   ("JARVIS_SELECT_HOTKEY", "Selection assistant", "ctrl+alt+r"),
                                   ("JARVIS_DICTATE_HOTKEY", "Dictate into any app", "ctrl+alt+d"),
                                   ("JARVIS_QUICKASK_HOTKEY", "Quick ask box", "ctrl+alt+space")):
            row = ctk.CTkFrame(keys.inner, fg_color="transparent")
            row.pack(fill="x", pady=1)
            label(row, text, size=12, width=190).pack(side="left")
            entry = ctk.CTkEntry(row, fg_color=c["bg"])
            entry.insert(0, get_setting(env, default))
            entry.pack(side="left", fill="x", expand=True)
            self.entries[env] = entry
        label(keys.inner, "In the JARVIS window, hold F9 to talk.", size=11, muted=True).pack(anchor="w", pady=4)
        button(keys.inner, "💾 Save shortcuts", self.save_keys).pack(anchor="w")
        self.section("More")
        self.tools("handsfree", "readaloud", "translate", "voice")

    def preview(self) -> None:
        os.environ["JARVIS_NEURAL_VOICE"] = self._voice_codes.get(self.voice_menu.get(), "")
        os.environ["JARVIS_VOICE_RATE"] = f"{int(self.rate.get()):+d}%"
        try:
            self.app.jarvis.voice.speak("Good evening. This is how I will sound.")
            self.note.configure(text="Playing…")
        except Exception as exc:
            self.note.configure(text=f"No voice: {exc}")

    def save(self) -> None:
        from ui.settings import write_env

        values = {"JARVIS_NEURAL_VOICE": self._voice_codes.get(self.voice_menu.get(), ""),
                  "JARVIS_VOICE_RATE": f"{int(self.rate.get()):+d}%"}
        write_env(values)
        os.environ.update(values)
        self.note.configure(text="Saved.")

    def save_keys(self) -> None:
        from ui.settings import write_env

        values = {env: entry.get().strip() or "off" for env, entry in self.entries.items()}
        write_env(values)
        os.environ.update(values)
        self.note.configure(text="Shortcuts saved — restart JARVIS to use them.")
