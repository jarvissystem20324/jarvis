"""Security and Antivirus (10.0).

Security: a score with the fixes (each opens the right Windows setting),
devices on your Wi-Fi, browser extensions, camera and mic use, sign-ins and
USB history. Antivirus: Microsoft Defender's status, scans started from here,
a schedule, USB auto-scan and the threat history.
"""

from __future__ import annotations

import time
import tkinter
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from jarvis.ten import shield10
from ui.pages.base import Card, Hub, ResultView, button, label


class SecurityPage(Hub):
    key = "security"
    title = "Security"
    icon = "🛡"
    subtitle = "How safe this PC is, who is on your network, and what can see you."

    def build_body(self) -> None:
        c = self.colors
        card = self.card("Security score", "Each ❌ has a button that opens the Windows setting to fix it.", "🛡", span=2)
        top = ctk.CTkFrame(card.inner, fg_color="transparent")
        top.pack(fill="x")
        self.score_label = label(top, "…", size=44, bold=True, text_color=c["accent"])
        self.score_label.pack(side="left", padx=(0, 20))
        self.checks = ctk.CTkFrame(top, fg_color="transparent")
        self.checks.pack(side="left", fill="x", expand=True)
        button(card.inner, "↻ Check again", self.refresh_score, height=24).pack(anchor="e")
        # Wi-Fi
        wifi = self.card("Who is on my Wi-Fi", "Scans your network (about 20 s). New devices are marked 🆕.", "📡", span=2)
        row = ctk.CTkFrame(wifi.inner, fg_color="transparent")
        row.pack(fill="x")
        button(row, "Scan my network", self.scan_wifi, accent=True).pack(side="left")
        self.wifi_note = label(row, "", size=11, muted=True)
        self.wifi_note.pack(side="left", padx=10)
        self.wifi_box = ctk.CTkFrame(wifi.inner, fg_color="transparent")
        self.wifi_box.pack(fill="x", pady=4)
        # cards with lists
        self.ext_view = self._list_card("Browser extensions", "What each extension can read. ⚠ = sees a lot.", "🧩",
                                        "/extensions")
        self.cam_view = self._list_card("Camera and microphone", "Which apps used them, and when (from Windows).", "📷",
                                        "/camcheck")
        self.login_view = self._list_card("Sign-ins", "Starts, sign-ins, sleeps and wakes this week.", "🔑", "/logins 7")
        self.failed_view = self._list_card("Failed sign-ins", "Wrong-password attempts (needs JARVIS run as "
                                                              "administrator).", "🚨", "/failedlogins")
        self.usb_view = self._list_card("USB devices", "Every USB drive this PC has seen. New ones raise an alert.",
                                        "🔌", "/usbhistory")
        self.vpn_view = self._list_card("What the internet sees", "Your public IP, provider and whether a VPN hides "
                                                                  "them.", "🕶", "/vpncheck")
        self.section("Tools")
        self.tools("stripmeta", "virustotal", "secnews", "firewall", "checklink", "passcheck", "pwned", "encrypt",
                   "decrypt", "shred", "2fa", "wifisafe", "procscan", "hash")

    def _list_card(self, title, subtitle, icon, command) -> ResultView:
        card = self.card(title, subtitle, icon)
        view = ResultView(card.inner, self.app, max_lines=12)
        view.pack(fill="x")
        button(card.inner, "↻ Load", lambda: self.app.run_tool(command, view.show, name=command[1:].split()[0]),
               height=24).pack(anchor="e", pady=(4, 0))
        view._command = command
        return view

    def on_show(self) -> None:
        if not self.checks.winfo_children():
            self.refresh_score()
        for view in (self.ext_view, self.cam_view, self.usb_view):
            if not view.winfo_children():
                self.app.run_tool(view._command, view.show, name=view._command[1:].split()[0])

    def refresh_score(self) -> None:
        self.score_label.configure(text="…")
        self.run(shield10.score, self._show_score, lambda e: self.score_label.configure(text="?"))

    def _show_score(self, result) -> None:
        c = self.colors
        if isinstance(result, str):
            return
        value, checks = result
        colour = c["ok"] if value >= 85 else "#fbbf24" if value >= 60 else c["error"]
        self.score_label.configure(text=f"{value}", text_color=colour)
        for child in self.checks.winfo_children():
            child.destroy()
        for check in checks:
            row = ctk.CTkFrame(self.checks, fg_color="transparent")
            row.pack(fill="x")
            label(row, ("✅ " if check["ok"] else "❌ ") + check["name"], size=12).pack(side="left")
            if not check["ok"]:
                if check.get("page"):
                    button(row, "Fix…", lambda p=check["page"]: shield10.open_setting(p), height=22, width=50).pack(
                        side="right")
                label(row, check["fix"], size=11, muted=True).pack(side="right", padx=8)

    def scan_wifi(self) -> None:
        self.wifi_note.configure(text="Scanning… (about 20 seconds)")
        self.run(shield10.scan_network, self._show_wifi, lambda e: self.wifi_note.configure(text=str(e)))

    def _show_wifi(self, result) -> None:
        c = self.colors
        for child in self.wifi_box.winfo_children():
            child.destroy()
        if isinstance(result, str) or "error" in result:
            self.wifi_note.configure(text=result if isinstance(result, str) else result["error"])
            return
        devices = result["devices"]
        new = sum(1 for d in devices if d["new"])
        self.wifi_note.configure(text=f"{len(devices)} device(s)" + (f", {new} new" if new else ""))
        for d in devices:
            row = ctk.CTkFrame(self.wifi_box, fg_color=c["bg"], corner_radius=6)
            row.pack(fill="x", pady=1)
            icon = {"router": "📶", "this PC": "💻"}.get(d["role"], "🆕" if d["new"] else "•")
            what = d["label"] or d["name"] or d["vendor"] or "unknown device"
            label(row, f"{icon}  {d['ip']:<15}  {what}", size=12).pack(side="left", padx=6, pady=3)
            label(row, d["mac"], size=10, muted=True).pack(side="right", padx=6)
            if d["mac"]:
                button(row, "Name it", lambda m=d["mac"]: self._name_device(m), height=22, width=60).pack(side="right")

    def _name_device(self, mac: str) -> None:
        name = ctk.CTkInputDialog(text=f"A name for {mac}:", title="Name this device").get_input()
        if name is None:
            return
        known = shield10.KNOWN_DEVICES.load()
        known.setdefault(mac, {"first": time.time()})["label"] = name.strip()
        shield10.KNOWN_DEVICES.save(known)
        self.wifi_note.configure(text=f"Saved: {name.strip()}")


class AntivirusPage(Hub):
    key = "antivirus"
    title = "Antivirus"
    icon = "🦠"
    subtitle = "Microsoft Defender's engine, driven from JARVIS: scan, schedule, auto-scan USB drives, see threats."

    def build_body(self) -> None:
        c = self.colors
        status = self.card("Protection", "", "🛡")
        self.lights = ctk.CTkFrame(status.inner, fg_color="transparent")
        self.lights.pack(fill="x")
        row = ctk.CTkFrame(status.inner, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        button(row, "⬇ Update definitions", lambda: self.app.run_tool("/avupdate", self._said, name="avupdate"),
               height=26).pack(side="left")
        button(row, "Open Windows Security", lambda: shield10.open_setting("defender"), height=26).pack(side="left",
                                                                                                         padx=6)
        scan = self.card("Scan", "Quick: the places malware hides (minutes). Full: everything (an hour or more).", "🔍")
        row = ctk.CTkFrame(scan.inner, fg_color="transparent")
        row.pack(fill="x")
        button(row, "Quick scan", lambda: self.start("quick"), accent=True).pack(side="left")
        button(row, "Full scan", lambda: self.start("full")).pack(side="left", padx=6)
        button(row, "A file…", lambda: self.start_path(False)).pack(side="left")
        button(row, "A folder…", lambda: self.start_path(True)).pack(side="left", padx=6)
        self.scan_state = label(scan.inner, "", size=13, bold=True)
        self.scan_state.pack(anchor="w", pady=(8, 0))
        self.scan_detail = label(scan.inner, "", size=11, muted=True, wrap=440)
        self.scan_detail.pack(anchor="w")
        plan = self.card("Schedule and USB", "Runs while JARVIS is open.", "📆")
        row = ctk.CTkFrame(plan.inner, fg_color="transparent")
        row.pack(fill="x")
        settings = shield10.AV_SETTINGS.load()
        current = settings.get("schedule", "")
        self.freq = ctk.CTkOptionMenu(row, values=["off", "daily", "weekly"], width=90, fg_color=c["bg"],
                                      button_color=c["accent_dim"])
        self.freq.set(current.split()[0] if current else "off")
        self.freq.pack(side="left")
        self.at = ctk.CTkEntry(row, width=70, fg_color=c["bg"])
        self.at.insert(0, current.split()[1] if current else "13:00")
        self.at.pack(side="left", padx=6)
        button(row, "Save", self.save_schedule, height=28).pack(side="left")
        self.usb_var = tkinter.BooleanVar(value=settings.get("usb_scan", True))
        ctk.CTkSwitch(plan.inner, text="Scan USB drives when they're plugged in", variable=self.usb_var,
                      command=lambda: self.app.jarvis.usbscan_cmd("on" if self.usb_var.get() else "off")).pack(
            anchor="w", pady=8)
        self.plan_note = label(plan.inner, "", size=11, muted=True)
        self.plan_note.pack(anchor="w")
        history = self.card("Scan history", "", "🗒")
        self.history_box = ctk.CTkFrame(history.inner, fg_color="transparent")
        self.history_box.pack(fill="x")
        threats = self.card("Threats found", "What Defender caught, and whether it dealt with it.", "☣", span=2)
        self.threat_view = ResultView(threats.inner, self.app, max_lines=12)
        self.threat_view.pack(fill="x")
        button(threats.inner, "↻ Load", lambda: self.app.run_tool("/threats", self.threat_view.show, name="threats"),
               height=24).pack(anchor="e")
        self.section("More checks")
        self.tools("virustotal", "procscan")
        self.every("scan", 1000, self.tick)

    def on_show(self) -> None:
        self.refresh_status()
        self.fill_history()
        if not self.threat_view.winfo_children():
            self.app.run_tool("/threats", self.threat_view.show, name="threats")

    def refresh_status(self) -> None:
        def done(found):
            c = self.colors
            for child in self.lights.winfo_children():
                child.destroy()
            d, other = found if isinstance(found, tuple) else ({}, None)
            if other:
                # Windows keeps Defender passive beside another antivirus, so
                # its own switches are off by design — not something to fix.
                label(self.lights, f"🟢 {other['name']} is on — your active antivirus, guarding in real time",
                      size=13).pack(anchor="w")
                if not other["current"]:
                    label(self.lights, f"🔴 {other['name']}'s definitions are out of date", size=13,
                          text_color=c["error"]).pack(anchor="w")
                label(self.lights, "Defender sits beside it in passive mode. Scans from this page use Defender's "
                                   "engine as a second opinion.", size=11, muted=True, wrap=420).pack(anchor="w")
            elif not d:
                label(self.lights, "Defender didn't answer — another antivirus may be in charge.", muted=True,
                      wrap=420).pack(anchor="w")
                return
            else:
                for ok, text in ((d["antivirus"], "Antivirus"), (d["realtime"], "Real-time protection"),
                                 (d["tamper"], "Tamper protection"), (d["behavior"], "Behaviour monitoring")):
                    label(self.lights, ("🟢 " if ok else "🔴 ") + text + (" on" if ok else " OFF"), size=13,
                          text_color=c["text"] if ok else c["error"]).pack(anchor="w")
            if d and d["signatures"]:
                label(self.lights, f"Defender definitions {d['version']} — {d['signatures']:%d %b %H:%M}", size=11,
                      muted=True).pack(anchor="w", pady=(4, 0))

        self.run(lambda: (shield10.defender(), shield10.other_antivirus()), done)

    def start(self, kind: str, path: str = "") -> None:
        message = shield10.scanner.start(kind, path)
        self.scan_detail.configure(text=message)
        self.tick()

    def start_path(self, folder: bool) -> None:
        path = filedialog.askdirectory(parent=self) if folder else filedialog.askopenfilename(parent=self)
        if path:
            self.start("custom", path)

    def tick(self) -> None:
        running = shield10.scanner.running
        if running:
            elapsed = int(time.time() - running["started"])
            self.scan_state.configure(text=f"⏳ {running['kind'].capitalize()} scan running — {elapsed // 60}:"
                                           f"{elapsed % 60:02d}")
        else:
            last = shield10.scanner.last
            if last:
                verdict = "⚠ threats found" if last["threats"] else "✅ no threats" if last["code"] == 0 else \
                    "didn't finish"
                self.scan_state.configure(text=f"Last {last['kind']} scan: {verdict}")
                if not getattr(self, "_shown_last", None) is last:
                    self._shown_last = last
                    self.fill_history()
            elif not self.scan_state.cget("text"):
                self.scan_state.configure(text="Ready.")

    def fill_history(self) -> None:
        for child in self.history_box.winfo_children():
            child.destroy()
        rows = shield10.AV_SETTINGS.load().get("history", [])
        if not rows:
            label(self.history_box, "No scans from JARVIS yet.", muted=True).pack(anchor="w")
        for r in rows[:10]:
            when = datetime.fromtimestamp(r["started"]).strftime("%d %b %H:%M")
            mark = "⚠" if r["threats"] else "✅" if r["code"] == 0 else "…"
            label(self.history_box, f"{mark} {when}  {r['kind']}{' ' + r['path'] if r.get('path') else ''}  "
                                    f"({int(r['seconds'] // 60)} min)", size=12).pack(anchor="w")

    def save_schedule(self) -> None:
        freq = self.freq.get()
        reply = self.app.jarvis.avschedule_cmd("off" if freq == "off" else f"{freq} {self.at.get().strip()}")
        self.plan_note.configure(text=reply)

    def _said(self, response) -> None:
        self.scan_detail.configure(text=str(getattr(response, "text", response))[:200])
        self.refresh_status()
