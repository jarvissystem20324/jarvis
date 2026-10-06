"""Settings window — manage provider keys without editing .env by hand.

Nearly every failure this project has hit traced back to a key: one revoked,
one with no credit, one denied by its project, one pasted with a stray word in
front of it. Each needed a text editor and a restart to diagnose. This puts
the keys, and a Test button that says exactly what each one does, in the app.

Keys are written straight back to .env and never leave the machine. Entries
are masked, and the file is only rewritten for values the user actually
changed — an untouched field cannot blank out a working key.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import customtkinter as ctk

from jarvis import i18n, modes, providers, websearch
from jarvis.config import get_base_dir

# (env var, label, where to get one, free?)
FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("GEMINI_API_KEY", "Google Gemini", "aistudio.google.com/apikey", True),
    ("GROQ_API_KEY", "Groq", "console.groq.com/keys", True),
    ("INCEPTION_API_KEY", "Inception Mercury", "platform.inceptionlabs.ai", True),
    ("NVIDIA_API_KEY", "NVIDIA NIM", "build.nvidia.com", True),
    ("MISTRAL_API_KEY", "Mistral", "console.mistral.ai/api-keys", True),
    ("CLOUDFLARE_API_TOKEN", "Cloudflare Workers AI", "dash.cloudflare.com/profile/api-tokens", True),
    ("CLOUDFLARE_ACCOUNT_ID", "Cloudflare account ID", "dash.cloudflare.com (right sidebar)", True),
    ("OPENROUTER_API_KEY", "OpenRouter", "openrouter.ai/keys", True),
    ("OPENAI_API_KEY", "OpenAI  (paid)", "platform.openai.com/api-keys", False),
    ("BLUEMINDS_API_KEY", "Blueminds  (paid relay)",
     "api.bluesminds.com/console/token", False),
    ("LLMSRELAY_API_KEY", "LLMsRelay  (paid relay, coding agent)", "llmsrelay.com", False),
    # Not a chat provider: web search, tested and counted on its own.
    ("FIRECRAWL_API_KEY", "Firecrawl  (web search)", "firecrawl.dev/app/api-keys", False),
)

_SETTING = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_env() -> dict[str, str]:
    path = get_base_dir() / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = _SETTING.match(line)
            if match:
                values[match.group(1)] = match.group(2).strip()
    except OSError:
        pass
    return values


def write_env(updates: dict[str, str]) -> None:
    """Set these keys in .env, leaving every other line untouched."""
    path = get_base_dir() / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = _SETTING.match(line)
        if match and match.group(1) in remaining:
            name = match.group(1)
            lines[index] = f"{name}={remaining.pop(name)}"
    for name, value in remaining.items():
        lines.append(f"{name}={value}")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, colors: dict):
        super().__init__(parent)
        self.colors = colors
        self.title("JARVIS settings")
        self.geometry("660x680")
        self.configure(fg_color=colors["bg"])
        self.transient(parent)

        self.entries: dict[str, ctk.CTkEntry] = {}
        # Dropdowns, kept apart from the text boxes because their value
        # has to be mapped from a label back to a code before saving.
        self.choices: dict[str, tuple] = {}
        self.status: dict[str, ctk.CTkLabel] = {}
        self.original = read_env()

        ctk.CTkLabel(
            self, text="API keys", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=colors["accent"],
        ).pack(anchor="w", padx=24, pady=(20, 2))
        ctk.CTkLabel(
            self,
            text="Two or more keeps JARVIS working when one is rate limited or "
                 "out of credit. Stored only on this PC, in .env.",
            font=ctk.CTkFont(size=11), text_color=colors["muted"],
            anchor="w", wraplength=580, justify="left",
        ).pack(anchor="w", padx=24, pady=(0, 14))

        # 10.0: type to find a setting instead of scrolling for it.
        self.search = ctk.CTkEntry(self, placeholder_text="🔎 Search settings — “voice”, “accent”, “battery”…",
                                   height=32)
        self.search.pack(fill="x", padx=20, pady=(0, 8))
        self.search.bind("<KeyRelease>", lambda e: self._filter())

        body = ctk.CTkScrollableFrame(self, fg_color=colors["panel"])
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.body = body

        for env_name, label, where, free in FIELDS:
            self._add_row(body, env_name, label, where, free)

        self._add_model_section(body)
        self._add_assistant_section(body)
        self._add_appearance_section(body)
        self._add_ten_section(body)
        self._rows = [(child, self._words(child), child.pack_info()) for child in body.winfo_children()]

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 18))
        self.summary = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont(size=11),
            text_color=colors["muted"], anchor="w",
        )
        self.summary.pack(side="left")
        ctk.CTkButton(footer, text="Close", width=90, fg_color="transparent",
                      hover_color=colors["accent_dim"], command=self.destroy
                      ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(footer, text="Save", width=110,
                      fg_color=colors["accent_dim"], hover_color=colors["accent"],
                      command=self._save).pack(side="right")

        self._refresh_summary()
        self.after(220, self.lift)
        self.after(240, self.focus_force)

    def _add_row(self, parent, env_name: str, label: str, where: str, free: bool) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 4))

        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=label, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=self.colors["text"]).pack(side="left")
        ctk.CTkLabel(head, text="free" if free else "paid", anchor="w",
                     font=ctk.CTkFont(size=10),
                     text_color=self.colors["ok"] if free else self.colors["muted"]
                     ).pack(side="left", padx=8)

        entry = ctk.CTkEntry(row, height=34, show="•", placeholder_text=where)
        entry.pack(fill="x", pady=(4, 2))
        existing = self.original.get(env_name, "")
        if existing:
            entry.insert(0, existing)
        self.entries[env_name] = entry

        line = ctk.CTkFrame(row, fg_color="transparent")
        line.pack(fill="x")
        state = ctk.CTkLabel(line, text="configured" if existing else "not set",
                             font=ctk.CTkFont(size=10), anchor="w",
                             text_color=self.colors["ok"] if existing
                             else self.colors["muted"])
        state.pack(side="left")
        self.status[env_name] = state
        ctk.CTkButton(line, text="Test", width=64, height=24,
                      fg_color="transparent", hover_color=self.colors["accent_dim"],
                      command=lambda n=env_name: self._test(n)).pack(side="right")

    def _add_model_section(self, parent) -> None:
        """Let each thinking mode be re-pointed at a different model.

        Providers retire models without notice — this project has lost three
        that way — and until now the only remedy was a new release. These
        boxes write JARVIS_MODE_<TIER> into .env, so a dead tier can be fixed
        in the app in under a minute.
        """
        ctk.CTkFrame(parent, height=1, fg_color=self.colors["accent_dim"]).pack(
            fill="x", padx=10, pady=(18, 10)
        )
        ctk.CTkLabel(
            parent, text="Models per mode", anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors["accent"],
        ).pack(anchor="w", padx=12)
        ctk.CTkLabel(
            parent,
            text="provider:model — leave blank for the built-in choice. "
                 "Use /bench to see which models are actually answering.",
            font=ctk.CTkFont(size=10), text_color=self.colors["muted"],
            anchor="w", justify="left", wraplength=520,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        for mode in modes.ALL:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)

            ctk.CTkLabel(
                row, text=mode.label, width=92, anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=mode.accent,
            ).pack(side="left")

            builtin = ", ".join(f"{p}:{m}" for p, m in mode.targets) or "the provider chain"
            entry = ctk.CTkEntry(row, height=30, placeholder_text=builtin)
            entry.pack(side="left", fill="x", expand=True)
            existing = self.original.get(modes.env_key(mode), "")
            if existing:
                entry.insert(0, existing)
            self.entries[modes.env_key(mode)] = entry

    def _heading(self, parent, title: str, note: str) -> None:
        ctk.CTkFrame(parent, height=1, fg_color=self.colors["accent_dim"]).pack(
            fill="x", padx=10, pady=(18, 10)
        )
        ctk.CTkLabel(parent, text=title, anchor="w", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=self.colors["accent"]).pack(anchor="w", padx=12)
        ctk.CTkLabel(parent, text=note, font=ctk.CTkFont(size=10), text_color=self.colors["muted"],
                     anchor="w", justify="left", wraplength=520).pack(anchor="w", padx=12, pady=(0, 8))

    def _labelled(self, parent, label: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row, text=label, width=150, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=self.colors["text"]).pack(side="left")
        return row

    def _add_assistant_section(self, parent) -> None:
        """Agent model, voice, home city, privacy switches, dictation."""
        from jarvis import neural

        self._heading(parent, "Assistant",
                      "The agent model is tried first for /agent, /fix and /testgen; if it "
                      "refuses or stays silent the mode's models take over.")

        row = self._labelled(parent, "Coding agent model")
        entry = ctk.CTkEntry(row, height=30, placeholder_text=modes.AGENT_DEFAULT)
        entry.pack(side="left", fill="x", expand=True)
        if self.original.get(modes.AGENT_ENV):
            entry.insert(0, self.original[modes.AGENT_ENV])
        self.entries[modes.AGENT_ENV] = entry

        voices = {code: label for code, label in neural.VOICES}
        voices["offline"] = "Windows voice (offline)"
        row = self._labelled(parent, "Voice")
        menu = ctk.CTkOptionMenu(row, values=list(voices.values()), width=260)
        menu.set(voices.get(self.original.get("JARVIS_NEURAL_VOICE", "").strip(), voices[neural.DEFAULT_VOICE]))
        menu.pack(side="left")
        self.choices["JARVIS_NEURAL_VOICE"] = (menu, {v: k for k, v in voices.items()})

        row = self._labelled(parent, "Home city (weather)")
        city = ctk.CTkEntry(row, height=30, placeholder_text="e.g. Istanbul")
        city.pack(side="left", fill="x", expand=True)
        if self.original.get("JARVIS_CITY"):
            city.insert(0, self.original["JARVIS_CITY"])
        self.entries["JARVIS_CITY"] = city

        for env_name, label, hint in (
            ("JARVIS_DICTATE_HOTKEY", "Dictation shortcut", "ctrl+alt+d  (off to disable)"),
            ("JARVIS_QUICKASK_HOTKEY", "Quick-ask shortcut", "ctrl+alt+space  (off to disable)"),
            ("JARVIS_LOCK_IDLE", "Auto-lock after (min)", "10 — only with a PIN (/lock set)"),
        ):
            row = self._labelled(parent, label)
            box = ctk.CTkEntry(row, height=30, placeholder_text=hint)
            box.pack(side="left", fill="x", expand=True)
            if self.original.get(env_name):
                box.insert(0, self.original[env_name])
            self.entries[env_name] = box

        self._heading(parent, "Privacy",
                      "Encryption ties saved chats, memory and notes to your Windows login. "
                      "Redaction masks keys, passwords, emails and phone numbers before "
                      "anything is sent. Auto web search looks up recent things on its own.")
        switch = {"on": "On", "off": "Off"}
        for env_name, label in (("JARVIS_ENCRYPT", "Encrypt saved data"),
                                ("JARVIS_REDACT", "Redact before sending"),
                                ("JARVIS_AUTO_WEB", "Auto web search"),
                                ("JARVIS_SUGGEST", "Follow-up suggestions")):
            row = self._labelled(parent, label)
            menu = ctk.CTkOptionMenu(row, values=list(switch.values()), width=90)
            current = self.original.get(env_name, "on").strip().lower()
            menu.set("Off" if current in {"off", "0", "false", "no"} else "On")
            menu.pack(side="left")
            self.choices[env_name] = (menu, {v: k for k, v in switch.items()})

    def _add_appearance_section(self, parent) -> None:
        """Theme, text size and interface language."""
        ctk.CTkFrame(parent, height=1, fg_color=self.colors["accent_dim"]).pack(
            fill="x", padx=10, pady=(18, 10)
        )
        ctk.CTkLabel(
            parent, text="Appearance", anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors["accent"],
        ).pack(anchor="w", padx=12)
        ctk.CTkLabel(
            parent, text="Takes effect when JARVIS restarts.",
            font=ctk.CTkFont(size=10), text_color=self.colors["muted"], anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        from ui import theme

        rows = (
            ("JARVIS_THEME", "Theme", list(theme.names().values()),
             {v: k for k, v in theme.names().items()}, theme.names()),
            ("JARVIS_LANGUAGE", "Language", list(i18n.available().values()),
             {v: k for k, v in i18n.available().items()}, i18n.available()),
        )
        for env_name, label, values, to_code, to_label in rows:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(row, text=label, width=92, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=self.colors["text"]).pack(side="left")
            menu = ctk.CTkOptionMenu(row, values=values, width=180)
            current = self.original.get(env_name, "").strip().lower()
            menu.set(to_label.get(current, values[0]))
            menu.pack(side="left")
            # Stored as the code, shown as the human name.
            self.choices[env_name] = (menu, to_code)

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(3, 10))
        ctk.CTkLabel(row, text="Text size", width=92, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=self.colors["text"]).pack(side="left")
        sizes = [str(n) for n in range(theme.MIN_FONT, theme.MAX_FONT + 1, 2)]
        size_menu = ctk.CTkOptionMenu(row, values=sizes, width=90)
        size_menu.set(self.original.get("JARVIS_FONT_SIZE", str(theme.DEFAULT_FONT)))
        size_menu.pack(side="left")
        self.choices["JARVIS_FONT_SIZE"] = (size_menu, None)

    def _add_ten_section(self, parent) -> None:
        """10.0: your colour, your picture, how the window behaves, extra keys."""
        self._heading(parent, "Look and feel",
                      "Accent colour and chat style apply after a restart (the button below restarts JARVIS).")
        row = self._labelled(parent, "Accent colour")
        accent = ctk.CTkEntry(row, height=30, width=110, placeholder_text="#00d4ff")
        accent.pack(side="left")
        if self.original.get("JARVIS_ACCENT"):
            accent.insert(0, self.original["JARVIS_ACCENT"])
        self.entries["JARVIS_ACCENT"] = accent
        swatch = ctk.CTkLabel(row, text="", width=28, height=28, corner_radius=6,
                              fg_color=self.original.get("JARVIS_ACCENT") or self.colors["accent"])
        swatch.pack(side="left", padx=6)

        def pick():
            from tkinter import colorchooser

            chosen = colorchooser.askcolor(parent=self, initialcolor=accent.get() or self.colors["accent"])
            if chosen and chosen[1]:
                accent.delete(0, "end")
                accent.insert(0, chosen[1])
                swatch.configure(fg_color=chosen[1])

        ctk.CTkButton(row, text="Pick…", width=64, height=28, fg_color="transparent",
                      hover_color=self.colors["accent_dim"], command=pick).pack(side="left")
        ctk.CTkButton(row, text="Theme default", width=100, height=28, fg_color="transparent",
                      hover_color=self.colors["accent_dim"],
                      command=lambda: (accent.delete(0, "end"), swatch.configure(fg_color=self.colors["accent"]))
                      ).pack(side="left", padx=4)

        from ui.tenui import CHAT_STYLES

        row = self._labelled(parent, "Chat style")
        menu = ctk.CTkOptionMenu(row, values=list(CHAT_STYLES.values()), width=140)
        menu.set(CHAT_STYLES.get(self.original.get("JARVIS_CHAT_STYLE", "classic"), "Classic"))
        menu.pack(side="left")
        self.choices["JARVIS_CHAT_STYLE"] = (menu, {v: k for k, v in CHAT_STYLES.items()})

        row = self._labelled(parent, "Your name")
        name = ctk.CTkEntry(row, height=30, placeholder_text="shown on your messages and the Home page")
        name.pack(side="left", fill="x", expand=True)
        if self.original.get("JARVIS_USER_NAME"):
            name.insert(0, self.original["JARVIS_USER_NAME"])
        self.entries["JARVIS_USER_NAME"] = name

        row = self._labelled(parent, "Your picture")
        avatar = ctk.CTkEntry(row, height=30, placeholder_text="a photo for your chat messages")
        avatar.pack(side="left", fill="x", expand=True)
        if self.original.get("JARVIS_AVATAR"):
            avatar.insert(0, self.original["JARVIS_AVATAR"])
        self.entries["JARVIS_AVATAR"] = avatar

        def browse():
            from tkinter import filedialog

            path = filedialog.askopenfilename(parent=self, filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp")])
            if path:
                avatar.delete(0, "end")
                avatar.insert(0, path)

        ctk.CTkButton(row, text="Browse…", width=70, height=28, fg_color="transparent",
                      hover_color=self.colors["accent_dim"], command=browse).pack(side="left", padx=4)

        from ui.pages import PAGES

        pages = {p.key: p.label for p in PAGES}
        row = self._labelled(parent, "Start on")
        menu = ctk.CTkOptionMenu(row, values=list(pages.values()), width=140)
        menu.set(pages.get(self.original.get("JARVIS_START_PAGE", "chat"), "Chat"))
        menu.pack(side="left")
        self.choices["JARVIS_START_PAGE"] = (menu, {v: k for k, v in pages.items()})

        switch = {"on": "On", "off": "Off"}
        for env_name, label, default in (("JARVIS_TOASTS", "Corner notifications", "on"),
                                         ("JARVIS_STATUSBAR", "Status bar", "on"),
                                         ("JARVIS_CHIPS", "Tool chips while typing", "on"),
                                         ("JARVIS_ORB", "Floating orb at start", "off")):
            row = self._labelled(parent, label)
            menu = ctk.CTkOptionMenu(row, values=list(switch.values()), width=90)
            current = self.original.get(env_name, default).strip().lower()
            menu.set("Off" if current in {"off", "0", "false", "no"} else "On")
            menu.pack(side="left")
            self.choices[env_name] = (menu, {v: k for k, v in switch.items()})

        row = self._labelled(parent, "Notifications corner")
        menu = ctk.CTkOptionMenu(row, values=["Bottom right", "Top right"], width=140)
        menu.set("Top right" if self.original.get("JARVIS_TOAST_CORNER", "") == "top" else "Bottom right")
        menu.pack(side="left")
        self.choices["JARVIS_TOAST_CORNER"] = (menu, {"Bottom right": "bottom", "Top right": "top"})

        for env_name, label, hint in (("JARVIS_BATTERY_ALERT", "Battery alert at (%)", "20"),
                                      ("JARVIS_EOD_AT", "End-of-day summary at", "21:00 — blank: off")):
            row = self._labelled(parent, label)
            box = ctk.CTkEntry(row, height=30, placeholder_text=hint)
            box.pack(side="left", fill="x", expand=True)
            if self.original.get(env_name):
                box.insert(0, self.original[env_name])
            self.entries[env_name] = box

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)
        ctk.CTkButton(row, text="⌨ Keyboard shortcuts…", fg_color="transparent", hover_color=self.colors["accent_dim"],
                      command=lambda: self.master.open_shortcut_editor()).pack(side="left")
        ctk.CTkButton(row, text="↻ Save and restart JARVIS", fg_color=self.colors["accent_dim"],
                      hover_color=self.colors["accent"], command=self._save_and_restart).pack(side="left", padx=8)

        self._heading(parent, "Other keys", "Optional services some tools use. Stored only in .env on this PC.")
        for env_name, label, hint in (("VIRUSTOTAL_API_KEY", "VirusTotal", "virustotal.com → API key (free)"),
                                      ("GITHUB_TOKEN", "GitHub token", "optional — more /github lookups per hour"),
                                      ("JARVIS_HA_URL", "Home Assistant URL", "http://homeassistant.local:8123"),
                                      ("JARVIS_HA_TOKEN", "Home Assistant token", "Profile → Long-lived access token")):
            row = self._labelled(parent, label)
            box = ctk.CTkEntry(row, height=30, placeholder_text=hint, show="" if env_name.endswith("URL") else "•")
            box.pack(side="left", fill="x", expand=True)
            if self.original.get(env_name):
                box.insert(0, self.original[env_name])
            self.entries[env_name] = box

    def _save_and_restart(self) -> None:
        self._save()
        try:
            self.master.restart()
        except Exception:
            pass

    # --- search --------------------------------------------------------------

    @staticmethod
    def _words(widget) -> str:
        found = []
        stack = [widget]
        while stack:
            current = stack.pop()
            for attr in ("_text", "_placeholder_text"):
                value = getattr(current, attr, None)
                if isinstance(value, str):
                    found.append(value)
            try:
                if isinstance(current, ctk.CTkOptionMenu):
                    found.extend(str(v) for v in current.cget("values") or [])
            except Exception:
                pass
            stack.extend(current.winfo_children())
        return " ".join(found).lower()

    def _filter(self) -> None:
        query = self.search.get().strip().lower()
        for child, _words, _info in self._rows:
            child.pack_forget()
        for child, words, info in self._rows:
            if not query or all(w in words for w in query.split()):
                info = {k: v for k, v in info.items() if k != "in"}
                child.pack(**info)

    # --- actions ----------------------------------------------------------

    def _test(self, env_name: str) -> None:
        """Try the key that is in the box right now, not the saved one."""
        key = self.entries[env_name].get().strip()
        label = self.status[env_name]
        if not key:
            label.configure(text="nothing to test", text_color=self.colors["muted"])
            return
        label.configure(text="testing…", text_color=self.colors["muted"])

        if env_name == websearch.FIRECRAWL_ENV:
            def check():
                # The credit balance: proves the key and costs no credit.
                try:
                    result = (websearch.firecrawl_status(key), self.colors["ok"])
                except websearch.SearchError as exc:
                    result = (str(exc)[:60], self.colors["error"])
                try:
                    self.after(0, lambda: label.configure(text=result[0], text_color=result[1]))
                except Exception:
                    pass

            threading.Thread(target=check, daemon=True).start()
            return

        provider = next(
            (p for p in providers.CHAT_PROVIDERS if p.key_env == env_name or env_name in p.needs_env), None
        )
        if provider is None:
            label.configure(text="unknown provider", text_color=self.colors["error"])
            return
        # A setting such as Cloudflare's account ID is tested with the
        # provider's key from its own box, and the ID filling in the URL.
        api_key = key
        if env_name != provider.key_env:
            api_key = (self.entries[provider.key_env].get().strip() if provider.key_env in self.entries else "")                 or providers.key_for(provider)

        def work():
            import os
            from openai import OpenAI

            previous = os.environ.get(env_name)
            os.environ[env_name] = key
            try:
                client = OpenAI(api_key=api_key, base_url=providers.base_url_for(provider),
                                timeout=45, max_retries=0)
                reply = client.chat.completions.create(
                    model=providers.model_for(provider), max_tokens=256,
                    messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                )
                text = (reply.choices[0].message.content or "").strip()
                result = ("works" + (f" — {text[:18]}" if text else ""),
                          self.colors["ok"])
            except Exception as exc:
                result = (self._explain(exc), self.colors["error"])
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous

            try:
                self.after(0, lambda: label.configure(text=result[0], text_color=result[1]))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _explain(exc: Exception) -> str:
        """Turn a provider error into something worth reading."""
        text = str(getattr(exc, "message", None) or exc).lower()
        if "has not been priced" in text or "model_price_error" in text:
            # Blueminds: the key is accepted, the model is not enabled yet.
            return "key works — model not switched on by the provider yet"
        if "invalid_api_key" in text or "invalid api key" in text or "unauthorized" in text:
            return "key rejected"
        if "no credits" in text or "insufficient_quota" in text or "credit_balance" in text:
            return "valid, but no credit"
        if "denied" in text or "permission" in text:
            return "project denied access"
        if "quota" in text or "rate" in text:
            return "rate limited — try again shortly"
        if "not found" in text or "does not exist" in text:
            return "key fine, default model missing"
        if "timeout" in text or "timed out" in text:
            return "no answer in 45s"
        return f"failed: {type(exc).__name__}"

    def _refresh_summary(self) -> None:
        filled = sum(
            1 for name, e in self.entries.items()
            if name.endswith("_API_KEY") and name != websearch.FIRECRAWL_ENV and e.get().strip()
        )
        if filled >= 2:
            self.summary.configure(
                text=f"{filled} keys configured — a dead one won't stop JARVIS.",
                text_color=self.colors["ok"])
        else:
            self.summary.configure(
                text=f"{filled} key configured — two or more is strongly advised.",
                text_color=self.colors["muted"])

    def _save(self) -> None:
        # Only write what changed, so an untouched box can never blank a key.
        updates = {
            name: entry.get().strip()
            for name, entry in self.entries.items()
            if entry.get().strip() != self.original.get(name, "")
        }
        for name, (widget, to_code) in self.choices.items():
            shown = widget.get()
            value = to_code.get(shown, shown) if to_code else shown
            if value != self.original.get(name, ""):
                updates[name] = value
        if not updates:
            self.summary.configure(text="Nothing changed.",
                                   text_color=self.colors["muted"])
            return
        try:
            write_env(updates)
        except OSError as exc:
            self.summary.configure(text=f"Could not write .env: {exc}",
                                   text_color=self.colors["error"])
            return

        import os

        for name, value in updates.items():
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        providers.reset_clients()
        websearch.reset()
        # New clients are not enough: a provider demoted earlier in the
        # session because its key was rejected stays demoted, so the key the
        # user just fixed would go untried until the next restart.
        try:
            self.master.jarvis.brain.reset_failures()
        except AttributeError:
            pass
        self.original = read_env()

        for name, state in self.status.items():
            if name not in self.entries:
                continue
            has = bool(self.entries[name].get().strip())
            state.configure(text="configured" if has else "not set",
                            text_color=self.colors["ok"] if has
                            else self.colors["muted"])
        self.summary.configure(
            text=f"Saved {len(updates)} change(s). Active immediately.",
            text_color=self.colors["ok"])
