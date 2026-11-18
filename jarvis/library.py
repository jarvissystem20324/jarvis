"""A documents library — ask questions across a whole folder at once.

/doc opens one file. This indexes a folder of PDFs, Word documents, notes and
Markdown, splits them into passages, and answers a question from the handful
of passages that actually match it, citing the file each came from.

The retrieval is BM25 over words, not embeddings, for the same reasons the
code index is: it needs no model, no key, and nothing leaves the machine to
build it. Only the few passages chosen for a question are ever sent, and only
after you are asked.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import vault
from .config import get_data_dir

READABLE = {".pdf", ".docx", ".txt", ".md", ".markdown", ".rst", ".csv", ".html", ".htm",
            # 13.4.2: company folders are mostly spreadsheets and decks.
            ".xlsx", ".xlsm", ".pptx"}
MAX_FILES = 800
MAX_FILE_BYTES = 30_000_000
PASSAGE_WORDS = 180
PASSAGE_OVERLAP = 40
TOP_PASSAGES = 6

# Ordinary words that match everything and so tell you nothing.
STOPWORDS = set("""
a an and are as at be but by for from has have how i if in into is it its
of on or that the their them then there these this to was were what when
where which who why will with you your do does did can could should would
ve bir ve ile bu şu da de mi mı ne nasıl için olan
""".split())

_WORD = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)


@dataclass
class Passage:
    file: str
    page: int          # 0 when the format has no pages
    text: str


def _words(text: str) -> list[str]:
    return [w for w in (m.lower() for m in _WORD.findall(text))
            if len(w) > 1 and w not in STOPWORDS]


# --- reading ---------------------------------------------------------------

def _read_pdf(path: Path) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    except Exception:
        return []


def _read_docx(path: Path) -> list[tuple[int, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return []
    xml = re.sub(r"</w:p>", "\n", xml)
    return [(0, re.sub(r"<[^>]+>", "", xml))]


def _read_text(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if path.suffix.lower() in {".html", ".htm"}:
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return [(0, text)]


def _read_xlsx(path: Path, max_rows: int = 2000) -> list[tuple[int, str]]:
    """One 'page' per sheet: its rows as tab-separated lines."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return []
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return []
    pages = []
    try:
        for number, sheet in enumerate(book.worksheets, 1):
            lines = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    lines.append("\t".join(cells).rstrip())
                if len(lines) >= max_rows:
                    break
            if lines:
                pages.append((number, f"Sheet: {sheet.title}\n" + "\n".join(lines)))
    except Exception:
        return pages
    finally:
        try:
            book.close()
        except Exception:
            pass
    return pages


def _read_pptx(path: Path) -> list[tuple[int, str]]:
    """One page per slide, with its notes."""
    try:
        from pptx import Presentation
    except ImportError:
        return []
    try:
        deck = Presentation(str(path))
    except Exception:
        return []
    pages = []
    for number, slide in enumerate(deck.slides, 1):
        texts = [shape.text_frame.text for shape in slide.shapes
                 if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()]
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                texts.append("Notes: " + slide.notes_slide.notes_text_frame.text)
        except Exception:
            pass
        if texts:
            pages.append((number, "\n".join(t.replace("\v", "\n") for t in texts)))
    return pages


def read_document(path: Path) -> list[tuple[int, str]]:
    """(page, text) pairs. An unreadable file yields nothing, not an error."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(path)
    if suffix == ".pptx":
        return _read_pptx(path)
    return _read_text(path)


def document_text(path: Path, limit: int = 60_000) -> str:
    """The whole readable text of one file, pages marked, cut at `limit`."""
    parts = []
    for page, text in read_document(path):
        parts.append((f"[page {page}]\n" if page else "") + text.strip())
        if sum(len(p) for p in parts) >= limit:
            break
    return "\n\n".join(parts)[:limit]


def _passages(relative: str, pages: list[tuple[int, str]]) -> list[Passage]:
    out: list[Passage] = []
    step = PASSAGE_WORDS - PASSAGE_OVERLAP
    for page, text in pages:
        words = text.split()
        for start in range(0, max(1, len(words)), step):
            chunk = " ".join(words[start:start + PASSAGE_WORDS])
            # The length floor is for scraps left at the end of a long page.
            # Applied to the first passage too, it silently dropped any
            # document shorter than a sentence or two — a one-line note
            # indexed as empty.
            if len(chunk) > 40 or (start == 0 and chunk.strip()):
                out.append(Passage(relative, page, chunk))
            if start + PASSAGE_WORDS >= len(words):
                break
    return out


# --- the index -------------------------------------------------------------

def _store(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    folder = get_data_dir() / "library"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def build(root: Path) -> dict:
    """Read every document under `root`. Returns a summary of what was read."""
    passages: list[Passage] = []
    files, skipped = 0, []
    for path in sorted(root.rglob("*")):
        if files >= MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in READABLE:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped.append(f"{path.name} (too large)")
                continue
        except OSError:
            continue
        pages = read_document(path)
        found = _passages(str(path.relative_to(root)).replace("\\", "/"), pages)
        if not found:
            skipped.append(f"{path.name} (no readable text — a scanned PDF needs OCR)"
                           if path.suffix.lower() == ".pdf" else f"{path.name} (empty)")
            continue
        passages.extend(found)
        files += 1

    data = {
        "root": str(root.resolve()),
        "built": time.time(),
        "files": files,
        "skipped": skipped,
        "passages": [[p.file, p.page, p.text] for p in passages],
    }
    try:
        # Passages of your own documents: sealed like conversations are.
        vault.write_json(_store(root), data, indent=None)
    except OSError:
        pass
    return data


def load(root: Path) -> dict | None:
    try:
        data = vault.read_json(_store(root))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def search(data: dict, question: str, limit: int = TOP_PASSAGES) -> list[Passage]:
    """The passages most likely to answer `question` (BM25)."""
    passages = [Passage(f, int(p), t) for f, p, t in data.get("passages") or []]
    terms = set(_words(question))
    if not passages or not terms:
        return []

    tokenised = [Counter(_words(p.text)) for p in passages]
    average = sum(sum(c.values()) for c in tokenised) / len(tokenised) or 1.0
    documents_with = Counter(term for counts in tokenised for term in counts if term in terms)
    total = len(passages)
    k1, b = 1.5, 0.75

    scored: list[tuple[float, int]] = []
    for index, counts in enumerate(tokenised):
        length = sum(counts.values()) or 1
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = documents_with[term]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average))
        if score > 0:
            scored.append((score, index))
    scored.sort(reverse=True)
    return [passages[i] for _s, i in scored[:limit]]


def cite(passage: Passage) -> str:
    return f"{passage.file}" + (f", page {passage.page}" if passage.page else "")
