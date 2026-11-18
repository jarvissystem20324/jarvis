"""Cowork (13.4.2): describe a job, JARVIS plans it and does it in the background.

A job is a goal in plain words — "compare the 40 PDFs in my Offers folder",
"sort my inbox and draft replies", "fill this application form from my CV",
"research student laptops under 30,000 TL with sources". It runs on its own
thread while you keep using JARVIS, shows its plan and each step as it goes,
and can be stopped at any time.

Five kinds of job:

    folder    read every document in a folder → a comparison spreadsheet
              and a one-page report
    inbox     sort recent email, summarise, and draft replies in your tone
              (drafts only: nothing is ever sent for you)
    form      fill a web form from your profile or CV, with the screen's
              eyes and hands (never presses Submit — that stays yours)
    research  search the web, read the pages, write a sourced document
    general   anything else: a planner splits it into steps, a worker does
              them, and the result is a document

The rules every job keeps:
  • It asks before it reads your files or email, or touches the screen.
  • It only ever creates new files, in JARVIS's own output folder; "undo"
    deletes exactly the files that job made (after asking).
  • Material it reads is treated as data, never as instructions (shield).
  • Stop always works: checked between every step and every file.

The planner is Groq's gpt-oss-120b; the screen is read by NVIDIA's Nemotron
3.5 VL (the user's choice for PC tasks), with Gemini as the backup. Both are
only the first choice: the usual provider chain stands behind them.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import kit, library, providers, security, shield

KINDS = ("folder", "inbox", "form", "research", "general")
KIND_LABELS = {"folder": "Folder report", "inbox": "Inbox triage", "form": "Form filler",
               "research": "Research", "general": "Job"}

PLANNER = (("groq", "openai/gpt-oss-120b"),)
MAX_FILES = 120
MAX_FILE_CHARS = 12_000
MAX_SOURCES = 8
MAX_FORM_SCREENS = 3
HISTORY_LIMIT = 40


def vision_targets() -> tuple[tuple[str, str], ...]:
    return (("nvidia", providers.NVIDIA.vision_model or ""), ("gemini", providers.model_for(providers.GEMINI)))


class JobError(Exception):
    """Something the user should read: why the job could not go on."""


class Stopped(Exception):
    """The user pressed Stop."""


@dataclass
class Step:
    title: str
    status: str = "waiting"        # waiting · running · done · failed · skipped
    detail: str = ""


@dataclass
class Job:
    id: int
    goal: str
    kind: str
    title: str = ""
    status: str = "planning"       # planning · running · done · failed · stopped
    steps: list[Step] = field(default_factory=list)
    progress: float = 0.0
    outputs: list[str] = field(default_factory=list)
    result: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    extra: dict = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def running(self) -> bool:
        return self.status in {"planning", "running"}

    def label(self) -> str:
        return KIND_LABELS.get(self.kind, "Job")

    def as_dict(self) -> dict:
        return {"id": self.id, "goal": self.goal, "kind": self.kind, "title": self.title, "status": self.status,
                "steps": [[s.title, s.status, s.detail] for s in self.steps], "progress": self.progress,
                "outputs": self.outputs, "result": self.result[:4000], "error": self.error, "started": self.started,
                "finished": self.finished, "extra": {k: v for k, v in self.extra.items() if k in {"drafts"}}}

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        job = cls(int(data.get("id", 0)), str(data.get("goal", "")), str(data.get("kind", "general")))
        job.title = str(data.get("title", ""))
        job.status = str(data.get("status", "done"))
        job.steps = [Step(*row[:3]) for row in data.get("steps") or [] if isinstance(row, list) and len(row) >= 2]
        job.progress = float(data.get("progress") or 0)
        job.outputs = [str(p) for p in data.get("outputs") or []]
        job.result = str(data.get("result", ""))
        job.error = str(data.get("error", ""))
        job.started = float(data.get("started") or 0)
        job.finished = float(data.get("finished") or 0)
        job.extra = dict(data.get("extra") or {})
        if job.status in {"planning", "running"}:
            job.status = "stopped"   # JARVIS was closed while it ran
        return job


# --- understanding the request ---------------------------------------------------------

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_WIN_PATH = re.compile(r"[\"']?([A-Za-z]:[\\/][^\"'\n|<>*?]*)[\"']?")
_FORM = re.compile(r"\b(fill|form|application|apply|doldur|başvuru formu|formu)\b", re.I)
_INBOX = re.compile(r"\b(inbox|e-?mails?|mail|gmail|outlook|e-?posta|gelen kutu\w*|maillerim\w*)\b", re.I)
_FOLDER = re.compile(r"\b(folder|directory|pdfs?|files|documents|invoices|offers|cvs|klasör\w*|dosyalar\w*|"
                     r"belgeler\w*)\b", re.I)
_REPORT = re.compile(r"\b(compare|comparison|summar\w*|report|table|spreadsheet|excel|extract|list|"
                     r"karşılaştır\w*|özet\w*|rapor\w*|tablo\w*)\b", re.I)
_RESEARCH = re.compile(r"\b(research|find out|look up|sources?|investigate|search the web|best|vs\.?|versus|"
                       r"araştır\w*|kaynak\w*|en iyi)\b", re.I)
_KNOWN_FOLDERS = {"desktop": "Desktop", "masaüstü": "Desktop", "downloads": "Downloads", "indirilenler": "Downloads",
                  "documents": "Documents", "belgelerim": "Documents", "pictures": "Pictures", "resimler": "Pictures"}


def find_url(goal: str) -> str:
    match = _URL.search(goal or "")
    return match.group(0).rstrip(".,);") if match else ""


def find_paths(goal: str) -> list[Path]:
    out = []
    for match in _WIN_PATH.finditer(goal or ""):
        raw = match.group(1).strip().rstrip(".,;")
        # A path may run into the next words ("C:\Offers and make a table"): try shorter.
        words = raw.split(" ")
        for cut in range(len(words), 0, -1):
            candidate = Path(" ".join(words[:cut]).rstrip(".,;"))
            if candidate.exists():
                out.append(candidate)
                break
    return out


def find_folder(goal: str) -> Path | None:
    for path in find_paths(goal):
        if path.is_dir():
            return path
    low = (goal or "").lower()
    for word, name in _KNOWN_FOLDERS.items():
        if re.search(rf"\b{word}\b", low):
            candidate = Path.home() / name
            if candidate.is_dir():
                return candidate
    return None


def find_file(goal: str, suffixes: set[str]) -> Path | None:
    for path in find_paths(goal):
        if path.is_file() and path.suffix.lower() in suffixes:
            return path
    return None


def detect_kind(goal: str) -> str:
    text = goal or ""
    if _FORM.search(text) and (find_url(text) or re.search(r"\bform", text, re.I)):
        return "form"
    if _INBOX.search(text):
        return "inbox"
    if find_folder(text) is not None or (_FOLDER.search(text) and _REPORT.search(text)):
        return "folder"
    if _RESEARCH.search(text) or text.rstrip().endswith("?"):
        return "research"
    return "general"


# --- the profile the form filler uses -----------------------------------------------------

PROFILE = kit.Store("cowork_profile.json", {})

PROFILE_FIELDS = ("full name", "first name", "last name", "email", "phone", "date of birth", "address", "city",
                  "country", "postcode", "school", "department", "graduation year", "gpa", "current job",
                  "linkedin", "github", "website", "languages", "skills", "about me")


def load_profile() -> dict:
    data = PROFILE.load()
    return {str(k): str(v) for k, v in data.items() if str(v).strip()}


def profile_from_text(brain, text: str) -> dict:
    """The details a form asks for, read out of a CV."""
    wrapped, _ = shield.wrap(text[:15000], "a CV")
    data = kit.ask_json(brain, (
        f"{shield.RULE}\nRead this CV and return the person's details as one flat JSON object with these keys "
        f"when present: {', '.join(PROFILE_FIELDS)}. Values are short strings copied from the CV; leave out "
        f"anything it does not say. Never invent.\n\n{wrapped}"))
    return {str(k): str(v) for k, v in data.items() if isinstance(data, dict) and str(v).strip()} \
        if isinstance(data, dict) else {}


# --- reading files ------------------------------------------------------------------------

def readable(path: Path) -> bool:
    return path.suffix.lower() in library.READABLE | {".png", ".jpg", ".jpeg"}


def list_files(folder: Path, limit: int = MAX_FILES) -> list[Path]:
    found = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and readable(path) and not path.name.startswith(("~$", ".")):
            found.append(path)
            if len(found) >= limit:
                break
    return found


def file_text(path: Path, limit: int = MAX_FILE_CHARS) -> str:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        try:
            from . import ocr

            return ocr.read_image(path)[:limit] if ocr.available() else ""
        except Exception:
            return ""
    return library.document_text(path, limit)


def mailto(draft: dict) -> str:
    query = urllib.parse.urlencode({"subject": draft.get("subject", ""), "body": draft.get("body", "")},
                                   quote_via=urllib.parse.quote)
    return f"mailto:{urllib.parse.quote(draft.get('to', ''), safe='@.+-_')}?{query}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def out_path(title: str, suffix: str) -> Path:
    return _unique(kit.output_dir("cowork") / f"{kit.slug(title, 50)}_{kit.stamp()}{suffix}")


# --- the runner -----------------------------------------------------------------------------

class Context:
    """What a job may use. Tests swap any of these out."""

    def __init__(self, job: Job, manager: "Manager", brain) -> None:
        self.job, self.manager, self.brain = job, manager, brain

    # progress
    def plan(self, *titles: str) -> None:
        self.job.steps = [Step(t) for t in titles]
        self.job.status = "running"
        self.changed()

    def step(self, index: int, status: str = "running", detail: str = "") -> None:
        self.check()
        if 0 <= index < len(self.job.steps):
            step = self.job.steps[index]
            step.status = status
            if detail or status == "running":
                step.detail = detail
        done = sum(s.status in {"done", "skipped"} for s in self.job.steps)
        self.job.progress = done / max(1, len(self.job.steps))
        self.changed()

    def note(self, index: int, detail: str, fraction: float | None = None) -> None:
        self.check()
        if 0 <= index < len(self.job.steps):
            self.job.steps[index].detail = detail
        if fraction is not None and self.job.steps:
            done = sum(s.status in {"done", "skipped"} for s in self.job.steps)
            self.job.progress = (done + max(0.0, min(1.0, fraction))) / len(self.job.steps)
        self.changed()

    def changed(self) -> None:
        self.manager.notify(self.job)

    def check(self) -> None:
        if self.job.stop_event.is_set():
            raise Stopped()

    def wait(self, seconds: float) -> None:
        if self.job.stop_event.wait(seconds):
            raise Stopped()

    # asking
    def allow(self, capability, detail: str) -> None:
        if not security.permissions.ask(capability, detail, context=f"Cowork job #{self.job.id}"):
            raise JobError("You said no, so the job stopped. Nothing was read or changed.")

    def ask(self, prompt: str, **kwargs) -> str:
        self.check()
        return self.brain.ask_once(prompt, **kwargs)

    def ask_json(self, prompt: str, **kwargs):
        self.check()
        try:
            return kit.ask_json(self.brain, prompt, **kwargs)
        except kit.KitError as exc:
            raise JobError(str(exc)) from None

    def output(self, path: Path) -> Path:
        self.job.outputs.append(str(path))
        self.changed()
        return path


def run_folder(ctx: Context) -> str:
    goal = ctx.job.goal
    folder = find_folder(goal)
    if folder is None:
        raise JobError("Which folder? Name it in the job, e.g. “compare the PDFs in C:\\Users\\you\\Documents\\Offers”.")
    files = list_files(folder)
    if not files:
        raise JobError(f"{folder} has no documents I can read (PDF, Word, Excel, PowerPoint, text, CSV, images).")
    ctx.plan("Decide what to compare", f"Read {len(files)} file(s)", "Build the spreadsheet", "Write the one-page report")
    ctx.allow(security.READ_FILE, f"{len(files)} file(s) in {folder}\n(their text goes to an AI provider to be read)")

    ctx.step(0)
    names = ", ".join(p.name for p in files[:40])
    plan = ctx.ask_json(
        f"The user asked: “{goal}”.\nThe folder holds: {names}.\n"
        "Decide how to compare these documents. Return {\"title\": a short report title, \"columns\": 3-8 short "
        "column names for a comparison table (not the file name; e.g. Supplier, Price, Delivery, Warranty)}.",
        targets=PLANNER)
    columns = [str(c).strip() for c in (plan.get("columns") if isinstance(plan, dict) else None) or [] if str(c).strip()]
    columns = columns[:8] or ["Summary", "Key figure", "Date", "Notes"]
    title = (plan.get("title") if isinstance(plan, dict) else "") or f"{folder.name} comparison"
    ctx.job.title = str(title)[:80]
    ctx.step(0, "done", ", ".join(columns))

    ctx.step(1)
    rows: list[tuple[Path, dict]] = []
    unread: list[str] = []
    for number, path in enumerate(files, 1):
        ctx.note(1, f"{number}/{len(files)}: {path.name}", (number - 1) / len(files))
        text = file_text(path)
        if not text.strip():
            unread.append(path.name)
            continue
        wrapped, _ = shield.wrap(text, path.name)
        try:
            values = kit.ask_json(ctx.brain, (
                f"{shield.RULE}\nFrom this document, fill in these fields: {json.dumps(columns, ensure_ascii=False)}. "
                "Return one JSON object with exactly those keys. Short values copied or summarised from the document; "
                "\"not stated\" when it does not say. Never guess numbers.\n\n" + wrapped))
        except kit.KitError:
            values = {}
        ctx.check()
        rows.append((path, values if isinstance(values, dict) else {}))
    ctx.step(1, "done", f"{len(rows)} read" + (f", {len(unread)} had no readable text" if unread else ""))

    ctx.step(2)
    sheet = write_sheet(ctx.job.title, columns, rows, folder)
    ctx.output(sheet)
    ctx.step(2, "done", sheet.name)

    ctx.step(3)
    table = "\n".join(f"- {p.name}: " + "; ".join(f"{c}: {v.get(c, 'not stated')}" for c in columns)
                      for p, v in rows)[:30000]
    markdown = ctx.ask(
        "Write a one-page report in Markdown comparing these documents, for the request: "
        f"“{goal}”.\nStart with '# {ctx.job.title}', then ## Summary (3-4 sentences), ## Highlights "
        "(the best and worst on what matters, naming files), ## Watch out for, ## Recommendation. Use only "
        f"the data below; say when something is not stated.\n\n{table}")
    report = save_markdown(markdown, ctx.job.title)
    for path in report:
        ctx.output(path)
    ctx.step(3, "done", report[0].name if report else "")
    note = f"\n{len(unread)} file(s) had no readable text (a scanned PDF needs OCR): {', '.join(unread[:5])}" \
        if unread else ""
    return (f"Compared {len(rows)} document(s) from {folder.name} on {len(columns)} points: "
            f"{', '.join(columns)}.{note}")


def write_sheet(title: str, columns: list[str], rows: list[tuple[Path, dict]], folder: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "Comparison"
    sheet.append(["File", *columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0E7490")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for path, values in rows:
        sheet.append([path.name, *[str(values.get(c, "not stated"))[:1000] for c in columns]])
        try:
            link = sheet.cell(row=sheet.max_row, column=1)
            link.hyperlink = path.resolve().as_uri()
            link.font = Font(color="0563C1", underline="single")
        except ValueError:
            pass
    for index, column in enumerate(sheet.columns, 1):
        width = max(len(str(c.value or "")) for c in column)
        sheet.column_dimensions[column[0].column_letter].width = max(12, min(60, width + 2))
        for c in column[1:]:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "B2"
    info = book.create_sheet("About")
    info.append(["Made by JARVIS Cowork from", str(folder)])
    info.append(["Files", len(rows)])
    info.append(["Note", "Values were read by an AI from each file. Check anything you rely on."])
    path = out_path(title, ".xlsx")
    book.save(path)
    return path


def save_markdown(markdown: str, title: str) -> list[Path]:
    from . import writer

    text = writer.clean_markdown(markdown or "")
    if not text.startswith("#"):
        text = f"# {title}\n\n{text}"
    try:
        return writer.save(text, ("docx",))
    except writer.WriterError:
        path = out_path(title, ".md")
        path.write_text(text, encoding="utf-8")
        return [path]


def run_inbox(ctx: Context) -> str:
    from . import social

    account = social.MAIL.load()
    if not account.get("user"):
        raise JobError("Connect your email first: type /inbox setup (it asks for an app password, not your real one).")
    ctx.plan("Read recent email", "Sort and summarise", "Draft replies in your tone", "Write the triage report")
    ctx.allow(security.READ_MAIL, f"{account['user']}: the last 3 days, up to 25 messages")

    ctx.step(0)
    try:
        mails = social.fetch_mail(account, limit=25, hours=72)
    except Exception as exc:
        raise JobError(f"Couldn't read the mailbox: {exc}") from None
    ctx.step(0, "done", f"{len(mails)} message(s)")
    if not mails:
        for i in (1, 2, 3):
            ctx.step(i, "skipped")
        return "No email in the last three days."

    ctx.step(1)
    try:
        from .ten.work import TONE

        tone = TONE.load().get("notes") or "clear, friendly and brief"
    except Exception:
        tone = "clear, friendly and brief"
    material = "\n\n".join(f"[{i}] From: {m['from']}\nSubject: {m['subject']}\nUnread: {m['unread']}\n{m['body'][:600]}"
                           for i, m in enumerate(mails))
    wrapped, _ = shield.wrap(material, "the user's inbox")
    sorted_ = ctx.ask_json(
        f"{shield.RULE}\nSort these emails. Return a JSON list with one object per email: {{\"i\": its number, "
        "\"category\": \"action\" | \"reply\" | \"fyi\" | \"newsletter\", \"priority\": 1 (urgent) to 3, "
        "\"summary\": one short line, \"reply\": a short draft reply for action/reply emails (empty for the "
        f"others), written in the email's language and in this style: {tone}}}. Never promise anything on the "
        "user's behalf, never include passwords or codes.\n\n" + wrapped)
    items = [x for x in sorted_ if isinstance(x, dict)] if isinstance(sorted_, list) else []
    ctx.step(1, "done", f"{sum(x.get('category') in {'action', 'reply'} for x in items)} need you")

    ctx.step(2)
    from email.utils import parseaddr

    drafts = []
    for item in items:
        try:
            mail = mails[int(item.get("i", -1))]
        except (ValueError, IndexError, TypeError):
            continue
        item["mail"] = mail
        reply = str(item.get("reply") or "").strip()
        if reply and item.get("category") in {"action", "reply"}:
            subject = mail["subject"] if mail["subject"].lower().startswith("re:") else f"Re: {mail['subject']}"
            drafts.append({"to": parseaddr(mail["from"])[1], "subject": subject, "body": reply,
                           "from": mail["from"]})
    ctx.job.extra["drafts"] = drafts
    ctx.step(2, "done", f"{len(drafts)} draft(s) — open each in your mail app to send it yourself")

    ctx.step(3)
    groups = (("action", "Needs action"), ("reply", "Needs a reply"), ("fyi", "For your information"),
              ("newsletter", "Newsletters and promotions"))
    lines = [f"# Inbox triage — {account['user']}", "",
             f"{len(mails)} message(s) from the last three days. Drafts are suggestions: nothing was sent.", ""]
    for key, heading in groups:
        chosen = sorted((x for x in items if x.get("category") == key and "mail" in x),
                        key=lambda x: int(x.get("priority") or 3))
        if not chosen:
            continue
        lines += [f"## {heading}", ""]
        for x in chosen:
            m = x["mail"]
            flag = "🔴 " if int(x.get("priority") or 3) == 1 else ""
            lines.append(f"- {flag}**{m['subject'] or '(no subject)'}** — {m['from']}: {x.get('summary', '')}")
        lines.append("")
    if drafts:
        lines += ["## Draft replies", ""]
        for d in drafts:
            lines += [f"### To {d['from']} — {d['subject']}", "", d["body"], ""]
    report = save_markdown("\n".join(lines), f"Inbox triage {time.strftime('%d %b')}")
    for path in report:
        ctx.output(path)
    ctx.step(3, "done", report[0].name if report else "")
    counts = {key: sum(x.get("category") == key for x in items) for key, _ in groups}
    return (f"{len(mails)} email(s): {counts['action']} need action, {counts['reply']} need a reply, "
            f"{counts['fyi']} FYI, {counts['newsletter']} newsletters. {len(drafts)} draft(s) ready — "
            "nothing was sent.")


FORM_PROMPT = """This is a screenshot of a web page with a form. Find the form's input fields that are visible.
The user's details are: {profile}
Return JSON: {{"fields": [{{"label": the field's label, "x": centre of the input box from the left (0 to 1),
"y": centre from the top (0 to 1), "kind": "text" | "select" | "checkbox" | "radio" | "file",
"value": what to enter from the user's details, or "" when the details don't say}}],
"more_below": true if the form clearly continues below the visible part}}.
Only input fields: never buttons or links. Never put a password, card number or ID number in a value."""


def run_form(ctx: Context) -> str:
    from . import screen

    goal = ctx.job.goal
    url = find_url(goal)
    profile = load_profile()
    cv = find_file(goal, {".pdf", ".docx", ".txt", ".md"})
    ctx.plan("Gather your details", "Open the form", "Fill the fields", "Hand it back to you")

    ctx.step(0)
    if cv is not None:
        ctx.allow(security.READ_FILE, f"{cv}\n(your CV, to read your details for the form)")
        from_cv = profile_from_text(ctx.brain, file_text(cv, 15000))
        profile = {**from_cv, **profile}
    if not profile:
        raise JobError("I don't know your details yet. Add them with /profile (e.g. /profile email = you@mail.com), "
                       "or name your CV in the job: “fill https://… from C:\\…\\cv.pdf”.")
    ctx.step(0, "done", ", ".join(list(profile)[:8]))

    ctx.allow(security.CONTROL_SCREEN, f"Fill the form at {url or 'the window in front of you'} with your "
              f"{', '.join(list(profile)[:10])}.")
    hands = screen.Hands(ctx.job.stop_event)
    hands.allowed = True
    ctx.step(1)
    if url:
        import webbrowser

        webbrowser.open(url)
        ctx.note(1, "waiting for the page to load…")
        ctx.wait(7)
    else:
        ctx.note(1, "switch to the form now — starting in 5 seconds")
        ctx.wait(5)
    ctx.step(1, "done", url or "the window in front")

    ctx.step(2)
    filled, unknown, manual, refused = [], [], [], []
    safe_profile = {k: v for k, v in profile.items() if not re.search(r"password|şifre|card|kart|iban|tc|kimlik", k, re.I)}
    for screen_number in range(MAX_FORM_SCREENS):
        ctx.note(2, f"reading the screen ({screen_number + 1})…")
        shot = screen.screenshot()
        data = ctx.ask_json(FORM_PROMPT.format(profile=json.dumps(safe_profile, ensure_ascii=False)),
                            image_b64=screen.encode(shot), targets=vision_targets())
        fields = [f for f in (data.get("fields") if isinstance(data, dict) else []) or [] if isinstance(f, dict)]
        for spec in fields:
            label = str(spec.get("label") or "field").strip()[:60]
            value = str(spec.get("value") or "").strip()
            kind = str(spec.get("kind") or "text").lower()
            if screen.is_commit(label):
                refused.append(label)
                continue
            if not value:
                unknown.append(label)
                continue
            if kind != "text":
                manual.append(f"{label}: {value}")
                continue
            try:
                x, y = screen.to_pixels(spec.get("x", -1), spec.get("y", -1), shot.width, shot.height)
                hands.click(x, y, label, space=(shot.width, shot.height))
                hands.type_text(value, label)
            except screen.Stopped:
                raise Stopped() from None
            except (screen.ScreenError, TypeError, ValueError) as exc:
                manual.append(f"{label}: {value} ({exc})")
                continue
            filled.append(label)
            ctx.note(2, f"filled {len(filled)}: {label}")
        if not (isinstance(data, dict) and data.get("more_below")):
            break
        try:
            hands.scroll(-6)
        except screen.Stopped:
            raise Stopped() from None
    ctx.step(2, "done", f"{len(filled)} filled")

    ctx.step(3)
    hands.allowed = False
    lines = [f"Filled {len(filled)} field(s): {', '.join(filled) or 'none'}."]
    if manual:
        lines.append("Please do these yourself (drop-downs, boxes, uploads): " + "; ".join(manual[:10]))
    if unknown:
        lines.append("I didn't know: " + ", ".join(unknown[:10]) + " — add them with /profile for next time.")
    lines.append("Check everything, then press Submit yourself. Cowork never submits.")
    ctx.step(3, "done")
    ctx.job.extra["filled"] = filled
    return "\n".join(lines)


def run_research(ctx: Context) -> str:
    from . import websearch

    goal = ctx.job.goal
    ctx.plan("Plan the searches", "Search the web", "Read the sources", "Write the sourced report")
    ctx.step(0)
    plan = ctx.ask_json(
        f"Research request: “{goal}”.\nReturn {{\"title\": a short report title, \"queries\": 3-4 web search "
        "queries that together answer it (in the request's language, plus English if that finds more)}}.",
        targets=PLANNER)
    queries = [str(q) for q in (plan.get("queries") if isinstance(plan, dict) else None) or [] if str(q).strip()][:4]
    queries = queries or [goal]
    ctx.job.title = str((plan.get("title") if isinstance(plan, dict) else "") or goal)[:80]
    ctx.step(0, "done", " · ".join(queries))

    ctx.step(1)
    results, seen = [], set()
    for number, query in enumerate(queries, 1):
        ctx.note(1, f"“{query}”", (number - 1) / len(queries))
        try:
            found = websearch.search(query, limit=5)
        except Exception:
            continue
        for item in found:
            key = item.url.split("#")[0].rstrip("/")
            if key not in seen:
                seen.add(key)
                results.append(item)
    if not results:
        raise JobError("The web search found nothing. Check the connection, or word the job differently.")
    ctx.step(1, "done", f"{len(results)} result(s)")

    ctx.step(2)
    sources = []
    for item in results:
        if len(sources) >= MAX_SOURCES:
            break
        ctx.note(2, item.url[:80], len(sources) / MAX_SOURCES)
        try:
            title, text = websearch.fetch(item.url)
        except Exception:
            continue
        if len(text.strip()) < 200:
            continue
        sources.append({"title": (title or item.title)[:120], "url": item.url, "text": text[:5000]})
    if not sources:
        sources = [{"title": r.title, "url": r.url, "text": r.snippet} for r in results[:MAX_SOURCES]]
    ctx.step(2, "done", f"{len(sources)} source(s) read")

    ctx.step(3)
    numbered = "\n\n".join(f"[{i}] {s['title']} — {s['url']}\n{shield.wrap(s['text'], s['url'])[0]}"
                           for i, s in enumerate(sources, 1))
    with kit.more_room(ctx.brain, 6000):
        markdown = ctx.ask(
            f"{shield.RULE}\nWrite a research report in Markdown answering: “{goal}”. Start with "
            f"'# {ctx.job.title}', then ## Summary, then sections as the topic needs, then ## Bottom line. "
            "Cite every factual claim with its source number like [2]. Only use the sources; say where they "
            "disagree or are missing. Same language as the request. Do not add a sources list (it is added "
            f"for you).\n\n{numbered}")
    markdown = (markdown.rstrip() + "\n\n## Sources\n\n" +
                "\n".join(f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(sources, 1)))
    report = save_markdown(markdown, ctx.job.title)
    for path in report:
        ctx.output(path)
    ctx.step(3, "done", report[0].name if report else "")
    first = re.sub(r"\s+", " ", markdown.split("## Summary", 1)[-1].split("##", 1)[0]).strip()
    return (first[:600] + ("…" if len(first) > 600 else "")) + f"\n\n{len(sources)} source(s), cited in the report."


def run_general(ctx: Context) -> str:
    goal = ctx.job.goal
    plan = ctx.ask_json(
        f"Plan this job for an AI assistant that can only think and write (no web, no files): “{goal}”.\n"
        "Return {\"title\": a short title, \"steps\": 2-6 objects {\"title\": 3-6 words, \"do\": what to produce in "
        "this step}}. The last step produces the finished deliverable.", targets=PLANNER)
    steps = [s for s in (plan.get("steps") if isinstance(plan, dict) else None) or [] if isinstance(s, dict)][:6]
    if not steps:
        steps = [{"title": "Do the job", "do": goal}]
    ctx.job.title = str((plan.get("title") if isinstance(plan, dict) else "") or goal)[:80]
    ctx.plan(*[str(s.get("title") or f"Step {i}")[:60] for i, s in enumerate(steps, 1)])
    done: list[str] = []
    for index, spec in enumerate(steps):
        ctx.step(index)
        last = index == len(steps) - 1
        so_far = "\n\n".join(done[-3:])[-12000:]
        with kit.more_room(ctx.brain, 6000 if last else 2500):
            out = ctx.ask(
                f"Job: {goal}\nPlan: " + " → ".join(str(s.get('title')) for s in steps) +
                (f"\n\nWork so far:\n{so_far}" if so_far else "") +
                f"\n\nNow do step {index + 1}: {spec.get('do') or spec.get('title')}. " +
                ("This is the final deliverable: write it in full as a Markdown document starting with "
                 f"'# {ctx.job.title}'." if last else "Output only this step's result, concisely."))
        done.append(f"## {spec.get('title')}\n{out}")
        ctx.step(index, "done")
    report = save_markdown(done[-1].split("\n", 1)[-1], ctx.job.title)
    for path in report:
        ctx.output(path)
    return f"Done in {len(steps)} step(s): “{ctx.job.title}”."


RUNNERS = {"folder": run_folder, "inbox": run_inbox, "form": run_form, "research": run_research,
           "general": run_general}


# --- the manager ------------------------------------------------------------------------------

class Manager:
    """Every job of this session, and the last few of earlier ones."""

    def __init__(self) -> None:
        self.jobs: list[Job] = []
        self.listeners: list = []
        self._lock = threading.Lock()
        self._loaded = False
        self.brain_factory = None

    def _store(self):
        return kit.Store("cowork_jobs.json", [])

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            saved = [Job.from_dict(d) for d in self._store().load() if isinstance(d, dict)]
        except Exception:
            saved = []
        with self._lock:
            known = {j.id for j in self.jobs}
            self.jobs = [j for j in saved if j.id not in known] + self.jobs

    def save(self) -> None:
        try:
            with self._lock:
                data = [j.as_dict() for j in self.jobs if not j.running][-HISTORY_LIMIT:]
            self._store().save(data)
        except Exception:
            pass

    def subscribe(self, listener) -> None:
        if listener not in self.listeners:
            self.listeners.append(listener)

    def notify(self, job: Job) -> None:
        for listener in list(self.listeners):
            try:
                listener(job)
            except Exception:
                pass

    def get(self, job_id: int) -> Job | None:
        self.load()
        return next((j for j in self.jobs if j.id == job_id), None)

    def running(self) -> list[Job]:
        return [j for j in self.jobs if j.running]

    def _brain(self):
        if self.brain_factory is not None:
            return self.brain_factory()
        from .brain import Brain

        return Brain()

    def start(self, goal: str, kind: str | None = None, wait: bool = False) -> Job:
        self.load()
        goal = (goal or "").strip()
        if not goal:
            raise JobError("Describe the job, e.g. “compare the PDFs in C:\\Offers and make a table”.")
        kind = kind if kind in RUNNERS else detect_kind(goal)
        with self._lock:
            job = Job(max([j.id for j in self.jobs] or [0]) + 1, goal, kind, title=goal[:80])
            self.jobs.append(job)
        security.audit.record("cowork", f"#{job.id} {kind}", goal[:120])
        thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"cowork-{job.id}")
        thread.start()
        self.notify(job)
        if wait:
            thread.join()
        return job

    def _run(self, job: Job) -> None:
        ctx = Context(job, self, self._brain())
        try:
            job.result = RUNNERS[job.kind](ctx) or ""
            job.status = "done"
            job.progress = 1.0
        except Stopped:
            job.status = "stopped"
            job.result = "Stopped. Files already made are kept (Undo removes them)."
        except (JobError, security.Denied) as exc:
            job.status = "failed"
            job.error = str(exc)
        except Exception as exc:  # a broken job reports itself; it never takes JARVIS down
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            try:
                from . import errorlog

                errorlog.record(f"cowork {job.kind}", exc)
            except Exception:
                pass
        for step in job.steps:
            if step.status == "running":
                step.status = "failed" if job.status == "failed" else "skipped"
        job.finished = time.time()
        security.audit.record("cowork", f"#{job.id} {job.status}", job.error[:120] or job.result[:120])
        self.save()
        self.notify(job)

    def stop(self, job_id: int) -> str:
        job = self.get(job_id)
        if job is None:
            return f"No job #{job_id}."
        if not job.running:
            return f"Job #{job_id} isn't running."
        job.stop_event.set()
        return f"Stopping job #{job_id}…"

    def undo(self, job_id: int) -> str:
        job = self.get(job_id)
        if job is None:
            return f"No job #{job_id}."
        if job.running:
            return f"Job #{job_id} is still running. Stop it first."
        made = [Path(p) for p in job.outputs if Path(p).is_file()]
        if not made:
            return f"Job #{job_id} left no files to remove."
        if not security.permissions.ask(security.DELETE_FILE, "\n".join(str(p) for p in made),
                                        context=f"Cowork undo #{job_id}"):
            return "Kept the files."
        removed = 0
        for path in made:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        job.outputs = [p for p in job.outputs if Path(p).exists()]
        job.extra["undone"] = True
        self.save()
        self.notify(job)
        return f"Removed {removed} file(s) that job #{job_id} made."

    def describe(self, limit: int = 8) -> str:
        self.load()
        if not self.jobs:
            return ("No Cowork jobs yet. Turn on Cowork next to Send, or type /cowork <job>, e.g.\n"
                    "  /cowork compare the PDFs in C:\\Users\\you\\Documents\\Offers\n"
                    "  /cowork sort my inbox and draft replies\n"
                    "  /cowork research the best student laptops under 30000 TL\n"
                    "  /cowork fill https://… from my CV C:\\…\\cv.pdf")
        marks = {"planning": "…", "running": "▶", "done": "✓", "failed": "✗", "stopped": "■"}
        lines = ["🧰 Cowork jobs:"]
        for job in self.jobs[-limit:][::-1]:
            pct = f" {int(job.progress * 100)}%" if job.running else ""
            lines.append(f"  {marks.get(job.status, '·')} #{job.id} {job.label()}: {job.title[:60]}{pct}")
        lines.append("/cowork stop <n> · /cowork undo <n> · /cowork open <n>")
        return "\n".join(lines)


manager = Manager()
