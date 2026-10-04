"""Gaming (10.0): the games installed on this PC, launching them, the GPU
driver's age, and live numbers for the performance overlay.

The library reads what the launchers themselves keep on disk — Steam's
appmanifest files, Epic's .item manifests, GOG's registry entries — so it
needs no logins and finds games in every Steam library folder, not just the
default one. Launching goes through each launcher's own link (steam://…),
exactly as a desktop shortcut would.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Steam "apps" that aren't games: runtimes, redistributables, Proton.
NOT_GAMES = re.compile(r"redistributable|steamworks|proton|steam linux runtime|directx|vc\+\+|soundtrack|"
                       r"dedicated server|sdk\b|benchmark tool", re.I)


@dataclass
class Game:
    name: str
    source: str            # "Steam", "Epic", "GOG"
    launch: str            # a launcher link, or an .exe path
    folder: str = ""
    size: int = 0
    app_id: str = ""
    updated: float = 0.0

    @property
    def image_url(self) -> str:
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{self.app_id}/header.jpg" if \
            self.source == "Steam" and self.app_id else ""


# --- Steam ---------------------------------------------------------------------------------------

def parse_vdf(text: str) -> dict:
    """Valve's KeyValues text ("key" "value", "key" { … }) as nested dicts."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack = [root]
    key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            stack[-1][key or ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted.replace("\\\\", "\\")
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return root


def steam_root() -> Path | None:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                path = Path(winreg.QueryValueEx(key, "SteamPath")[0])
                if path.exists():
                    return path
        except OSError:
            pass
        for guess in (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
                      Path(r"C:\Program Files\Steam")):
            if guess.exists():
                return guess
        return None
    for guess in (Path.home() / "Library/Application Support/Steam", Path.home() / ".steam/steam",
                  Path.home() / ".local/share/Steam"):
        if guess.exists():
            return guess
    return None


def steam_libraries(root: Path) -> list[Path]:
    folders = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return folders
    for entry in (data.get("libraryfolders") or data.get("LibraryFolders") or {}).values():
        path = entry.get("path") if isinstance(entry, dict) else entry if isinstance(entry, str) else None
        if path and Path(path).exists() and Path(path).resolve() not in {f.resolve() for f in folders}:
            folders.append(Path(path))
    return folders


def steam_games(root: Path | None = None) -> list[Game]:
    root = root or steam_root()
    if root is None:
        return []
    games = []
    for library in steam_libraries(root):
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            try:
                state = parse_vdf(manifest.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
            except OSError:
                continue
            name, app_id = state.get("name", ""), state.get("appid", "")
            if not name or not app_id or NOT_GAMES.search(name):
                continue
            games.append(Game(name=name, source="Steam", launch=f"steam://rungameid/{app_id}", app_id=app_id,
                              folder=str(library / "steamapps" / "common" / state.get("installdir", "")),
                              size=int(state.get("SizeOnDisk") or 0), updated=float(state.get("LastUpdated") or 0)))
    return games


# --- Epic and GOG ----------------------------------------------------------------------------------

EPIC_MANIFESTS = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / \
    "Manifests"


def epic_games(folder: Path | None = None) -> list[Game]:
    games = []
    for item in sorted((folder or EPIC_MANIFESTS).glob("*.item")):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not data.get("DisplayName") or "games" not in [c.lower() for c in data.get("AppCategories", ["games"])]:
            continue
        uri = (f"com.epicgames.launcher://apps/{data.get('CatalogNamespace', '')}%3A{data.get('CatalogItemId', '')}"
               f"%3A{data.get('AppName', '')}?action=launch&silent=true")
        games.append(Game(name=data["DisplayName"], source="Epic", launch=uri, folder=data.get("InstallLocation", ""),
                          size=int(data.get("InstallSize") or 0), app_id=data.get("AppName", "")))
    return games


def gog_games() -> list[Game]:
    if sys.platform != "win32":
        return []
    games = []
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                        values = {winreg.EnumValue(key, j)[0]: winreg.EnumValue(key, j)[1]
                                  for j in range(winreg.QueryInfoKey(key)[1])}
                except OSError:
                    continue
                if values.get("gameName") and values.get("exe"):
                    games.append(Game(name=values["gameName"], source="GOG", launch=values["exe"],
                                      folder=values.get("path", ""), app_id=str(values.get("gameID", ""))))
    except OSError:
        pass
    return games


def library() -> list[Game]:
    found = steam_games() + epic_games() + gog_games()
    unique: dict[str, Game] = {}
    for game in found:
        unique.setdefault(f"{game.source}:{game.app_id or game.name}", game)
    return sorted(unique.values(), key=lambda g: g.name.lower())


def find(games: list[Game], name: str) -> list[Game]:
    words = name.lower().split()
    exact = [g for g in games if g.name.lower() == name.lower().strip()]
    return exact or [g for g in games if all(w in g.name.lower() for w in words)]


def launch(game: Game) -> None:
    if game.launch.lower().endswith(".exe"):
        subprocess.Popen([game.launch], cwd=game.folder or None, creationflags=NO_WINDOW)
    elif sys.platform == "win32":
        os.startfile(game.launch)  # noqa: S606 — the launcher's own link, as a desktop shortcut uses
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", game.launch])


# --- the GPU driver --------------------------------------------------------------------------------

DRIVER_PAGES = {"nvidia": "https://www.nvidia.com/Download/index.aspx",
                "amd": "https://www.amd.com/en/support/download/drivers.html",
                "intel": "https://www.intel.com/content/www/us/en/support/detect.html"}


def nvidia_version(windows_version: str) -> str:
    """Windows reports 31.0.15.5222; NVIDIA calls that 552.22 (the last five digits)."""
    digits = "".join(windows_version.split(".")[-2:])[-5:]
    return f"{digits[:3]}.{digits[3:]}" if len(digits) == 5 and digits.isdigit() else windows_version


def gpu_drivers() -> list[dict]:
    from .ten.system import _ps_date, ps_json

    out = []
    for row in ps_json("Get-CimInstance Win32_VideoController | Select Name, DriverVersion, DriverDate, "
                       "AdapterCompatibility"):
        name = row.get("Name") or "GPU"
        vendor = next((v for v in DRIVER_PAGES if v in f"{name} {row.get('AdapterCompatibility', '')}".lower()), "")
        if not vendor and "radeon" in name.lower():
            vendor = "amd"
        version = row.get("DriverVersion") or ""
        date = _ps_date(row.get("DriverDate"))
        out.append({"name": name, "vendor": vendor, "version": version,
                    "shown": nvidia_version(version) if vendor == "nvidia" else version,
                    "date": date, "age_days": (datetime.now() - date).days if date else None,
                    "page": DRIVER_PAGES.get(vendor, "")})
    return out


# --- the overlay's numbers -------------------------------------------------------------------------

def ping(host: str = "1.1.1.1", port: int = 443, timeout: float = 1.5) -> float | None:
    """Round trip to a well-connected server in ms (a TCP handshake: no admin, unlike ICMP)."""
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.perf_counter() - started) * 1000
    except OSError:
        return None


def sample() -> dict:
    """CPU, memory, GPU (NVIDIA's own numbers where present) and network round trip."""
    import psutil

    from .ten import system

    data = {"cpu": psutil.cpu_percent(interval=None), "ram": psutil.virtual_memory().percent,
            "gpu": None, "gpu_temp": None, "vram": None, "ping": ping()}
    gpus = system.nvidia()
    if gpus:
        gpu = gpus[0]
        data.update(gpu=gpu["load"], gpu_temp=gpu["temp"],
                    vram=(gpu["mem_used"] / gpu["mem_total"] * 100) if gpu.get("mem_total") else None)
    return data


def screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            pass
    return 1920, 1080
