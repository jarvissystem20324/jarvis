"""Automations (10.0): build "when this, do that" without typing a command,
start from a template, see what ran, pause everything, record macros, and
reach Home Assistant."""

from __future__ import annotations

import time
import tkinter
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from jarvis import macro, security
from jarvis.ten import automate
from ui.pages.base import Card, Hub, ResultView, button, label

TRIGGER_FIELDS = {
    "time": [("at", "At (HH:MM)", "08:30"), ("days", "Days", "every day")],
    "every": [("minutes", "Every … minutes", "60")],
    "start": [],
    "wifi": [("ssid", "Network name (blank: any)", "")],
    "folder": [("folder", "Folder", ""), ("pattern", "Files like", "*")],
    "battery": [("below", "Below (%)", "20")],
    "program_end": [("program", "Program (e.g. ffmpeg.exe)", "")],
    "rain": [("chance", "Chance of rain at least (%)", "50"), ("at", "Check at", "20:00")],
    "youtube": [("channel", "Channel (@handle or link)", "")],
    "phrase": [("phrase", "Phrase (several: a | b)", "good night")],
}


class AutomationsPage(Hub):
    key = "automations"
    title = "Automations"
    icon = "⚙"
    subtitle = "When something happens, JARVIS does the steps you choose — while it's open."

    def build_body(self) -> None:
        c = self.colors
        top = self.card("Your automations", "", "⚙", span=2)
        row = ctk.CTkFrame(top.inner, fg_color="transparent")
        row.pack(fill="x")
        self.pause_var = tkinter.BooleanVar(value=automate.paused())
        ctk.CTkSwitch(row, text="Pause all", variable=self.pause_var, command=self.toggle_pause).pack(side="left")
        button(row, "＋ New automation", self.new, accent=True).pack(side="right")
        self.list_box = ctk.CTkFrame(top.inner, fg_color="transparent")
        self.list_box.pack(fill="x", pady=6)
        self._builder()
        self._templates()
        log = self.card("Log", "What ran, when, and what happened.", "📜")
        self.log_box = ctk.CTkFrame(log.inner, fg_color="transparent")
        self.log_box.pack(fill="x")
        self._macros()
        self._home_assistant()
        self.section("Tools")
        self.tools("routine", "webhook", "task", "every", "watchpage", "alert")

    def on_show(self) -> None:
        self.fill_list()
        self.fill_log()
        self.fill_macros()

    # --- list ------------------------------------------------------------------------
    def toggle_pause(self) -> None:
        self.app.jarvis.automation_cmd("pause" if self.pause_var.get() else "resume")

    def fill_list(self) -> None:
        c = self.colors
        for child in self.list_box.winfo_children():
            child.destroy()
        items = automate.load()
        if not items:
            label(self.list_box, "None yet — start from a template below, or make your own.", muted=True).pack(anchor="w")
        for item in items:
            row = ctk.CTkFrame(self.list_box, fg_color=c["bg"], corner_radius=8)
            row.pack(fill="x", pady=2)
            var = tkinter.BooleanVar(value=item.get("enabled", True))
            ctk.CTkSwitch(row, text="", variable=var, width=40,
                          command=lambda i=item, v=var: self.set_enabled(i, v.get())).pack(side="left", padx=6)
            last = f" · last ran {datetime.fromtimestamp(item['last_run']):%d %b %H:%M}" if item.get("last_run") else ""
            label(row, f"{item['name']}", size=13, bold=True).pack(side="left")
            label(row, f"  {automate.describe_trigger(item['trigger'])} → {len(item['steps'])} step(s){last}",
                  size=11, muted=True).pack(side="left")
            button(row, "🗑", lambda i=item: self.delete(i), width=30, height=24).pack(side="right", padx=4)
            button(row, "Edit", lambda i=item: self.edit(i), width=50, height=24).pack(side="right")
            button(row, "▶ Run now", lambda i=item: self.run_now(i), height=24).pack(side="right", padx=4)

    def set_enabled(self, item: dict, on: bool) -> None:
        items = automate.load()
        for a in items:
            if a["id"] == item["id"]:
                a["enabled"] = on
        automate.save_all(items)

    def delete(self, item: dict) -> None:
        automate.save_all([a for a in automate.load() if a["id"] != item["id"]])
        self.fill_list()

    def run_now(self, item: dict) -> None:
        self.app.run_tool(f"/automation run {item['name']}", lambda r: (self.fill_log(), self.fill_list(),
                                                                        self.app.status_label.configure(
                                                                            text=str(getattr(r, 'text', r))[:90])),
                          name="automation")

    def fill_log(self) -> None:
        for child in self.log_box.winfo_children():
            child.destroy()
        items = automate.AUTO_LOG.load()
        if not items:
            label(self.log_box, "Nothing has run yet.", muted=True).pack(anchor="w")
        for i in items[:14]:
            label(self.log_box, f"{datetime.fromtimestamp(i['at']):%d %b %H:%M}  {'✔' if i['ok'] else '✘'} "
                                f"{i['name']} — {i['detail'][:70]}", size=11, wrap=460,
                  text_color=self.colors["text"] if i["ok"] else self.colors["error"]).pack(anchor="w")

    # --- builder --------------------------------------------------------------------------
    def _builder(self) -> None:
        c = self.colors
        card = self.card("Build an automation", "Pick a trigger, add steps, save.", "🛠")
        self.editing: str | None = None
        self.name = ctk.CTkEntry(card.inner, placeholder_text="Name", fg_color=c["bg"])
        self.name.pack(fill="x", pady=2)
        label(card.inner, "When…", size=12, bold=True).pack(anchor="w", pady=(6, 0))
        names = {v: k for k, v in automate.TRIGGERS.items()}
        self.trigger_menu = ctk.CTkOptionMenu(card.inner, values=list(names), fg_color=c["bg"],
                                              button_color=c["accent_dim"], command=lambda v: self.draw_trigger())
        self.trigger_menu.set(automate.TRIGGERS["time"])
        self.trigger_menu.pack(fill="x")
        self._trigger_names = names
        self.trigger_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.trigger_box.pack(fill="x")
        self.trigger_inputs: dict[str, ctk.CTkEntry] = {}
        label(card.inner, "Do…", size=12, bold=True).pack(anchor="w", pady=(8, 0))
        self.steps_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.steps_box.pack(fill="x")
        self.step_rows: list[tuple] = []
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x", pady=4)
        button(row, "＋ Add step", lambda: self.add_step(), height=26).pack(side="left")
        button(row, "💾 Save", self.save, accent=True, height=26).pack(side="right")
        self.builder_note = label(card.inner, "", size=11, muted=True, wrap=440)
        self.builder_note.pack(anchor="w")
        self.draw_trigger()
        self.add_step("notify", "")

    def trigger_type(self) -> str:
        return self._trigger_names.get(self.trigger_menu.get(), "time")

    def draw_trigger(self, values: dict | None = None) -> None:
        for child in self.trigger_box.winfo_children():
            child.destroy()
        self.trigger_inputs = {}
        for key, text, default in TRIGGER_FIELDS[self.trigger_type()]:
            row = ctk.CTkFrame(self.trigger_box, fg_color="transparent")
            row.pack(fill="x", pady=1)
            label(row, text, size=11, muted=True, width=180).pack(side="left")
            entry = ctk.CTkEntry(row, fg_color=self.colors["bg"])
            value = (values or {}).get(key, default)
            if value not in (None, ""):
                entry.insert(0, str(value))
            entry.pack(side="left", fill="x", expand=True)
            if key == "folder":
                button(row, "…", lambda e=entry: self._pick_folder(e), width=30, height=26).pack(side="left", padx=2)
            self.trigger_inputs[key] = entry

    def _pick_folder(self, entry) -> None:
        folder = filedialog.askdirectory(parent=self)
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)

    def add_step(self, kind: str = "command", value: str = "") -> None:
        c = self.colors
        row = ctk.CTkFrame(self.steps_box, fg_color="transparent")
        row.pack(fill="x", pady=1)
        names = {v: k for k, v in automate.STEPS.items()}
        menu = ctk.CTkOptionMenu(row, values=list(names), width=170, fg_color=c["bg"], button_color=c["accent_dim"])
        menu.set(automate.STEPS.get(kind, automate.STEPS["command"]))
        menu.pack(side="left")
        entry = ctk.CTkEntry(row, fg_color=c["bg"], placeholder_text="/volume 20 · text · URL · light.turn_on light.desk")
        if value:
            entry.insert(0, value)
        entry.pack(side="left", fill="x", expand=True, padx=4)
        record = (row, menu, entry, names)
        button(row, "…", lambda e=entry: self._pick_file(e), width=26, height=26).pack(side="left")
        button(row, "✕", lambda r=record: self.remove_step(r), width=26, height=26).pack(side="left", padx=2)
        self.step_rows.append(record)

    def _pick_file(self, entry) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("Scripts", "*.py *.ps1 *.bat *.cmd *.js"),
                                                                  ("All", "*.*")])
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def remove_step(self, record) -> None:
        record[0].destroy()
        self.step_rows.remove(record)

    def new(self) -> None:
        self.editing = None
        self.name.delete(0, "end")
        self.trigger_menu.set(automate.TRIGGERS["time"])
        self.draw_trigger()
        for record in list(self.step_rows):
            self.remove_step(record)
        self.add_step("notify", "")
        self.builder_note.configure(text="")

    def load_into_builder(self, automation: dict, editing: str | None) -> None:
        self.editing = editing
        self.name.delete(0, "end")
        self.name.insert(0, automation.get("name", ""))
        trigger = automation.get("trigger", {})
        self.trigger_menu.set(automate.TRIGGERS.get(trigger.get("type"), automate.TRIGGERS["time"]))
        self.draw_trigger(trigger)
        for record in list(self.step_rows):
            self.remove_step(record)
        for step in automation.get("steps", []):
            self.add_step(step.get("type", "command"), str(step.get("value", "")))
        self.body._parent_canvas.yview_moveto(0.15)

    def edit(self, item: dict) -> None:
        self.load_into_builder(item, item["id"])
        self.builder_note.configure(text=f"Editing {item['name']} — Save to update it.")

    def save(self) -> None:
        kind = self.trigger_type()
        trigger = {"type": kind}
        for key, entry in self.trigger_inputs.items():
            value = entry.get().strip()
            if key in {"minutes", "below", "chance"}:
                try:
                    value = float(value)
                except ValueError:
                    self.builder_note.configure(text=f"{key.capitalize()} must be a number.")
                    return
            trigger[key] = value
        if kind == "time" and not str(trigger.get("at", "")).count(":"):
            self.builder_note.configure(text="Time like 08:30")
            return
        steps = []
        for _row, menu, entry, names in self.step_rows:
            value = entry.get().strip()
            step_kind = names.get(menu.get(), "command")
            if not value and step_kind not in {"digest"}:
                continue
            if step_kind == "command" and not value.startswith("/"):
                value = "/" + value
            steps.append({"type": step_kind, "value": value})
        if not steps:
            self.builder_note.configure(text="Add at least one step.")
            return
        scripts = [s["value"] for s in steps if s["type"] == "script"]
        if scripts and not security.permissions.ask(security.RUN_COMMAND,
                                                    "let this automation run: " + ", ".join(scripts),
                                                    context="Automations"):
            self.builder_note.configure(text="Not saved — the scripts weren't approved.")
            return
        items = automate.load()
        name = self.name.get().strip() or automate.TRIGGERS[kind]
        if self.editing:
            for item in items:
                if item["id"] == self.editing:
                    item.update(name=name, trigger=trigger, steps=steps, approved_scripts=scripts)
        else:
            item = automate.new_automation(name, trigger, steps)
            item["approved_scripts"] = scripts
            items.append(item)
        automate.save_all(items)
        self.builder_note.configure(text=f"Saved “{name}”.")
        self.editing = None
        self.fill_list()

    # --- templates -----------------------------------------------------------------------
    def _templates(self) -> None:
        card = self.card("Templates", "One click fills the builder — change anything, then Save.", "✨")
        for i, template in enumerate(automate.TEMPLATES):
            button(card.inner, template["name"], lambda t=template: self._use_template(t), height=28, width=200).grid(
                row=i // 2, column=i % 2, padx=3, pady=3, sticky="w")

    def _use_template(self, template: dict) -> None:
        self.load_into_builder(template, None)
        self.builder_note.configure(text=f"Template “{template['name']}” loaded — Save to add it.")

    # --- macros ---------------------------------------------------------------------------
    def _macros(self) -> None:
        c = self.colors
        card = self.card("Macro recorder", "Records clicks and keys; F10 stops recording, Esc stops playback.", "🎬")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        self.record_btn = button(row, "● Record", self.toggle_record, accent=True)
        self.record_btn.pack(side="left")
        self.speed = ctk.CTkOptionMenu(row, values=["0.5×", "1×", "2×", "4×"], width=70, fg_color=c["bg"],
                                       button_color=c["accent_dim"])
        self.speed.set("1×")
        self.speed.pack(side="left", padx=6)
        self.macro_note = label(card.inner, "", size=11, muted=True, wrap=440)
        self.macro_note.pack(anchor="w", pady=4)
        self.macro_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.macro_box.pack(fill="x")
        self._watch_job = None

    def toggle_record(self) -> None:
        if macro.recorder.recording:
            self._finish_recording(by_click=True)
            return
        if not macro.AVAILABLE:
            self.macro_note.configure(text="The macro recorder works on Windows only.")
            return
        if not security.permissions.ask(security.RUN_COMMAND, "record your mouse and keyboard until you press F10",
                                        context="Macro recorder"):
            return
        macro.recorder.start()
        self.record_btn.configure(text="■ Stop (F10)", fg_color=self.colors["error"])
        self.macro_note.configure(text="🔴 Recording… do the task, then press F10.")
        self._watch_recording()

    def _watch_recording(self) -> None:
        if macro.recorder.recording:
            self._watch_job = self.after(300, self._watch_recording)
        else:
            self._finish_recording(by_click=False)

    def _finish_recording(self, by_click: bool) -> None:
        events = macro.tidy(macro.recorder.stop(), stopped_by_click=by_click)
        self.record_btn.configure(text="● Record", fg_color=self.colors["accent_dim"])
        if not events:
            self.macro_note.configure(text="Nothing recorded.")
            return
        name = ctk.CTkInputDialog(text=f"Name this macro ({macro.describe(events)}):", title="Save macro").get_input()
        if not name:
            self.macro_note.configure(text="Discarded.")
            return
        macro.save(name.strip(), events)
        self.macro_note.configure(text=f"Saved {name.strip()} — use it as a step: Play a recorded macro.")
        self.fill_macros()

    def fill_macros(self) -> None:
        for child in self.macro_box.winfo_children():
            child.destroy()
        for name, data in macro.MACROS.load().items():
            row = ctk.CTkFrame(self.macro_box, fg_color="transparent")
            row.pack(fill="x", pady=1)
            label(row, f"🎬 {name}  ({macro.describe(data['events'])})", size=12).pack(side="left")
            button(row, "🗑", lambda n=name: self._delete_macro(n), width=30, height=24).pack(side="right")
            button(row, "▶ Play", lambda n=name: self._play(n), height=24).pack(side="right", padx=4)

    def _play(self, name: str) -> None:
        data = macro.MACROS.load().get(name)
        if not data:
            return
        speed = float(self.speed.get().rstrip("×"))
        self.macro_note.configure(text=f"▶ Playing {name} in 2 s… (Esc stops)")
        self.after(2000, lambda: macro.player.play(data["events"], speed, on_done=lambda ok: self.after(
            0, lambda: self.macro_note.configure(text="Done." if ok else "Stopped."))))

    def _delete_macro(self, name: str) -> None:
        macros = macro.MACROS.load()
        macros.pop(name, None)
        macro.MACROS.save(macros)
        self.fill_macros()

    # --- Home Assistant ----------------------------------------------------------------------
    def _home_assistant(self) -> None:
        card = self.card("Home Assistant", "Add your URL and token in Settings → Other keys, then load your devices.",
                         "🏠")
        button(card.inner, "Load devices", self.load_ha, height=26).pack(anchor="w")
        self.ha_box = ctk.CTkScrollableFrame(card.inner, fg_color="transparent", height=180)
        self.ha_box.pack(fill="x", pady=4)

    def load_ha(self) -> None:
        def done(states):
            for child in self.ha_box.winfo_children():
                child.destroy()
            if isinstance(states, str):
                label(self.ha_box, states, muted=True, wrap=420).pack(anchor="w")
                return
            useful = [s for s in states if s["entity_id"].split(".")[0] in {"light", "switch", "fan", "input_boolean"}]
            for s in useful[:60]:
                row = ctk.CTkFrame(self.ha_box, fg_color="transparent")
                row.pack(fill="x")
                name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
                label(row, f"{'🟡' if s.get('state') == 'on' else '⚫'} {name}", size=12).pack(side="left")
                button(row, "Toggle", lambda e=s["entity_id"]: self.app.run_tool(
                    f"/ha {e} toggle", lambda r: self.load_ha(), name="ha"), height=22).pack(side="right")
            if not useful:
                label(self.ha_box, "No lights or switches found.", muted=True).pack(anchor="w")

        self.run(lambda: automate.ha_request("/api/states"), done, lambda e: done(f"Home Assistant: {e}"))
