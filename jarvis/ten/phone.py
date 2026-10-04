"""10.0 phone and devices: the phone link (chat, files and clipboard from the
phone's browser), casting to a TV, and smart plugs. The logic is in
jarvis/phonelink.py, jarvis/dlna.py and jarvis/kasa.py."""

from __future__ import annotations

import mimetypes

from .. import kit
from ..registry import command, field, split

G = "Phone"
_tvs: list[dict] = []


def stop_server() -> None:
    from .. import phonelink

    phonelink.link.stop()


def register_watchers(jarvis, watchers) -> None:
    """Start the phone link with JARVIS when Settings say so (JARVIS_PHONE_LINK=on)."""
    from .. import phonelink
    from ..config import get_setting

    if get_setting("JARVIS_PHONE_LINK", "off").strip().lower() in {"on", "1", "true", "yes"}:
        try:
            phonelink.link.start(jarvis)
        except OSError:
            pass


class Phone:
    @command("phone", "phonelink", group=G, usage="/phone [on|off]",
             help="use JARVIS from your phone's browser: chat, send photos and files, swap clipboards",
             title="Phone link", icon="📱", page="phone",
             fields=(field("state", "choice", "Phone link", "on", ("on", "off")),))
    def phone_cmd(self, args: str, routed: bool = False):
        from .. import phonelink
        from ..assistant import JarvisResponse

        word = args.strip().lower()
        if word == "off":
            phonelink.link.stop()
            return "📱 Phone link off."
        if word != "on" and not phonelink.link.running:
            return JarvisResponse(text="📱 The phone link is off. /phone on starts it (your phone needs to be on "
                                       "the same Wi-Fi).", open_page="phone")
        if not phonelink.link.running:
            try:
                phonelink.link.start(self)
            except OSError as exc:
                return f"📱 {exc}"
        return JarvisResponse(text=f"📱 Phone link on. Scan the QR code on the Phone page with your phone (same "
                                   f"Wi-Fi), or open {phonelink.link.url()} on it. If Windows asks, allow JARVIS on "
                                   "private networks.", open_page="phone")

    @command("cast", group=G, usage="/cast <video, music or photo> [| TV name] · /cast stop",
             help="plays a file from this PC on your TV (DLNA)", title="Cast to TV", icon="📺", page="phone",
             fields=(field("file", "file", "Video, music or photo"), field("tv", "text", "TV", optional=True)))
    def cast_cmd(self, args: str, routed: bool = False):
        global _tvs
        from .. import dlna, phonelink

        path_text, tv = split(args, 2)
        if path_text.strip().lower() in {"stop", "pause"}:
            if not _tvs:
                return "📺 Nothing is casting."
            try:
                (dlna.stop if path_text.strip().lower() == "stop" else dlna.pause)(_tvs[0])
            except dlna.CastError as exc:
                return f"📺 {exc}"
            return "📺 Stopped." if path_text.strip().lower() == "stop" else "📺 Paused."
        path = kit.path_arg(path_text)
        if path is None or not path.is_file():
            return "Usage: /cast C:/Videos/holiday.mp4 [| living room TV]"
        devices = dlna.discover()
        if not devices:
            return "📺 No TV answered. Is it on, on the same network, with screen sharing/DLNA enabled?"
        chosen = [d for d in devices if tv.strip().lower() in d["name"].lower()] if tv.strip() else devices
        if not chosen:
            return "📺 TVs found: " + ", ".join(d["name"] for d in devices)
        try:
            if not phonelink.link.running:
                phonelink.link.start(self)
            mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
            dlna.play(chosen[0], phonelink.link.cast_url(path), path.stem, mime)
        except (OSError, dlna.CastError) as exc:
            return f"📺 {exc}"
        _tvs = [chosen[0]]
        return f"📺 Playing {path.name} on {chosen[0]['name']}. /cast stop to stop."

    @command("plugs", "plug", group=G, usage="/plugs · /plugs on <name> · /plugs off <name>",
             help="finds TP-Link Kasa smart plugs and switches them", title="Smart plugs", icon="🔌", page="phone",
             fields=(field("action", "choice", "Switch", "on", ("on", "off")), field("name", "text", "Plug")),
             template="{action} {name}")
    def plugs_cmd(self, args: str, routed: bool = False):
        from .. import kasa, security

        verb, _, name = args.strip().partition(" ")
        plugs = kasa.discover()
        if not plugs:
            return ("🔌 No Kasa plugs answered. They need to be on this network; Tapo plugs and the newest Kasa "
                    "firmware only work through TP-Link's app.")
        if verb.lower() in {"on", "off", "aç", "kapat"}:
            on = verb.lower() in {"on", "aç"}
            targets = [p for p in plugs if name.strip().lower() in p["name"].lower()] if name.strip() else []
            if not targets:
                return "🔌 Which plug? " + ", ".join(p["name"] for p in plugs)
            if not security.permissions.ask(security.RUN_COMMAND, f"turn {'on' if on else 'off'} "
                                                                  f"{targets[0]['name']}", context="/plugs"):
                return "Left as it was."
            try:
                ok = kasa.set_power(targets[0]["ip"], on)
            except OSError as exc:
                return f"🔌 {targets[0]['name']} didn't answer: {exc}"
            return f"🔌 {targets[0]['name']} is {'on' if on else 'off'}." if ok else "🔌 The plug refused."
        return "🔌 Plugs:\n" + "\n".join(f"  {'🟢' if p['on'] else '⚪'} {p['name']} ({p['model']}, {p['ip']})"
                                        for p in plugs)
