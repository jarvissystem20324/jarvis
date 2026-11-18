"""13.4.2: Cowork from the chat, the smart router's readout, your form profile,
and questions across a folder of company documents."""

from __future__ import annotations

import re
from pathlib import Path

from .. import cowork, router
from ..registry import command, field, split_free

G = "Cowork"


class CoworkCommands:
    @command("cowork", "jobs", "job", group=G, usage="/cowork <job> · /cowork · /cowork stop|undo|open <n>",
             help="a background job: folder reports, inbox triage, form filling, research — with a plan, live "
                  "progress and Stop", title="Cowork job", icon="🧰", page="today",
             fields=(field("job", "long", "The job, in plain words",
                           hint="compare the PDFs in C:\\Offers · sort my inbox · research … · fill https://… "
                                "from my CV"),),
             keywords="agent background task automate folder inbox form research")
    def cowork_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        number = re.search(r"\d+", rest or "")
        if not text or text.lower() in {"list", "jobs", "history", "status"}:
            return cowork.manager.describe()
        if verb.lower() in {"stop", "cancel", "undo", "open", "show"} and number:
            job_id = int(number.group())
            if verb.lower() in {"stop", "cancel"}:
                return cowork.manager.stop(job_id)
            if verb.lower() == "undo":
                return cowork.manager.undo(job_id)
            return self._cowork_show(job_id)
        try:
            job = cowork.manager.start(text)
        except cowork.JobError as exc:
            return str(exc)
        return (f"🧰 Cowork job #{job.id} started — {job.label()}: {text[:120]}\n"
                "It runs in the background; follow it in the Cowork panel beside the chat. "
                f"/cowork stop {job.id} stops it.")

    def _cowork_show(self, job_id: int) -> str:
        job = cowork.manager.get(job_id)
        if job is None:
            return f"No job #{job_id}."
        lines = [f"🧰 #{job.id} {job.label()} — {job.title} ({job.status})"]
        lines += [f"  {'✓' if s.status == 'done' else '✗' if s.status == 'failed' else '·'} {s.title}"
                  + (f" — {s.detail}" if s.detail else "") for s in job.steps]
        if job.result:
            lines += ["", job.result]
        if job.error:
            lines += ["", f"Problem: {job.error}"]
        if job.outputs:
            lines += ["", "Files:"] + [f"  {p}" for p in job.outputs]
        return "\n".join(lines)

    @command("profile", "myprofile", group=G, usage="/profile · /profile <field> = <value> · /profile fromcv <file> · "
             "/profile clear", help="your details for Cowork's form filler (kept sealed on this PC)",
             title="My details for forms", icon="🪪", page="today",
             fields=(field("detail", "text", "Field = value", hint="email = you@mail.com · phone = 0555 … · "
                           "school = …"),))
    def profile_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        data = cowork.PROFILE.load()
        if text.lower() in {"clear", "forget", "reset"}:
            cowork.PROFILE.save({})
            return "🪪 Forgot your form details."
        if text.lower().startswith(("fromcv", "from cv", "cv ")):
            path = Path(re.sub(r"^(from\s*cv|cv)\s*", "", text, flags=re.I).strip().strip('"'))
            if not path.is_file():
                return "Usage: /profile fromcv C:\\path\\to\\cv.pdf"
            from .. import security

            if not security.permissions.ask(security.READ_FILE, str(path), context="/profile"):
                return "Denied. The CV was not read."
            found = cowork.profile_from_text(self.brain, cowork.file_text(path, 15000))
            if not found:
                return "I couldn't read any details from that CV."
            data.update(found)
            cowork.PROFILE.save(data)
            return f"🪪 Read {len(found)} detail(s) from {path.name}: {', '.join(found)}. /profile shows them."
        if "=" in text:
            key, _, value = text.partition("=")
            key = key.strip().lower()
            if re.search(r"password|şifre|card|kart|iban|cvv|kimlik|tc no", key):
                return "Cowork never stores passwords, card numbers or ID numbers — forms like that are yours to fill."
            if value.strip():
                data[key] = value.strip()
            else:
                data.pop(key, None)
            cowork.PROFILE.save(data)
            return f"🪪 {key}: {value.strip() or '(removed)'}"
        if not data:
            return ("🪪 No details yet. Add them one at a time — /profile full name = Ada Yılmaz · /profile email = "
                    "ada@mail.com — or read them from your CV: /profile fromcv C:\\…\\cv.pdf.\n"
                    "Cowork never stores passwords, card or ID numbers.")
        return "🪪 Your details for forms:\n" + "\n".join(f"  {k}: {v}" for k, v in data.items()) + \
            "\n/profile <field> = (blank) removes one · /profile clear"

    @command("router", "smartrouter", group=G, usage="/router [on|off|reset]",
             help="the smart router: the cheapest model that can do each message, and what it saved",
             title="Smart router", icon="🧭", page="memory",
             fields=(field("action", "choice", "Show", "savings", ("savings", "on", "off", "reset")),),
             keywords="cost savings models cheapest")
    def router_cmd(self, args: str, routed: bool = False):
        word = args.strip().lower()
        if word in {"on", "off"}:
            self._write_setting(router.SETTING, word)
        elif word == "reset":
            router.reset()
        return router.readout()

    @command("askdocs", "companydocs", "askfolder", group=G, usage="/askdocs <folder> | <question>",
             help="ask a question across a folder of documents (PDF, Word, Excel, PowerPoint) — answered with "
                  "sources", title="Ask company documents", icon="🗂", page="documents",
             fields=(field("folder", "folder", "Folder (blank: the last one)", optional=True),
                     field("question", "long", "Question")),
             keywords="company documents knowledge base sources library search")
    def askdocs_cmd(self, args: str, routed: bool = False):
        folder, question = split_free(args, 2)
        folder = folder.strip().strip('"')
        if folder and not question and not Path(folder).expanduser().is_dir():
            folder, question = "", folder
        reply = ""
        if folder:
            if not Path(folder).expanduser().is_dir():
                return f"There's no folder at {folder}."
            reply = self.docs(folder)
            if not question:
                return reply
        if not question.strip():
            return self.docs("")
        answer = self.docs(question)
        return (reply.split("\n\nAsk with")[0] + "\n\n" if reply else "") + answer
