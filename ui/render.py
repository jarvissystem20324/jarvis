"""Markdown and syntax highlighting inside the chat log.

Everything used to arrive as flat text, which is fine for a sentence and bad
for the thing this app is mostly used for: a forty-line code answer where the
strings, the keywords and the comments all look identical.

This is a renderer, not a parser. It walks the reply line by line and applies
Tk text tags — fenced blocks get a background and real colouring, headings get
weight, bullets get a bullet. Anything it does not recognise is inserted as
plain text, so a malformed document degrades to exactly what you had before
rather than to an exception or to visible markup.

Colours come from the active theme, so highlighting follows light and dark
without a second palette to maintain.
"""

from __future__ import annotations

import re

# Enough of each language to make code readable. Not a lexer: a lexer for
# eight languages is its own project, and bolding the keywords and colouring
# the strings is most of the benefit.
KEYWORDS = {
    "py": (
        "and as assert async await break class continue def del elif else except "
        "finally for from global if import in is lambda nonlocal not or pass raise "
        "return try while with yield None True False self"
    ),
    "js": (
        "async await break case catch class const continue default delete do else "
        "export extends finally for from function if import in instanceof let new "
        "of return static super switch this throw try typeof var void while yield "
        "null true false undefined"
    ),
    "sh": "if then else fi for while do done case esac function return export local",
}
KEYWORDS["python"] = KEYWORDS["py"]
KEYWORDS["ts"] = KEYWORDS["typescript"] = KEYWORDS["javascript"] = KEYWORDS["js"]
KEYWORDS["bash"] = KEYWORDS["shell"] = KEYWORDS["ps1"] = KEYWORDS["sh"]

_STRING = re.compile(r"""("""  # noqa: W605
                     r'"""(?:.|\n)*?"""'
                     r"|'''(?:.|\n)*?'''"
                     r'|"(?:\\.|[^"\\])*"'
                     r"|'(?:\\.|[^'\\])*'"
                     r"|`(?:\\.|[^`\\])*`"
                     r")")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+\.)\s+(.*)$")
_FENCE = re.compile(r"^\s*```\s*(\S*)\s*$")


def configure_tags(textbox, colors: dict, font_size: int = 14) -> None:
    """Define every tag this module uses. Safe to call again after a theme change."""
    mono = ("Consolas", font_size - 1)
    textbox.tag_config("user", foreground=colors["user"])
    textbox.tag_config("jarvis", foreground=colors["accent"])
    textbox.tag_config("code_bg", background=colors["code_bg"],
                       font=mono, lmargin1=18, lmargin2=18, spacing1=1)
    textbox.tag_config("kw", foreground=colors["kw"], font=(*mono, "bold"))
    textbox.tag_config("str", foreground=colors["str"], font=mono)
    textbox.tag_config("com", foreground=colors["com"], font=(*mono, "italic"))
    textbox.tag_config("num", foreground=colors["num"], font=mono)
    textbox.tag_config("inline", foreground=colors["accent"],
                       font=("Consolas", font_size - 1))
    textbox.tag_config("bold", font=("Segoe UI", font_size, "bold"))
    textbox.tag_config("h", foreground=colors["accent"],
                       font=("Segoe UI", font_size + 3, "bold"), spacing1=6, spacing3=2)
    textbox.tag_config("bullet", lmargin1=16, lmargin2=32)
    textbox.tag_config("fence", foreground=colors["muted"],
                       font=("Consolas", font_size - 3))
    textbox.tag_config("found", background=colors["accent"], foreground=colors["bg"])


def insert(textbox, text: str, colors: dict) -> None:
    """Write `text` into the widget with markdown and code highlighting."""
    in_code = False
    language = ""
    for raw in text.split("\n"):
        fence = _FENCE.match(raw)
        if fence:
            if in_code:
                in_code, language = False, ""
                textbox.insert("end", "\n")
            else:
                in_code = True
                language = (fence.group(1) or "").lower()
                label = language or "code"
                # The info line is often a file path, which is worth seeing.
                textbox.insert("end", f"{label}\n", "fence")
            continue

        if in_code:
            _code_line(textbox, raw + "\n", language)
            continue

        heading = _HEADING.match(raw)
        if heading:
            textbox.insert("end", heading.group(2) + "\n", "h")
            continue

        bullet = _BULLET.match(raw)
        if bullet:
            textbox.insert("end", f"{bullet.group(1)}• ", "bullet")
            _inline(textbox, bullet.group(2) + "\n", ("bullet",))
            continue

        numbered = _NUMBERED.match(raw)
        if numbered:
            textbox.insert("end", f"{numbered.group(1)}{numbered.group(2)} ", "bullet")
            _inline(textbox, numbered.group(3) + "\n", ("bullet",))
            continue

        _inline(textbox, raw + "\n", ())

    if in_code:
        # An unclosed fence means a reply that was cut off. Leave it readable.
        textbox.insert("end", "\n")


def _inline(textbox, line: str, base: tuple) -> None:
    """Insert one prose line, handling `code` and **bold**."""
    position = 0
    pattern = re.compile(f"{_INLINE_CODE.pattern}|{_BOLD.pattern}")
    for match in pattern.finditer(line):
        if match.start() > position:
            textbox.insert("end", line[position:match.start()], base)
        code, bold = match.group(1), match.group(2)
        if code is not None:
            textbox.insert("end", code, base + ("inline",))
        else:
            textbox.insert("end", bold, base + ("bold",))
        position = match.end()
    if position < len(line):
        textbox.insert("end", line[position:], base)


def _code_line(textbox, line: str, language: str) -> None:
    """Insert one line of code, colouring strings, comments and keywords."""
    words = set(KEYWORDS.get(language, "").split())

    comment_at = None
    marker = "#" if language in {"py", "python", "sh", "bash", "shell", "ps1", "yaml"} else "//"
    # Only treat it as a comment when it is not inside a string.
    spans = [m.span() for m in _STRING.finditer(line)]
    index = line.find(marker)
    while index != -1:
        if not any(start <= index < end for start, end in spans):
            comment_at = index
            break
        index = line.find(marker, index + 1)

    body = line if comment_at is None else line[:comment_at]
    comment = "" if comment_at is None else line[comment_at:]

    position = 0
    for match in _STRING.finditer(body):
        if match.start() > position:
            _plain_code(textbox, body[position:match.start()], words)
        textbox.insert("end", match.group(0), ("code_bg", "str"))
        position = match.end()
    if position < len(body):
        _plain_code(textbox, body[position:], words)
    if comment:
        textbox.insert("end", comment, ("code_bg", "com"))


def _plain_code(textbox, fragment: str, words: set) -> None:
    for token in re.split(r"(\W)", fragment):
        if not token:
            continue
        if token in words:
            textbox.insert("end", token, ("code_bg", "kw"))
        elif _NUMBER.fullmatch(token):
            textbox.insert("end", token, ("code_bg", "num"))
        else:
            textbox.insert("end", token, ("code_bg",))
