"""Document Q&A — open a file, then ask questions about it.

Handles PDF (via pypdf), DOCX (parsed straight from the zip, no extra
dependency), and any plain-text format. The open document is held in memory
and attached to your next questions until you close it.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from jarvis.addons import Addon, Command

# Characters of the document sent as context. Roughly 15k tokens — comfortably
# inside a free-tier context window while still covering most documents.
MAX_CONTEXT_CHARS = 60_000
TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log",
    ".html", ".css", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".rst",
}


class DocumentQA(Addon):
    name = "document-qa"
    version = "1.0"
    description = "Reads a document so you can ask questions about it."

    def __init__(self):
        self.path: Path | None = None
        self.text: str = ""
        # Which document has already been placed in the conversation.
        self._sent_for: Path | None = None

    def commands(self):
        return [
            Command("doc", self.open_doc, "Open a document", "/doc <path to file>"),
            Command("docclose", self.close_doc, "Close the open document", "/docclose"),
            Command("summary", self.summarise, "Summarise the open document", "/summary"),
        ]

    # --- extraction -------------------------------------------------------

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("PDF support needs pypdf — run: pip install pypdf")

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise RuntimeError("That PDF is password protected.")

        pages = []
        for number, page in enumerate(reader.pages, 1):
            try:
                content = page.extract_text() or ""
            except Exception:
                content = ""
            if content.strip():
                pages.append(f"[page {number}]\n{content}")
        if not pages:
            raise RuntimeError(
                "No text could be extracted — the PDF is probably scanned "
                "images. Try /see instead to look at it on screen."
            )
        return "\n\n".join(pages)

    @staticmethod
    def _read_docx(path: Path) -> str:
        """DOCX is a zip of XML, so the standard library is enough."""
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError):
            raise RuntimeError("That doesn't look like a valid .docx file.")

        # Paragraph and line breaks become newlines; every other tag goes.
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = (
            text.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not cleaned:
            raise RuntimeError("That document appears to be empty.")
        return cleaned

    @staticmethod
    def _read_text(path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8", "utf-16", "cp1254", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")

    def _extract(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix == ".docx":
            return self._read_docx(path)
        if suffix in TEXT_SUFFIXES or suffix == "":
            return self._read_text(path)
        # Try it as text anyway — better than refusing outright.
        return self._read_text(path)

    # --- commands ---------------------------------------------------------

    def open_doc(self, ctx, args: str) -> str:
        raw = args.strip().strip('"').strip("'")
        if not raw:
            return (
                "Usage: /doc <path to file>\n"
                'Example: /doc C:\\Users\\me\\report.pdf\n'
                "Supports PDF, DOCX, and text files."
            )

        path = Path(raw).expanduser()
        if not path.exists():
            return f"I can't find that file:\n  {path}"
        if path.is_dir():
            return f"That's a folder, not a file:\n  {path}"

        try:
            text = self._extract(path)
        except RuntimeError as exc:
            return str(exc)
        except Exception as exc:
            return f"Couldn't read that file: {exc}"

        self.path = path
        self.text = text
        self.source = ""
        self._sent_for = None
        words = len(text.split())
        truncated = (
            f"\nOnly the first {MAX_CONTEXT_CHARS:,} characters will be used as context."
            if len(text) > MAX_CONTEXT_CHARS
            else ""
        )
        return (
            f"Opened {path.name} — {words:,} words, {len(text):,} characters."
            f"{truncated}\n"
            "Ask me anything about it, or use /summary. /docclose when you're done."
        )

    def close_doc(self, ctx, args: str) -> str:
        if self.path is None:
            return "No document is open."
        name = self.path.name
        self.path = None
        self.text = ""
        self._sent_for = None
        return f"Closed {name}."

    def summarise(self, ctx, args: str) -> str:
        if not self.text:
            return "No document is open. Use /doc <path> first."
        from jarvis import shield

        cleaned = shield.clean(self.text[:MAX_CONTEXT_CHARS], self._label())
        summary = ctx.ask(
            "Summarise this document in a short paragraph, then list its key "
            f"points as bullets.\n\n{shield.RULE}\n{cleaned.wrapped()}"
        )
        warning = cleaned.warning()
        return summary + (f"\n\n{warning}" if warning else "")

    # --- conversation hook ------------------------------------------------

    def open_text(self, title: str, text: str, source: str) -> None:
        """Open text that did not come from a file — a web page, for /read."""
        self.path = Path(re.sub(r"[^\w.\- ]+", "_", title)[:80] or "page")
        self.text = text
        self.source = source
        self._sent_for = None

    def _label(self) -> str:
        return getattr(self, "source", "") or (self.path.name if self.path else "document")

    def enrich_prompt(self, ctx, text: str) -> str | None:
        """Attach the document: whole the first time, then what is relevant.

        Until 6.0 it was attached to the first question only, on the belief
        that it "stays in the history the model already receives". It does
        not: the history keeps what you typed, not what addons attached, so
        from the second question on the model was answering about a document
        it could no longer see. Re-sending 60k characters every turn would
        burn a free tier's per-minute budget, so follow-ups get the passages
        that best match the question instead.

        Either way the text is wrapped as untrusted: a document can contain
        sentences written to the AI rather than to you.
        """
        if not self.text:
            return None
        from jarvis import library, shield

        source = self._label()
        brain = getattr(ctx.jarvis, "brain", None)
        forgotten = not getattr(brain, "history", None)
        if self._sent_for != self.path or forgotten:
            self._sent_for = self.path
            wrapped, _warning = shield.wrap(self.text[:MAX_CONTEXT_CHARS], source)
            return (f"The user has this document open — use it to answer if relevant.\n"
                    f"{shield.RULE}\n{wrapped}")

        index = {"passages": [[p.file, p.page, p.text]
                              for p in library._passages(source, [(0, self.text)])]}
        hits = library.search(index, text, limit=6)
        if not hits:
            return None
        excerpt = "\n…\n".join(p.text for p in hits)
        wrapped, _warning = shield.wrap(excerpt, source)
        return (f"Passages from the open document ({source}) that match this "
                f"question.\n{shield.RULE}\n{wrapped}")


ADDON = DocumentQA()
