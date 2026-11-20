"""The Bounty update's commands: Memory 2.0, Focus mode 2.0, Build it live,
Image Studio upscaling and the proactive briefings."""

from __future__ import annotations

from pathlib import Path

from .. import kit
from ..registry import command, field

G = "Productivity"


class Bounty:
    @command("knowledge", "kb", "mine", group="Chat and AI", usage="/knowledge <question>",
             help="Memory 2.0: one answer from everything — your chats, notes, pins, memory and indexed documents, "
                  "with sources", title="Ask everything I know", icon="🧠", page="memory",
             fields=(field("question", "long", "Question", hint="what did we decide about the club budget?"),),
             keywords="memory search everything notes chats sources")
    def knowledge_cmd(self, args: str, routed: bool = False):
        from .. import kb

        question = args.strip()
        if not question:
            counts = kb.counts()
            parts = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "nothing yet"
            return f"🧠 I can search: {parts}.\nAsk with /knowledge <question>."
        return kb.answer(self.brain, question)

    @command("focus", group=G, usage="/focus start [minutes] · /focus stop · /focus stats · "
             "/focus sites|apps add|remove <name>", help="Focus mode 2.0: Pomodoro blocks that minimise distracting "
             "sites and apps, with stats", title="Focus mode", icon="🎯", page="today",
             fields=(field("action", "choice", "Action", "start", ("start", "stop", "status", "stats")),
                     field("minutes", "number", "Focus minutes", "25", optional=True)),
             keywords="pomodoro block distraction concentrate study timer")
    def focus_cmd(self, args: str, routed: bool = False):
        from .. import alerts, focus

        words = args.strip().split()
        verb = (words[0].lower() if words else "status")
        engine = focus.focus
        engine.notify = lambda title, body: alerts.post(title, body, page="today")
        if verb in {"start", "on", "begin", "başlat"}:
            minutes = kit.whole(words[1] if len(words) > 1 else "", 25, 5, 120)
            return engine.start(minutes, 5 if minutes <= 30 else 10)
        if verb in {"stop", "off", "end"}:
            return engine.stop()
        if verb == "stats":
            return focus.stats_text()
        if verb in {"sites", "apps"} and len(words) >= 3:
            return focus.edit_list(verb, words[1].lower(), " ".join(words[2:]))
        if verb in {"sites", "apps"}:
            return f"🎯 Blocked {verb}: " + ", ".join(focus.lists()[verb])
        return engine.status()

    @command("buildlive", "livebuild", "buildit", group="Make and write", usage="/buildlive <your idea>",
             help="Build it live: an idea becomes a website with a working mini app, shared on your Wi-Fi with a "
                  "QR code", title="Build it live", icon="⚡", page="tools",
             fields=(field("idea", "long", "The idea", hint="a site for our robotics club with a quiz"),),
             keywords="website app qr demo stage present live")
    def buildlive_cmd(self, args: str, routed: bool = False):
        from .. import buildlive
        from ..assistant import JarvisResponse

        idea = args.strip()
        if idea.lower() in {"stop", "off"}:
            return buildlive.live.stop()
        try:
            site = buildlive.build(self.brain, idea)
            page = site / "index.html"
            try:
                url = buildlive.live.share(site)
            except buildlive.LiveError as exc:
                return str(exc)
            code = buildlive.qr(url, site)
        except buildlive.LiveError as exc:
            return str(exc)
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
        return JarvisResponse(
            text=(f"⚡ Built and live: {url}\nScan the code with a phone on the same Wi-Fi.\nSaved: {page}\n"
                  "/buildlive stop stops sharing."),
            image_path=code, image_paths=[code])

    @command("upscale", group="Make and write", usage="/upscale [2|4] [image file]",
             help="Image Studio: a 2× or 4× bigger copy of the last picture, made on this PC",
             title="Upscale a picture", icon="🔍", page="media",
             fields=(field("factor", "choice", "Size", "2", ("2", "4")),
                     field("image", "file", "Picture (blank: the last one)", optional=True)),
             keywords="image bigger resolution enlarge")
    def upscale_cmd(self, args: str, routed: bool = False):
        from .. import images
        from ..assistant import JarvisResponse

        words = args.strip().split(maxsplit=1)
        factor = 2
        if words and words[0] in {"2", "4", "2x", "4x"}:
            factor = int(words[0][0])
            words = words[1:]
        source = Path(words[0].strip('"')) if words else getattr(self, "current_image", None)
        if source is None or not Path(source).is_file():
            return "Make or open a picture first, or give one: /upscale 2 C:\\…\\picture.png"
        path = images.upscale(Path(source), factor)
        self.current_image = path
        return JarvisResponse(text=f"🔍 Upscaled {factor}× → {path}", image_path=path, image_paths=[path])

    @command("analyze", "analyse", "imageanalysis", group="Chat and AI", usage="/analyze [image] | [question]",
             help="image analysis: what's in a picture, its text, what matters (charts, forms, errors) — and your "
                  "question answered", title="Analyse an image", icon="🔍", page="media",
             fields=(field("image", "file", "Picture (blank: the last one)", optional=True),
                     field("question", "text", "Question (optional)", optional=True,
                           hint="what does this chart show? · what's wrong here?")),
             keywords="image picture photo analyse vision describe screenshot chart")
    def analyze_cmd(self, args: str, routed: bool = False):
        from .. import vision
        from ..assistant import JarvisResponse
        from ..registry import split_free

        target, question = split_free(args, 2)
        target = target.strip().strip('"')
        path = Path(target) if target and Path(target).is_file() else None
        if path is None:
            question = f"{target} {question}".strip() if target else question
            path = getattr(self, "current_image", None)
        if path is None or not Path(path).is_file():
            return "Give me a picture: press + next to the message box, drop one in, or /analyze C:\\…\\photo.jpg"
        try:
            text = vision.analyse(self.brain, Path(path), question)
        except vision.VisionError as exc:
            return str(exc)
        self.current_image = Path(path)
        return JarvisResponse(text=text, image_path=Path(path), image_paths=[Path(path)])

    @command("nudges", "briefings", group=G, usage="/nudges [on|off]",
             help="proactive briefings: at most three useful nudges a day, never at night",
             title="Proactive nudges", icon="💡", page="today",
             fields=(field("state", "choice", "Turn", "on", ("on", "off")),))
    def nudges_cmd(self, args: str, routed: bool = False):
        from .. import nudges

        word = args.strip().lower()
        if word in {"on", "off"}:
            self._write_setting("JARVIS_NUDGES", word)
        return (f"💡 Nudges are {'on' if nudges.enabled() else 'off'}: at most {nudges.per_day()} a day, two hours "
                "apart, never between 22:00 and 08:00 or during focus mode. They come from your own to-dos and "
                "focus time — nothing is sent anywhere to decide.")
