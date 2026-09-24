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

from jarvis import i18n, modes, providers
from jarvis.config import get_base_dir

# (env var, label, where to get one, free?)
FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("GEMINI_API_KEY", "Google Gemini", "aistudio.google.com/apikey", True),
    ("GROQ_API_KEY", "Groq", "console.groq.com/keys", True),
    ("INCEPTION_API_KEY", "Inception Mercury", "platform.inceptionlabs.ai", True),
    ("NVIDIA_API_KEY", "NVIDIA NIM", "build.nvidia.com", True),
    ("OPENROUTER_API_KEY", "OpenRouter", "openrouter.ai/keys", True),
    ("OPENAI_API_KEY", "OpenAI  (paid)", "platform.openai.com/api-keys", False),
    ("BLUEMINDS_API_KEY", "Blueminds  (relay, opt-in)",
     "api.bluesminds.com/console/token", False),
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

        body = ctk.CTkScrollableFrame(self, fg_color=colors["panel"])
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        for env_name, label, where, free in FIELDS:
            self._add_row(body, env_name, label, where, free)

        self._add_model_section(body)
        self._add_appearance_section(body)

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

    # --- actions ----------------------------------------------------------

    def _test(self, env_name: str) -> None:
        """Try the key that is in the box right now, not the saved one."""
        key = self.entries[env_name].get().strip()
        label = self.status[env_name]
        if not key:
            label.configure(text="nothing to test", text_color=self.colors["muted"])
            return
        label.configure(text="testing…", text_color=self.colors["muted"])

        provider = next(
            (p for p in providers.CHAT_PROVIDERS if p.key_env == env_name), None
        )
        if provider is None:
            label.configure(text="unknown provider", text_color=self.colors["error"])
            return

        def work():
            import os
            from openai import OpenAI

            previous = os.environ.get(env_name)
            os.environ[env_name] = key
            try:
                client = OpenAI(api_key=key, base_url=provider.base_url,
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
            if name.endswith("_API_KEY") and e.get().strip()
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
