"""JARVIS Docs — turn a request into a finished Word document and PDF.

    /makedoc a one-page cover letter for a junior developer job at Spotify
    /docx meeting notes template          /pdf a 5-day Rome itinerary
    /makedoc revise: make it shorter and more formal

The model writes the document in Markdown (which it is good at); this module
typesets it into .docx with python-docx and .pdf with fpdf2 — real headings,
lists, bold, tables and code blocks, not a text dump. The Markdown is kept,
so "revise:" edits the last document instead of starting over.

Turkish needs a real font in a PDF (the built-in PDF fonts stop at Latin-1,
so ş, ğ and ı would come out as "?"), so the system's Arial or Segoe UI is
embedded when one is present.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from .config import get_output_dir

PROMPT = """Write the document the user asked for, in Markdown.

Rules:
- Start with a single "# Title" line.
- Use "##" and "###" headings, "-" bullets, "1." numbered lists, **bold**,
  *italic*, and pipe tables where they help. Code goes in ``` fences.
- Write the complete document at a sensible length for what was asked —
  never a outline, never "[insert X here]" unless it is genuinely a template
  the user asked for.
- Match the language of the request.
- Output only the document: no preamble, no closing remarks.
"""

REVISE = """Here is a document you wrote, in Markdown. Revise it as the user
asks and return the whole revised document in the same Markdown form, with
nothing before or after it.

Request: {request}

--- document ---
{document}
"""


class WriterError(Exception):
    pass


def documents_dir() -> Path:
    folder = get_output_dir().parent / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clean_markdown(text: str) -> str:
    """Drop a wrapping ```markdown fence and anything before the title."""
    body = (text or "").strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", body, re.S)
    if fence:
        body = fence.group(1).strip()
    title_at = body.find("# ")
    if 0 < title_at < 400 and body[title_at - 1] == "\n":
        body = body[title_at:]
    return body


def title_of(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or "Document"
    return "Document"


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", cleaned)[:60] or "document"


# --- markdown -> blocks ------------------------------------------------------

def blocks(markdown: str) -> list[tuple]:
    """A tiny Markdown reader: (kind, payload) in document order."""
    out: list[tuple] = []
    lines = markdown.splitlines()
    i = 0
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(("p", " ".join(s.strip() for s in paragraph)))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(("code", "\n".join(code)))
        elif re.match(r"^#{1,6}\s", stripped):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(("h", (min(level, 3), stripped[level:].strip())))
        elif re.match(r"^[-*+]\s+", stripped):
            flush()
            out.append(("li", re.sub(r"^[-*+]\s+", "", stripped)))
        elif re.match(r"^\d+[.)]\s+", stripped):
            flush()
            out.append(("ol", re.sub(r"^\d+[.)]\s+", "", stripped)))
        elif stripped.startswith("|") and stripped.endswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            out.append(("table", rows))
            continue
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush()
            out.append(("hr", ""))
        elif stripped.startswith(">"):
            flush()
            out.append(("quote", stripped.lstrip("> ")))
        elif not stripped:
            flush()
        else:
            paragraph.append(stripped)
        i += 1
    flush()
    return out


_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|__[^_]+__|_[^_]+_)")


def runs(text: str) -> list[tuple[str, str]]:
    """Inline formatting as (style, text): '' plain, 'b', 'i', 'code'."""
    out = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith(("**", "__")) and len(part) > 4:
            out.append(("b", part[2:-2]))
        elif part.startswith("`") and len(part) > 2:
            out.append(("code", part[1:-1]))
        elif part.startswith(("*", "_")) and len(part) > 2:
            out.append(("i", part[1:-1]))
        else:
            out.append(("", part))
    return out


# --- Word ------------------------------------------------------------------------

def to_docx(markdown: str, path: Path) -> Path:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError:
        raise WriterError("Word output needs python-docx (pip install python-docx).")

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    def add_runs(paragraph, text: str) -> None:
        for kind, piece in runs(text):
            run = paragraph.add_run(piece)
            run.bold = kind == "b"
            run.italic = kind == "i"
            if kind == "code":
                run.font.name = "Consolas"

    for kind, payload in blocks(markdown):
        if kind == "h":
            level, text = payload
            document.add_heading(text, level=0 if level == 1 else level - 1)
        elif kind == "p":
            add_runs(document.add_paragraph(), payload)
        elif kind == "li":
            add_runs(document.add_paragraph(style="List Bullet"), payload)
        elif kind == "ol":
            add_runs(document.add_paragraph(style="List Number"), payload)
        elif kind == "quote":
            add_runs(document.add_paragraph(style="Intense Quote"), payload)
        elif kind == "code":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(payload)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        elif kind == "table" and payload:
            width = max(len(r) for r in payload)
            table = document.add_table(rows=len(payload), cols=width)
            table.style = "Light Grid Accent 1"
            for r, row in enumerate(payload):
                for c in range(width):
                    cell = table.cell(r, c)
                    cell.text = ""
                    add_runs(cell.paragraphs[0], row[c] if c < len(row) else "")
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        elif kind == "hr":
            document.add_paragraph("")
    document.save(str(path))
    return path


# --- PDF -------------------------------------------------------------------------

def _font_files() -> tuple[Path, Path, Path] | None:
    """(regular, bold, italic) TrueType files that cover Turkish."""
    candidates = []
    if sys.platform == "win32":
        fonts = Path(r"C:\Windows\Fonts")
        candidates = [(fonts / "arial.ttf", fonts / "arialbd.ttf", fonts / "ariali.ttf"),
                      (fonts / "segoeui.ttf", fonts / "segoeuib.ttf", fonts / "segoeuii.ttf")]
    elif sys.platform == "darwin":
        sup = Path("/System/Library/Fonts/Supplemental")
        candidates = [(sup / "Arial.ttf", sup / "Arial Bold.ttf", sup / "Arial Italic.ttf")]
    else:
        dejavu = Path("/usr/share/fonts/truetype/dejavu")
        candidates = [(dejavu / "DejaVuSans.ttf", dejavu / "DejaVuSans-Bold.ttf", dejavu / "DejaVuSans-Oblique.ttf")]
    for trio in candidates:
        if all(p.exists() for p in trio):
            return trio
    return None


def to_pdf(markdown: str, path: Path) -> Path:
    try:
        from fpdf import FPDF
    except ImportError:
        raise WriterError("PDF output needs fpdf2 (pip install fpdf2).")

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    fonts = _font_files()
    if fonts:
        pdf.add_font("Body", "", str(fonts[0]))
        pdf.add_font("Body", "B", str(fonts[1]))
        pdf.add_font("Body", "I", str(fonts[2]))
        family = "Body"
        safe = lambda s: s  # noqa: E731
    else:
        family = "Helvetica"
        safe = lambda s: s.encode("latin-1", "replace").decode("latin-1")  # noqa: E731
    mono = "Courier"
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def para(text: str, size: float = 11, indent: str = "") -> None:
        pdf.set_font(family, "", size)
        # fpdf2 understands **bold** and *italic* markers itself.
        body = "".join(
            f"**{p}**" if k == "b" else f"__{p}__" if k == "i" else p
            for k, p in runs(text)
        )
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(width, size * 0.55, safe(indent + body), markdown=True,
                       new_x="LMARGIN", new_y="NEXT")

    counter = 0
    for kind, payload in blocks(markdown):
        if kind != "ol":
            counter = 0
        if kind == "h":
            level, text = payload
            size = {1: 20, 2: 15, 3: 12.5}[level]
            pdf.ln(3 if level > 1 else 0)
            pdf.set_font(family, "B", size)
            pdf.multi_cell(width, size * 0.5, safe(text), new_x="LMARGIN", new_y="NEXT")
            if level == 1:
                pdf.set_draw_color(180, 180, 180)
                pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + width, pdf.get_y() + 1)
            pdf.ln(3)
        elif kind == "p":
            para(payload)
            pdf.ln(2)
        elif kind == "li":
            para(payload, indent="•  ")
            pdf.ln(0.5)
        elif kind == "ol":
            counter += 1
            para(payload, indent=f"{counter}.  ")
            pdf.ln(0.5)
        elif kind == "quote":
            pdf.set_text_color(90, 90, 90)
            para(payload, indent="  ")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
        elif kind == "code":
            pdf.set_font(mono, "", 9)
            pdf.set_fill_color(242, 242, 242)
            pdf.multi_cell(width, 4.6, payload.encode("latin-1", "replace").decode("latin-1"),
                           fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "table" and payload:
            pdf.set_font(family, "", 9.5)
            with pdf.table(text_align="LEFT", line_height=5.5) as table:
                for row_cells in payload:
                    row = table.row()
                    for cell in row_cells:
                        row.cell(safe(re.sub(r"[*_`]", "", cell)))
            pdf.ln(2)
        elif kind == "hr":
            pdf.ln(2)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
            pdf.ln(3)
    pdf.output(str(path))
    return path


def save(markdown: str, formats: tuple[str, ...] = ("docx", "pdf")) -> list[Path]:
    """Write the document in each format. Returns the files written."""
    title = title_of(markdown)
    # Seconds included: a revision made within the same minute used to
    # overwrite the version it revised.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = documents_dir() / f"{_slug(title)}_{stamp}"
    written: list[Path] = []
    errors: list[str] = []
    for fmt in formats:
        try:
            if fmt == "docx":
                written.append(to_docx(markdown, base.with_suffix(".docx")))
            elif fmt == "pdf":
                written.append(to_pdf(markdown, base.with_suffix(".pdf")))
        except WriterError as exc:
            errors.append(str(exc))
        except Exception as exc:  # a typesetting problem should not lose the text
            errors.append(f"{fmt.upper()} failed: {exc}")
    if not written:
        markdown_path = base.with_suffix(".md")
        markdown_path.write_text(markdown, encoding="utf-8")
        written.append(markdown_path)
        if errors:
            raise WriterError("; ".join(errors) + f"\nThe text was saved as {markdown_path}")
    return written
