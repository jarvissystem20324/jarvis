"""Tidy a messy folder — Downloads, usually — into sensible subfolders.

    /tidy                 show the plan for Downloads (nothing moves yet)
    /tidy <folder>        the plan for another folder
    /tidy go              do it (asks first)
    /tidy undo            put every file back where it was

Only files directly inside the folder are moved, never folders, never
anything already sorted, and never a file changed in the last ten minutes
(it may still be downloading). Nothing is deleted or renamed except to avoid
overwriting: a clash becomes "name (2).ext". Every move is written to a
journal first, so /tidy undo can reverse the whole run.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .config import get_data_dir

JOURNAL = "tidy-journal.json"
RECENT_SECONDS = 600

CATEGORIES: dict[str, set[str]] = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg", ".tiff", ".ico"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".epub"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods", ".numbers"},
    "Presentations": {".ppt", ".pptx", ".key", ".odp"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".dmg", ".pkg", ".apk"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "Video": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".java", ".c", ".cpp", ".cs",
             ".go", ".rs", ".ipynb", ".sql", ".sh", ".ps1", ".bat"},
    "Fonts": {".ttf", ".otf", ".woff", ".woff2"},
    "Torrents": {".torrent"},
}
SKIP = {".crdownload", ".part", ".partial", ".tmp", ".download", ".ini", ".lnk"}


def category_of(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in SKIP or not suffix:
        return None
    for name, suffixes in CATEGORIES.items():
        if suffix in suffixes:
            return name
    return "Other"


def plan(folder: Path, now: float | None = None) -> list[tuple[Path, Path]]:
    """(from, to) for every file that would move. Moves nothing."""
    now = now or time.time()
    moves: list[tuple[Path, Path]] = []
    taken: set[Path] = set()
    for path in sorted(Path(folder).iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            if now - path.stat().st_mtime < RECENT_SECONDS:
                continue
        except OSError:
            continue
        category = category_of(path)
        if category is None:
            continue
        target = folder / category / path.name
        counter = 2
        while target.exists() or target in taken:
            target = folder / category / f"{path.stem} ({counter}){path.suffix}"
            counter += 1
        taken.add(target)
        moves.append((path, target))
    return moves


def describe(folder: Path, moves: list[tuple[Path, Path]]) -> str:
    if not moves:
        return f"{folder} is already tidy — nothing to move."
    counts: dict[str, int] = {}
    for _src, dst in moves:
        counts[dst.parent.name] = counts.get(dst.parent.name, 0) + 1
    lines = [f"Plan for {folder}: {len(moves)} file(s) into {len(counts)} folder(s)"]
    lines += [f"  {name:<14} {count:>4}" for name, count in sorted(counts.items(), key=lambda kv: -kv[1])]
    examples = [f"  {s.name}  →  {d.parent.name}/" for s, d in moves[:6]]
    lines += ["", "For example:", *examples]
    lines += ["", "Nothing has moved. '/tidy go' does it (you'll be asked); '/tidy undo' reverses it."]
    return "\n".join(lines)


def apply(moves: list[tuple[Path, Path]]) -> tuple[int, list[str]]:
    """Move the files, journalling each move before it happens."""
    journal_path = get_data_dir() / JOURNAL
    journal: list[list[str]] = []
    failed: list[str] = []
    for src, dst in moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                failed.append(f"{src.name}: target appeared meanwhile")
                continue
            journal.append([str(src), str(dst)])
            journal_path.write_text(json.dumps({"at": time.time(), "moves": journal}), encoding="utf-8")
            shutil.move(str(src), str(dst))
        except OSError as exc:
            journal = journal[:-1] if journal and journal[-1][0] == str(src) else journal
            failed.append(f"{src.name}: {exc}")
    journal_path.write_text(json.dumps({"at": time.time(), "moves": journal}), encoding="utf-8")
    return len(journal), failed


def undo() -> str:
    journal_path = get_data_dir() / JOURNAL
    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "There is no tidy to undo."
    moves = data.get("moves") or []
    if not moves:
        return "There is no tidy to undo."
    restored, failed, emptied = 0, [], set()
    for src, dst in reversed(moves):
        src_path, dst_path = Path(src), Path(dst)
        if not dst_path.exists():
            failed.append(f"{dst_path.name}: no longer there")
            continue
        if src_path.exists():
            failed.append(f"{src_path.name}: something else is now in its old place")
            continue
        try:
            shutil.move(str(dst_path), str(src_path))
            restored += 1
            emptied.add(dst_path.parent)
        except OSError as exc:
            failed.append(f"{dst_path.name}: {exc}")
    for folder in emptied:
        try:
            folder.rmdir()          # only succeeds if JARVIS emptied it
        except OSError:
            pass
    journal_path.unlink(missing_ok=True)
    text = f"Put {restored} file(s) back."
    if failed:
        text += "\nCould not restore:\n" + "\n".join(f"  {f}" for f in failed[:10])
    return text
