"""10.0 automation: if this, then that — inside JARVIS.

An automation is a trigger and a list of steps. Triggers: a time of day, every
N minutes, JARVIS starting, the Wi-Fi network changing, a file landing in a
folder, the battery running low, a program finishing, rain tomorrow, a new
YouTube video, or a phrase you say (a routine). Steps: any JARVIS command,
speak, notify, call a webhook, a Home Assistant service, one of your scripts,
a recorded macro, or wait.

Everything runs while JARVIS is open, on the shared watcher thread; each run
is written to the automation log. "Pause all" stops every automation without
deleting any. Scripts and macros were approved when you saved them, and the
audit log records every run.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import psutil

from .. import alerts, kit, net, security
from ..registry import command, field, split

G = "Automation"
AUTOMATIONS = kit.Store("automations.json", [])
AUTO_STATE = kit.Store("automation_state.json", {"paused": False})
AUTO_LOG = kit.Store("automation_log.json", [])
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TRIGGERS = {
    "time": "At a time of day", "every": "Every few minutes", "start": "When JARVIS starts",
    "wifi": "When the Wi-Fi network changes", "folder": "When a file lands in a folder",
    "battery": "When the battery is low", "program_end": "When a program finishes",
    "rain": "If it will rain tomorrow", "youtube": "When a YouTube channel posts", "phrase": "When I say a phrase",
}
STEPS = {"command": "Run a JARVIS command", "say": "Say something", "notify": "Show a notification",
         "webhook": "Call a webhook (URL)", "ha": "Home Assistant service", "script": "Run one of my scripts",
         "macro": "Play a recorded macro", "wait": "Wait (seconds)", "digest": "My daily digest"}

TEMPLATES = [
    {"name": "Rain tomorrow alert", "trigger": {"type": "rain", "at": "20:00", "chance": 50},
     "steps": [{"type": "notify", "value": "☔ Rain tomorrow ({chance}%) — take an umbrella."}]},
    {"name": "Daily digest", "trigger": {"type": "time", "at": "08:30", "days": "every day"},
     "steps": [{"type": "digest", "value": ""}]},
    {"name": "Good night routine", "trigger": {"type": "phrase", "phrase": "good night"},
     "steps": [{"type": "command", "value": "/media pause"}, {"type": "command", "value": "/volume 20"},
               {"type": "say", "value": "Good night. Sleep well."}]},
    {"name": "Start work routine", "trigger": {"type": "phrase", "phrase": "start work"},
     "steps": [{"type": "command", "value": "/dnd on for 2h"}, {"type": "command", "value": "/mylist"},
               {"type": "notify", "value": "Focus time — notifications muted for 2 hours."}]},
    {"name": "Program finished", "trigger": {"type": "program_end", "program": "ffmpeg.exe"},
     "steps": [{"type": "notify", "value": "✔ {program} finished."}, {"type": "say", "value": "Your job is done."}]},
    {"name": "New downloads", "trigger": {"type": "folder", "folder": str(Path.home() / "Downloads"), "pattern": "*"},
     "steps": [{"type": "notify", "value": "New download: {file}"}]},
    {"name": "Home Wi-Fi", "trigger": {"type": "wifi", "ssid": ""},
     "steps": [{"type": "notify", "value": "Connected to {ssid}."}]},
    {"name": "Battery low", "trigger": {"type": "battery", "below": 15},
     "steps": [{"type": "notify", "value": "🔋 {percent}% left — plug in."}, {"type": "command", "value": "/awake off"}]},
    {"name": "New video from a channel", "trigger": {"type": "youtube", "channel": "@veritasium"},
     "steps": [{"type": "notify", "value": "▶ New video: {title}"}]},
]


def load() -> list[dict]:
    return AUTOMATIONS.load()


def save_all(items: list[dict]) -> None:
    AUTOMATIONS.save(items)


def paused() -> bool:
    return bool(AUTO_STATE.load().get("paused"))


def log(name: str, trigger: str, ok: bool, detail: str) -> None:
    items = AUTO_LOG.load()
    items.insert(0, {"at": time.time(), "name": name, "trigger": trigger, "ok": ok, "detail": detail[:300]})
    AUTO_LOG.save(items[:300])


def describe_trigger(trigger: dict) -> str:
    kind = trigger.get("type")
    if kind == "time":
        return f"at {trigger.get('at', '?')} {trigger.get('days', 'every day')}"
    if kind == "every":
        return f"every {trigger.get('minutes', '?')} min"
    if kind == "wifi":
        return f"on Wi-Fi {trigger.get('ssid') or 'change'}"
    if kind == "folder":
        return f"new file in {Path(trigger.get('folder', '')).name or '?'}"
    if kind == "battery":
        return f"battery below {trigger.get('below', 20)}%"
    if kind == "program_end":
        return f"when {trigger.get('program', '?')} closes"
    if kind == "rain":
        return f"rain tomorrow ≥{trigger.get('chance', 50)}% (checked {trigger.get('at', '20:00')})"
    if kind == "youtube":
        return f"new video on {trigger.get('channel', '?')}"
    if kind == "phrase":
        return f"when you say “{trigger.get('phrase', '')}”"
    return TRIGGERS.get(kind, kind or "?").lower()


DAY_SETS = {"every day": set(range(7)), "weekdays": set(range(5)), "weekends": {5, 6}}


def day_ok(trigger: dict, now: datetime) -> bool:
    days = str(trigger.get("days", "every day")).lower()
    if days in DAY_SETS:
        return now.weekday() in DAY_SETS[days]
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    chosen = {names.index(d[:3]) for d in re.split(r"[,\s]+", days) if d[:3] in names}
    return now.weekday() in chosen if chosen else True


def time_due(trigger: dict, state: dict, now: datetime) -> bool:
    m = re.match(r"(\d{1,2}):(\d{2})", str(trigger.get("at", "")))
    if not m or not day_ok(trigger, now):
        return False
    key = now.date().isoformat()
    if state.get("day") == key:
        return False
    if now.hour * 60 + now.minute >= int(m.group(1)) * 60 + int(m.group(2)):
        if now.hour * 60 + now.minute - (int(m.group(1)) * 60 + int(m.group(2))) <= 30:
            state["day"] = key
            return True
        state["day"] = key            # opened JARVIS long after: don't fire a stale morning routine
    return False


def wifi_ssid() -> str:
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=10,
                             creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    return m.group(1).strip() if m else ""


def youtube_channel_id(channel: str) -> str:
    channel = channel.strip()
    m = re.search(r"(UC[\w-]{22})", channel)
    if m:
        return m.group(1)
    handle = channel if channel.startswith("@") else re.sub(r".*youtube\.com/", "", channel).strip("/")
    url = f"https://www.youtube.com/{handle if handle.startswith(('@', 'c/', 'user/')) else '@' + handle}"
    html = kit.get_text(url, limit=1_500_000)
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html) or re.search(r"channel/(UC[\w-]{22})", html)
    if not m:
        raise kit.KitError(f"Couldn't find the channel {channel}.")
    return m.group(1)


def latest_videos(channel_id: str) -> list[dict]:
    text = kit.get_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ET.fromstring(text.encode("utf-8"))
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = []
    for entry in root.findall("a:entry", ns):
        out.append({"id": entry.findtext("yt:videoId", default="", namespaces=ns),
                    "title": entry.findtext("a:title", default="", namespaces=ns),
                    "url": (entry.find("a:link", ns).get("href") if entry.find("a:link", ns) is not None else "")})
    return out


def rain_tomorrow() -> int | None:
    from .. import weather

    city = weather.home_city()
    if not city:
        return None
    _label, lat, lon = weather.geocode(city)
    data = kit.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "daily": "precipitation_probability_max", "timezone": "auto",
        "forecast_days": 2})
    values = (data.get("daily") or {}).get("precipitation_probability_max") or []
    return int(values[1]) if len(values) > 1 and values[1] is not None else None


# --- Home Assistant -------------------------------------------------------------------------

def ha_request(path: str, body: dict | None = None):
    from ..config import get_setting

    url = get_setting("JARVIS_HA_URL", "").rstrip("/")
    token = get_setting("JARVIS_HA_TOKEN", "")
    if not url or not token:
        raise kit.KitError("Add your Home Assistant URL and token in Settings → Other keys.")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with net.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def ha_call(service: str, entity: str, extra: dict | None = None):
    domain, _, name = service.partition(".")
    if not domain or not name:
        raise kit.KitError("Services look like light.turn_on")
    return ha_request(f"/api/services/{domain}/{name}", {"entity_id": entity, **(extra or {})})


# --- running steps ----------------------------------------------------------------------------

def fill(text: str, context: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(context.get(m.group(1), m.group(0))), text or "")


def run_steps(jarvis, automation: dict, context: dict) -> tuple[bool, str]:
    done: list[str] = []
    for step in automation.get("steps", []):
        kind = step.get("type")
        value = fill(str(step.get("value", "")), context)
        try:
            if kind == "command":
                response = jarvis.process(value if value.startswith("/") else "/" + value)
                done.append(f"{value} → {str(getattr(response, 'text', response))[:80]}")
            elif kind == "say":
                jarvis.voice.speak(value)
                done.append(f"said “{value[:40]}”")
            elif kind == "notify":
                alerts.post(automation.get("name", "Automation"), value, page="automations")
                done.append("notified")
            elif kind == "webhook":
                url, _, payload = value.partition(" ")
                body = json.dumps({"automation": automation.get("name"), **context,
                                   **({"text": payload} if payload else {})}, default=str).encode()
                request = urllib.request.Request(url, data=body, method="POST",
                                                 headers={"Content-Type": "application/json",
                                                          "User-Agent": net.DEFAULT_USER_AGENT})
                with net.urlopen(request, timeout=15) as response:
                    done.append(f"webhook {response.status}")
            elif kind == "ha":
                service, _, entity = value.partition(" ")
                ha_call(service, entity.strip())
                done.append(f"{service} {entity}")
            elif kind == "script":
                path = Path(value.strip().strip('"'))
                if not automation.get("approved_scripts") or str(path) not in automation["approved_scripts"]:
                    raise PermissionError(f"{path.name} wasn't approved for this automation")
                from .coding import run_file

                code, output, _label = run_file(path, timeout=600)
                security.audit.record("automation script", path.name, f"exit {code}")
                done.append(f"{path.name} exit {code}")
            elif kind == "macro":
                from .. import macro

                saved = macro.MACROS.load().get(value)
                if not saved:
                    raise ValueError(f"No macro called {value}")
                finished = threading.Event()
                macro.player.play(saved["events"], on_done=lambda ok: finished.set())
                finished.wait(max(10, saved.get("length", 0) * 2 + 10))
                done.append(f"played {value}")
            elif kind == "wait":
                time.sleep(min(600, float(value or 1)))
            elif kind == "digest":
                text = daily_digest()
                alerts.post("Your day", text, page="today")
                done.append("digest")
        except Exception as exc:
            return False, "; ".join(done + [f"{kind} failed: {exc}"])
    return True, "; ".join(done) or "nothing to do"


def daily_digest() -> str:
    from ..life import CALENDAR
    from .work import load_tasks

    start = datetime.combine(date.today(), datetime.min.time()).timestamp()
    events = [e for e in CALENDAR.load() if start <= e.get("start", 0) < start + 86400]
    tasks = [t for t in load_tasks() if not t.get("done") and (not t.get("due") or t["due"] < start + 86400)]
    bits = [f"{len(events)} event(s)", f"{len(tasks)} task(s)"]
    try:
        from .. import weather

        if weather.home_city():
            first = weather.report("").splitlines()[0]
            bits.append(first.split(":", 1)[-1].strip()[:60])
    except Exception:
        pass
    return " · ".join(bits)


class Engine:
    """Decides which automations are due. Called from the watcher thread."""

    def __init__(self) -> None:
        self.jarvis = None
        self.state: dict[str, dict] = {}
        self.ssid: str | None = None
        self._running: set[str] = set()

    def fire(self, automation: dict, trigger: str, context: dict | None = None) -> None:
        if paused() or not automation.get("enabled", True) or automation["id"] in self._running:
            return
        self._running.add(automation["id"])

        def work():
            try:
                ok, detail = run_steps(self.jarvis, automation, {"time": datetime.now().strftime("%H:%M"),
                                                                 "trigger": trigger, **(context or {})})
                log(automation.get("name", "?"), trigger, ok, detail)
                items = load()
                for item in items:
                    if item["id"] == automation["id"]:
                        item["last_run"] = time.time()
                        item["runs"] = item.get("runs", 0) + 1
                save_all(items)
                if not ok:
                    alerts.post(f"Automation “{automation.get('name')}” failed", detail[-150:], page="automations",
                                kind="warn")
            finally:
                self._running.discard(automation["id"])

        threading.Thread(target=work, daemon=True).start()

    def tick(self) -> None:
        if paused():
            return
        now = datetime.now()
        for automation in load():
            if not automation.get("enabled", True):
                continue
            trigger = automation.get("trigger", {})
            kind = trigger.get("type")
            state = self.state.setdefault(automation["id"], {})
            try:
                if kind == "time" and time_due(trigger, state, now):
                    self.fire(automation, describe_trigger(trigger))
                elif kind == "every":
                    minutes = max(1.0, float(trigger.get("minutes") or 60))
                    if time.time() - state.get("last", time.time() - minutes * 60 + 30) >= minutes * 60:
                        state["last"] = time.time()
                        self.fire(automation, describe_trigger(trigger))
                    state.setdefault("last", time.time())
                elif kind == "battery":
                    b = psutil.sensors_battery()
                    if b is not None:
                        low = not b.power_plugged and b.percent <= float(trigger.get("below") or 20)
                        if low and not state.get("low"):
                            self.fire(automation, describe_trigger(trigger), {"percent": round(b.percent)})
                        state["low"] = low
                elif kind == "program_end":
                    name = str(trigger.get("program", "")).lower()
                    running = any((p.info.get("name") or "").lower() == name for p in psutil.process_iter(["name"]))
                    if state.get("seen") and not running:
                        self.fire(automation, describe_trigger(trigger), {"program": trigger.get("program")})
                    state["seen"] = running
                elif kind == "folder":
                    self._folder(automation, trigger, state)
                elif kind == "rain":
                    if time_due({"at": trigger.get("at", "20:00")}, state, now):
                        chance = rain_tomorrow()
                        if chance is not None and chance >= int(trigger.get("chance") or 50):
                            self.fire(automation, describe_trigger(trigger), {"chance": chance})
                elif kind == "youtube":
                    if time.time() - state.get("checked", 0) >= 1800:
                        state["checked"] = time.time()
                        self._youtube(automation, trigger, state)
            except Exception as exc:
                state["error"] = str(exc)[:200]

    def _folder(self, automation, trigger, state) -> None:
        folder = Path(str(trigger.get("folder", "")))
        if not folder.is_dir():
            return
        pattern = trigger.get("pattern") or "*"
        current = {p.name: p.stat().st_size for p in folder.glob(pattern) if p.is_file() and
                   p.suffix.lower() not in {".crdownload", ".part", ".tmp", ".download"}}
        if "known" not in state:
            state["known"] = current
            return
        for name, size in current.items():
            if name not in state["known"]:
                pending = state.setdefault("pending", {})
                if pending.get(name) == size:
                    state["known"][name] = size
                    pending.pop(name, None)
                    self.fire(automation, describe_trigger(trigger), {"file": name, "folder": str(folder)})
                else:
                    pending[name] = size
        state["known"] = {k: v for k, v in state["known"].items() if k in current}

    def _youtube(self, automation, trigger, state) -> None:
        channel = str(trigger.get("channel", ""))
        if not state.get("channel_id"):
            state["channel_id"] = youtube_channel_id(channel)
        videos = latest_videos(state["channel_id"])
        if not videos:
            return
        seen = set(automation.get("seen_videos", []))
        if not seen:
            items = load()
            for item in items:
                if item["id"] == automation["id"]:
                    item["seen_videos"] = [v["id"] for v in videos]
            save_all(items)
            return
        fresh = [v for v in videos if v["id"] not in seen]
        if fresh:
            items = load()
            for item in items:
                if item["id"] == automation["id"]:
                    item["seen_videos"] = [v["id"] for v in videos]
            save_all(items)
            for video in reversed(fresh[:3]):
                self.fire(automation, describe_trigger(trigger), {"title": video["title"], "url": video["url"]})

    def wifi_tick(self) -> None:
        if paused():
            return
        ssid = wifi_ssid()
        if self.ssid is None:
            self.ssid = ssid
            return
        if ssid != self.ssid:
            self.ssid = ssid
            for automation in load():
                trigger = automation.get("trigger", {})
                if trigger.get("type") == "wifi" and ssid and (not trigger.get("ssid") or
                                                              trigger["ssid"].lower() == ssid.lower()):
                    self.fire(automation, describe_trigger(trigger), {"ssid": ssid})

    def started(self) -> None:
        for automation in load():
            if automation.get("trigger", {}).get("type") == "start":
                self.fire(automation, "JARVIS started")


engine = Engine()


def register_watchers(jarvis, watchers) -> None:
    engine.jarvis = jarvis
    watchers.add("automations", 20, engine.tick, first_after=15)
    watchers.add("wifi", 15, engine.wifi_tick, first_after=8)
    watchers.add("automations-start", 10 ** 9, engine.started, first_after=10)


def new_automation(name: str, trigger: dict, steps: list[dict]) -> dict:
    return {"id": uuid.uuid4().hex[:10], "name": name.strip() or "Automation", "enabled": True, "trigger": trigger,
            "steps": steps, "created": time.time(), "runs": 0, "last_run": 0}


def parse_steps(text: str) -> list[dict]:
    """'/volume 20 ; say Good night ; notify Done' → steps."""
    steps = []
    for part in [p.strip() for p in re.split(r"\s*;\s*|\n", text) if p.strip()]:
        word, _, rest = part.partition(" ")
        low = word.lower()
        if part.startswith("/"):
            steps.append({"type": "command", "value": part})
        elif low in {"say", "notify", "webhook", "ha", "script", "macro", "wait"}:
            steps.append({"type": low, "value": rest.strip()})
        elif low == "digest":
            steps.append({"type": "digest", "value": ""})
        else:
            steps.append({"type": "command", "value": "/" + part})
    return steps


class Automate:
    def match_routine(self, text: str) -> str | None:
        """Run a routine if `text` is one of its phrases (called for every plain message)."""
        if len(text) > 60 or paused():
            return None
        said = re.sub(r"[^\w\s]", "", text.lower()).strip()
        for automation in load():
            trigger = automation.get("trigger", {})
            if trigger.get("type") != "phrase" or not automation.get("enabled", True):
                continue
            phrases = [p.strip().lower() for p in str(trigger.get("phrase", "")).split("|") if p.strip()]
            if said in {re.sub(r"[^\w\s]", "", p) for p in phrases} or said in {f"jarvis {p}" for p in phrases}:
                ok, detail = run_steps(self, automation, {"time": datetime.now().strftime("%H:%M")})
                log(automation["name"], f"phrase “{said}”", ok, detail)
                return f"⚙ {automation['name']}: " + ("done." if ok else f"stopped — {detail[-120:]}")
        return None

    @command("routine", group=G, usage="/routine <phrase> | <steps: /volume 20 ; say Good night ; notify Done>",
             help="a phrase that runs several steps — say or type it", title="Routines", icon="🪄", page="automations",
             fields=(field("phrase", "text", "When I say", "good night"),
                     field("steps", "long", "Do these (one per line or ;)",
                           hint="/media pause\n/volume 20\nsay Good night")))
    def routine_cmd(self, args: str, routed: bool = False):
        phrase, steps_text = split(args, 2)
        if not phrase or not steps_text:
            names = [f"  “{a['trigger'].get('phrase')}” → {len(a['steps'])} step(s)" for a in load()
                     if a.get("trigger", {}).get("type") == "phrase"]
            return ("🪄 Routines:\n" + "\n".join(names)) if names else \
                "Usage: /routine good night | /media pause ; /volume 20 ; say Good night"
        steps = parse_steps(steps_text)
        items = load()
        items.append(new_automation(phrase.capitalize(), {"type": "phrase", "phrase": phrase.lower()}, steps))
        save_all(items)
        return f"🪄 Say or type “{phrase}” and I'll do {len(steps)} step(s)."

    @command("automation", "automations", "auto", group=G,
             usage="/automation list · /automation run <name> · /automation on|off <name> · /automation delete <name> · /automation pause|resume",
             help="your automations: list, run now, switch on/off, pause all", title="Automations", icon="⚙",
             page="automations", fields=(field("action", "choice", "Action", "list", ("list", "run", "on", "off",
                                                                                      "delete", "pause", "resume")),
                                         field("name", "text", "Name", optional=True)), template="{action} {name}")
    def automation_cmd(self, args: str, routed: bool = False):
        verb, _, name = args.strip().partition(" ")
        verb = (verb or "list").lower()
        items = load()
        if verb in {"pause", "resume"}:
            AUTO_STATE.save({"paused": verb == "pause"})
            return "⏸ All automations paused." if verb == "pause" else "▶ Automations running again."
        if verb == "list":
            if not items:
                return "No automations yet. Make one on the Automations page, or /routine for a phrase."
            head = "⏸ paused — " if paused() else ""
            return f"⚙ {head}{len(items)} automation(s):\n" + "\n".join(
                f"  {'●' if a.get('enabled', True) else '○'} {a['name']} — {describe_trigger(a['trigger'])}, "
                f"{len(a['steps'])} step(s), ran {a.get('runs', 0)}×" for a in items)
        target = next((a for a in items if a["name"].lower() == name.strip().lower()), None) or \
            next((a for a in items if name.strip().lower() in a["name"].lower()), None) if name.strip() else None
        if target is None:
            return f"No automation called {name.strip() or '?'}."
        if verb == "run":
            ok, detail = run_steps(self, target, {"time": datetime.now().strftime("%H:%M"), "trigger": "by hand"})
            log(target["name"], "by hand", ok, detail)
            return f"⚙ {target['name']}: " + ("done — " if ok else "failed — ") + detail
        if verb in {"on", "off"}:
            target["enabled"] = verb == "on"
            save_all(items)
            return f"⚙ {target['name']} is {verb}."
        if verb in {"delete", "remove"}:
            save_all([a for a in items if a is not target])
            return f"Deleted {target['name']}."
        return "Usage: /automation list|run|on|off|delete <name> · /automation pause|resume"

    @command("autolog", group=G, usage="/autolog", help="what your automations did, newest first",
             title="Automation log", icon="📜", page="automations")
    def autolog_cmd(self, args: str, routed: bool = False):
        items = AUTO_LOG.load()
        if not items:
            return "Nothing has run yet."
        return "📜 Automation log:\n" + "\n".join(
            f"  {datetime.fromtimestamp(i['at']):%d %b %H:%M}  {'✔' if i['ok'] else '✘'} {i['name']} ({i['trigger']}) — "
            f"{i['detail'][:90]}" for i in items[:40])

    @command("webhook", group=G, usage="/webhook <url> [message]", help="calls a webhook (POST, JSON)",
             title="Call a webhook", icon="🪝", page="automations",
             fields=(field("url", "text", "URL", hint="https://…"), field("message", "text", "Message", optional=True)),
             template="{url} {message}")
    def webhook_cmd(self, args: str, routed: bool = False):
        url, _, message = args.strip().partition(" ")
        if not url.startswith(("http://", "https://")):
            return "Usage: /webhook https://… [message]"
        ok, detail = run_steps(self, {"name": "webhook", "steps": [{"type": "webhook", "value": f"{url} {message}"}]},
                               {"time": datetime.now().strftime("%H:%M")})
        return ("🪝 " if ok else "⚠ ") + detail

    @command("ha", "homeassistant", group=G, usage="/ha [filter] · /ha <entity> on|off|toggle · /ha call <domain.service> <entity>",
             help="your Home Assistant: see and switch lights, plugs and more", title="Home Assistant", icon="🏠",
             page="automations", fields=(field("what", "text", "Entity and on/off, or a filter", optional=True,
                                               hint="light.kitchen toggle"),))
    def ha_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        try:
            if text.lower().startswith("call "):
                _, service, entity = (text.split(None, 2) + ["", ""])[:3]
                ha_call(service, entity)
                return f"🏠 Called {service} on {entity}."
            m = re.match(r"([a-z_]+\.[\w]+)\s+(on|off|toggle)$", text.lower())
            if m:
                entity, action = m.groups()
                domain = entity.split(".")[0]
                service_domain = domain if domain in {"light", "switch", "fan", "cover", "climate", "media_player",
                                                      "input_boolean", "script", "automation"} else "homeassistant"
                ha_call(f"{service_domain}.turn_{action}" if action != "toggle" else f"{service_domain}.toggle", entity)
                return f"🏠 {entity}: {action}."
            states = ha_request("/api/states")
        except (kit.KitError, OSError, ValueError) as exc:
            return f"Home Assistant: {exc}"
        words = text.lower().split()
        rows = [s for s in states if s.get("entity_id", "").split(".")[0] in {"light", "switch", "fan", "cover",
                                                                               "climate", "sensor", "binary_sensor",
                                                                               "media_player", "lock"}
                and all(w in (s["entity_id"] + " " + str(s.get("attributes", {}).get("friendly_name", ""))).lower()
                        for w in words)]
        return f"🏠 {len(rows)} entities:\n" + "\n".join(
            f"  {s['entity_id']:<36} {s.get('state')}  {s.get('attributes', {}).get('friendly_name', '')}"
            for s in rows[:60])
