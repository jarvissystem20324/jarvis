"""Controlling this PC: media and volume, opening apps, finding files, and
saying why it is slow.

Everything here acts only on what you typed or said — the AI never reaches
these functions on its own — and each is narrow on purpose:

- Media and volume press the same media keys your keyboard has. Nothing is
  installed and nothing hooks into other programs.
- Opening an app uses the Start menu's own list, so "open spotify" launches
  exactly what clicking it in Start would, and nothing that is not there.
- The file finder only reads names and dates in your own folders (Desktop,
  Documents, Downloads, Pictures, Music, Videos, OneDrive). It never opens
  a file to look inside, and nothing it finds is sent anywhere.
- PC status reads counters. Only the summary — process names and numbers —
  goes to the AI to be explained, and only when you ask why.
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --- media and volume ------------------------------------------------------

VK = {
    "play": 0xB3, "pause": 0xB3, "toggle": 0xB3, "next": 0xB0, "previous": 0xB1,
    "stop": 0xB2, "mute": 0xAD, "down": 0xAE, "up": 0xAF,
}


def _press(vk: int, times: int = 1) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)      # KEYEVENTF_KEYUP


def media(action: str) -> str:
    action = action.lower().strip()
    aliases = {"resume": "play", "skip": "next", "prev": "previous", "back": "previous",
               "unmute": "mute"}
    action = aliases.get(action, action)
    if action not in VK:
        return "Media: play, pause, next, previous, stop, mute."
    if IS_WINDOWS:
        _press(VK[action])
    elif IS_MACOS:
        script = {"play": "playpause", "pause": "playpause", "toggle": "playpause",
                  "next": "next track", "previous": "previous track", "stop": "pause"}.get(action)
        if action == "mute":
            _osascript("set volume output muted not (output muted of (get volume settings))")
        elif script:
            for app in ("Spotify", "Music"):
                _osascript(f'if application "{app}" is running then tell application "{app}" to {script}')
    else:
        return "Media keys are only wired up on Windows and macOS."
    words = {"play": "Play/pause", "pause": "Play/pause", "toggle": "Play/pause",
             "next": "Next track", "previous": "Previous track", "stop": "Stopped",
             "mute": "Mute toggled", "up": "Volume up", "down": "Volume down"}
    return f"{words[action]}."


def set_volume(level: int) -> str:
    """Set the master volume to 0–100.

    Windows' volume keys move it 2% a press, so fifty presses down reaches
    zero from anywhere and then level/2 presses up lands on the target —
    exact, with no audio API and nothing installed.
    """
    level = max(0, min(100, int(level)))
    if IS_WINDOWS:
        _press(VK["down"], 50)
        _press(VK["up"], round(level / 2))
    elif IS_MACOS:
        _osascript(f"set volume output volume {level}")
    else:
        return "Setting the volume is only wired up on Windows and macOS."
    return f"Volume set to {level}%."


def volume_step(direction: str, steps: int = 5) -> str:
    if IS_WINDOWS:
        _press(VK["up" if direction == "up" else "down"], steps)
    elif IS_MACOS:
        sign = "+" if direction == "up" else "-"
        _osascript(f"set volume output volume ((output volume of (get volume settings)) {sign} {steps * 2})")
    return f"Volume {'up' if direction == 'up' else 'down'}."


def _osascript(script: str) -> None:
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


# --- known folders -----------------------------------------------------------

_FOLDER_IDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}
_FOLDER_WORDS = {
    "downloads": "downloads", "download": "downloads", "indirilenler": "downloads",
    "documents": "documents", "docs": "documents", "belgeler": "documents",
    "desktop": "desktop", "masaüstü": "desktop", "pictures": "pictures", "photos": "pictures",
    "resimler": "pictures", "music": "music", "müzik": "music", "videos": "videos",
    "home": "home", "user folder": "home",
}


def known_folder(name: str) -> Path | None:
    """The real location, including when OneDrive has moved Documents."""
    key = _FOLDER_WORDS.get(name.lower().strip(), name.lower().strip())
    if key == "home":
        return Path.home()
    if IS_WINDOWS and key in _FOLDER_IDS:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            guid = uuid.UUID(_FOLDER_IDS[key])
            buffer = ctypes.c_wchar_p()
            raw = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(raw), 0, None, ctypes.byref(buffer)
            ) == 0:
                path = Path(buffer.value)
                ctypes.windll.ole32.CoTaskMemFree(buffer)
                return path
        except Exception:
            pass
    candidate = Path.home() / key.capitalize()
    return candidate if key in _FOLDER_IDS and candidate.exists() else None


def user_folders() -> list[Path]:
    seen: list[Path] = []
    for key in ("desktop", "documents", "downloads", "pictures", "music", "videos"):
        folder = known_folder(key)
        if folder and folder.exists() and folder not in seen:
            seen.append(folder)
    onedrive = os.environ.get("OneDrive")
    if onedrive and Path(onedrive).exists() and Path(onedrive) not in seen:
        seen.append(Path(onedrive))
    return seen


# --- opening apps --------------------------------------------------------------

@dataclass
class App:
    name: str
    launch: str        # AppID on Windows, .app path on macOS


_apps_cache: list[App] | None = None


def installed_apps(refresh: bool = False) -> list[App]:
    """Everything in the Start menu — desktop programs and Store apps alike."""
    global _apps_cache
    if _apps_cache is not None and not refresh:
        return _apps_cache
    apps: list[App] = []
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-StartApps | ForEach-Object { $_.Name + \"`t\" + $_.AppID }"],
                capture_output=True, text=True, timeout=20, encoding="utf-8",
                errors="replace", creationflags=NO_WINDOW,
            ).stdout
            for line in out.splitlines():
                name, _, app_id = line.partition("\t")
                if name.strip() and app_id.strip():
                    apps.append(App(name.strip(), app_id.strip()))
        except Exception:
            pass
    elif IS_MACOS:
        for folder in (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications"):
            if folder.exists():
                apps += [App(p.stem, str(p)) for p in folder.glob("*.app")]
    _apps_cache = apps
    return apps


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def find_app(query: str) -> tuple[App | None, float]:
    """Best Start-menu match and how sure we are (0–1)."""
    wanted = _normal(query)
    if not wanted:
        return None, 0.0
    best, best_score = None, 0.0
    for app in installed_apps():
        name = _normal(app.name)
        if not name:
            continue
        if name == wanted:
            score = 1.0
        elif name.startswith(wanted + " ") or name.split(" ")[0] == wanted:
            score = 0.93
        elif wanted in name.split():
            score = 0.85
        else:
            score = difflib.SequenceMatcher(None, wanted, name).ratio()
        # Uninstallers and help files are never what "open X" means.
        if any(word in name for word in ("uninstall", "readme", "help", "documentation")):
            score -= 0.3
        if score > best_score:
            best, best_score = app, score
    return best, best_score


def open_app(query: str, sure: float = 0.8) -> tuple[bool, str]:
    """(opened?, message). Folders first, then the Start menu."""
    target = query.strip().strip('"')
    target = re.sub(r"^(?:the|my)\s+", "", target, flags=re.I)
    target = re.sub(r"\s+(?:app|application|program|folder)$", "", target, flags=re.I)

    folder = known_folder(target) if target.lower() in _FOLDER_WORDS else None
    path = Path(os.path.expandvars(target)).expanduser()
    if folder is None and path.is_absolute() and path.exists():
        folder = path
    if folder is not None and folder.exists():
        _reveal(folder)
        return True, f"Opened {folder}."

    app, score = find_app(target)
    if app is None or score < sure:
        return False, ""
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.launch}"],
                             creationflags=NO_WINDOW)
        elif IS_MACOS:
            subprocess.Popen(["open", app.launch])
        else:
            return False, ""
    except OSError as exc:
        return True, f"Couldn't open {app.name}: {exc}"
    return True, f"Opening {app.name}."


def _reveal(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(str(path))  # noqa: S606 - a folder or file the user chose
    elif IS_MACOS:
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_path(path: Path) -> None:
    _reveal(path)


# --- finding files -------------------------------------------------------------

KINDS = {
    "pdf": {".pdf"}, "word": {".doc", ".docx", ".odt", ".rtf"}, "doc": {".doc", ".docx"},
    "docx": {".docx"}, "excel": {".xls", ".xlsx", ".csv", ".ods"}, "spreadsheet": {".xls", ".xlsx", ".csv", ".ods"},
    "csv": {".csv"}, "powerpoint": {".ppt", ".pptx"}, "slides": {".ppt", ".pptx"},
    "presentation": {".ppt", ".pptx"}, "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"},
    "photo": {".jpg", ".jpeg", ".png", ".heic", ".webp"}, "picture": {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    "screenshot": {".png", ".jpg"}, "video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
    "music": {".mp3", ".wav", ".flac", ".m4a", ".ogg"}, "song": {".mp3", ".wav", ".flac", ".m4a"},
    "zip": {".zip", ".rar", ".7z"}, "installer": {".exe", ".msi"}, "text": {".txt", ".md"},
    "code": {".py", ".js", ".ts", ".java", ".cs", ".cpp", ".c", ".go", ".rs", ".html", ".css"},
    "python": {".py"},
}
SYNONYMS = {
    "cv": ["cv", "resume", "özgeçmiş", "ozgecmis"], "resume": ["resume", "cv", "özgeçmiş"],
    "invoice": ["invoice", "fatura", "receipt"], "receipt": ["receipt", "invoice", "fiş"],
    "homework": ["homework", "assignment", "ödev", "odev"], "photo": ["photo", "img", "image", "dsc"],
}
_STOP = set(
    "find locate where is are my the a an of for from in on at file files document documents "
    "please called named with that which last this past recent recently i me some any all "
    "bul dosya dosyam benim".split()
)
_SKIP_DIRS = {"appdata", "node_modules", ".git", "venv", ".venv", "__pycache__", "$recycle.bin",
              ".cache", "site-packages", "build", "dist", ".idea", ".vscode"}


@dataclass
class Found:
    path: Path
    modified: float
    size: int
    score: float


def _window(text: str, now: datetime) -> tuple[float, float] | None:
    t = text.lower()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "today" in t:
        return day.timestamp(), now.timestamp()
    if "yesterday" in t:
        return (day - timedelta(days=1)).timestamp(), day.timestamp()
    if "this week" in t:
        return (day - timedelta(days=day.weekday())).timestamp(), now.timestamp()
    if "last week" in t:
        start = day - timedelta(days=day.weekday() + 7)
        return start.timestamp(), (start + timedelta(days=7)).timestamp()
    if "this month" in t:
        return day.replace(day=1).timestamp(), now.timestamp()
    if "last month" in t:
        first = day.replace(day=1)
        previous = (first - timedelta(days=1)).replace(day=1)
        return previous.timestamp(), first.timestamp()
    if "this year" in t:
        return day.replace(month=1, day=1).timestamp(), now.timestamp()
    if "last year" in t:
        return day.replace(year=day.year - 1, month=1, day=1).timestamp(), day.replace(month=1, day=1).timestamp()
    match = re.search(r"last (\d+) days", t)
    if match:
        return (now - timedelta(days=int(match.group(1)))).timestamp(), now.timestamp()
    if "recent" in t:
        return (now - timedelta(days=14)).timestamp(), now.timestamp()
    return None


def parse_find(query: str, now: datetime | None = None):
    """(keyword groups, allowed suffixes or None, time window or None)."""
    now = now or datetime.now()
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ.\-]+", query.lower())
    suffixes: set[str] = set()
    keywords: list[list[str]] = []
    time_words = {"today", "yesterday", "week", "month", "year", "days", "recent", "recently"}
    for word in words:
        if word in KINDS:
            suffixes |= KINDS[word]
            continue
        if word.startswith(".") and len(word) <= 6:
            suffixes.add(word)
            continue
        if word in _STOP or word in time_words or word.isdigit():
            continue
        keywords.append(SYNONYMS.get(word, [word]))
    return keywords, (suffixes or None), _window(query, now)


def find_files(query: str, limit: int = 12, budget: float = 8.0,
               roots: list[Path] | None = None) -> list[Found]:
    keywords, suffixes, window = parse_find(query)
    roots = roots if roots is not None else user_folders()
    found: list[Found] = []
    deadline = time.monotonic() + budget
    for root in roots:
        for folder, dirs, files in os.walk(root):
            if time.monotonic() > deadline:
                break
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                lowered = name.lower()
                suffix = os.path.splitext(lowered)[1]
                if suffixes and suffix not in suffixes:
                    continue
                score = 0.0
                if keywords:
                    stem = re.sub(r"[_\-.]+", " ", lowered)
                    hits = sum(1 for group in keywords if any(k in stem for k in group))
                    if hits == 0:
                        continue
                    score = hits / len(keywords)
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if window and not (window[0] <= stat.st_mtime <= window[1]):
                    continue
                found.append(Found(path, stat.st_mtime, stat.st_size, score))
    found.sort(key=lambda f: (f.score, f.modified), reverse=True)
    return found[:limit]


def describe_found(found: list[Found], query: str) -> str:
    if not found:
        return (f"Nothing matching '{query}' in your Desktop, Documents, Downloads, "
                "Pictures, Music, Videos or OneDrive.")
    lines = [f"{len(found)} match(es) for '{query}':"]
    for index, item in enumerate(found, 1):
        when = datetime.fromtimestamp(item.modified).strftime("%d %b %Y")
        lines.append(f"  {index:>2}. {item.path.name}   ({when}, {_size(item.size)})")
        lines.append(f"      {item.path.parent}")
    lines.append("")
    lines.append("'open 1' opens the first, 'show 1' shows it in its folder.")
    return "\n".join(lines)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def reveal_in_folder(path: Path) -> None:
    if IS_WINDOWS:
        subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=NO_WINDOW)
    else:
        _reveal(path.parent)


# --- why is my PC slow --------------------------------------------------------

def status_snapshot(sample: float = 1.0) -> dict:
    """Counters worth knowing, gathered in about a second."""
    import psutil

    procs = list(psutil.process_iter(["name", "memory_info"]))
    for proc in procs:
        try:
            proc.cpu_percent(None)
        except Exception:
            pass
    overall = psutil.cpu_percent(interval=sample)
    cores = psutil.cpu_count() or 1
    rows = []
    for proc in procs:
        try:
            cpu = proc.cpu_percent(None) / cores
            mem = proc.info["memory_info"].rss if proc.info.get("memory_info") else 0
            rows.append((proc.info.get("name") or "?", cpu, mem))
        except Exception:
            continue
    # One line per program, not per process: Chrome is one thing to a person.
    grouped: dict[str, list[float]] = {}
    for name, cpu, mem in rows:
        if name.lower() in {"system idle process", "idle"}:
            continue
        entry = grouped.setdefault(name, [0.0, 0.0, 0])
        entry[0] += cpu
        entry[1] += mem
        entry[2] += 1
    top_cpu = sorted(grouped.items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    top_mem = sorted(grouped.items(), key=lambda kv: kv[1][1], reverse=True)[:6]

    memory = psutil.virtual_memory()
    system_drive = os.environ.get("SystemDrive", "C:") + "\\" if IS_WINDOWS else "/"
    disk = psutil.disk_usage(system_drive)
    battery = None
    try:
        battery = psutil.sensors_battery()
    except Exception:
        pass
    return {
        "cpu": overall, "cores": cores,
        "memory_used": memory.percent, "memory_total_gb": memory.total / 1_073_741_824,
        "memory_available_gb": memory.available / 1_073_741_824,
        "disk_free_gb": disk.free / 1_073_741_824, "disk_used": disk.percent, "drive": system_drive,
        "battery": (battery.percent, battery.power_plugged) if battery else None,
        "uptime_hours": (time.time() - psutil.boot_time()) / 3600,
        "processes": len(procs),
        "top_cpu": [(n, v[0], int(v[2])) for n, v in top_cpu],
        "top_mem": [(n, v[1] / 1_048_576, int(v[2])) for n, v in top_mem],
    }


def findings(s: dict) -> list[str]:
    """Plain-language problems, worst first. No AI involved."""
    out = []
    if s["memory_used"] >= 90:
        out.append(f"Memory is nearly full ({s['memory_used']:.0f}%). Windows is swapping to disk, which is the most common cause of a slow PC.")
    elif s["memory_used"] >= 80:
        out.append(f"Memory is getting full ({s['memory_used']:.0f}%).")
    if s["cpu"] >= 85:
        out.append(f"The processor is busy ({s['cpu']:.0f}%) — mostly {s['top_cpu'][0][0]}." if s["top_cpu"] else f"The processor is busy ({s['cpu']:.0f}%).")
    if s["disk_free_gb"] < 5 or s["disk_used"] >= 95:
        out.append(f"{s['drive']} is almost full ({s['disk_free_gb']:.1f} GB free). Windows slows down badly under ~10 GB.")
    elif s["disk_free_gb"] < 15:
        out.append(f"{s['drive']} is getting full ({s['disk_free_gb']:.1f} GB free).")
    if s["uptime_hours"] > 24 * 7:
        out.append(f"It hasn't been restarted in {s['uptime_hours'] / 24:.0f} days. A restart clears leaks that build up.")
    if s["battery"] and not s["battery"][1] and s["battery"][0] < 20:
        out.append(f"Battery is at {s['battery'][0]:.0f}% and unplugged; Windows throttles to save power.")
    return out


def format_status(s: dict) -> str:
    lines = [
        "PC status",
        f"  CPU       {s['cpu']:5.0f}%   ({s['cores']} cores, {s['processes']} processes)",
        f"  Memory    {s['memory_used']:5.0f}%   ({s['memory_available_gb']:.1f} of {s['memory_total_gb']:.1f} GB free)",
        f"  Disk {s['drive']:<4} {s['disk_used']:4.0f}%   ({s['disk_free_gb']:.1f} GB free)",
    ]
    if s["battery"]:
        lines.append(f"  Battery   {s['battery'][0]:5.0f}%   ({'plugged in' if s['battery'][1] else 'on battery'})")
    lines.append(f"  Up for    {s['uptime_hours']:.0f} hours")
    lines.append("")
    lines.append("Using the most processor:")
    lines += [f"  {name[:28]:<28} {cpu:5.1f}%" + (f"  ({n} processes)" if n > 1 else "")
              for name, cpu, n in s["top_cpu"] if cpu >= 0.1] or ["  nothing notable"]
    lines.append("Using the most memory:")
    lines += [f"  {name[:28]:<28} {mb:7.0f} MB" + (f"  ({n} processes)" if n > 1 else "")
              for name, mb, n in s["top_mem"]]
    return "\n".join(lines)
