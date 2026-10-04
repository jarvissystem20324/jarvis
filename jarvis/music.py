"""Music (10.0): your own songs, playlists, radio, and a drum machine.

Playback goes through Windows Media Player's engine (WMPlayer.OCX over COM),
which every Windows 10/11 has: it plays MP3, M4A, WMA, WAV and FLAC, and
internet radio streams, with pause, seeking and volume, and nothing to
install. A COM object belongs to the thread that made it, so the player
lives on a thread of its own with its own message pump; the chat, the Music
page and global shortcuts all hand it commands through a queue. The queue
logic (next, shuffle, repeat, carrying on when a song ends) is plain Python
over a small backend, so it is tested with a fake one.

Radio stations come from radio-browser.info, a free community directory, so
the list stays current instead of being a hard-coded set of URLs that rot.
The drum machine synthesises its own sounds with numpy — no samples shipped.
"""

from __future__ import annotations

import queue
import random
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import kit

AUDIO_EXT = {".mp3", ".m4a", ".wma", ".wav", ".flac", ".aac", ".ogg", ".opus"}
PLAYLISTS = kit.Store("playlists.json", {})
MUSIC_SETTINGS = kit.Store("music.json", {"folders": [], "volume": 70, "shuffle": False, "repeat": "off",
                                          "favorites": []})

# --- the library ------------------------------------------------------------------------------


def music_folders() -> list[Path]:
    from .pc import known_folder

    folders = [known_folder("music") or Path.home() / "Music"]
    folders += [Path(f) for f in MUSIC_SETTINGS.load().get("folders", [])]
    seen, out = set(), []
    for folder in folders:
        key = str(folder).lower()
        if key not in seen and folder.is_dir():
            seen.add(key)
            out.append(folder)
    return out


def scan(folders: list[Path] | None = None, limit: int = 20000, depth: int = 5) -> list[Path]:
    """Every song under the music folders, sorted by name."""
    found: list[Path] = []

    def walk(path: Path, level: int) -> None:
        try:
            entries = list(path.iterdir())
        except OSError:
            return
        for entry in entries:
            if len(found) >= limit:
                return
            try:
                if entry.is_dir():
                    if level < depth and not entry.name.startswith("."):
                        walk(entry, level + 1)
                elif entry.suffix.lower() in AUDIO_EXT:
                    found.append(entry)
            except OSError:
                continue

    for folder in folders if folders is not None else music_folders():
        walk(Path(folder), 0)
    return sorted(found, key=lambda p: p.stem.lower())


_library: tuple[float, list[Path]] | None = None


def library(refresh: bool = False) -> list[Path]:
    """The scanned library, kept for ten minutes (a big one takes seconds to walk)."""
    global _library
    if refresh or _library is None or time.time() - _library[0] > 600:
        _library = (time.time(), scan())
    return _library[1]


def describe(path: Path) -> tuple[str, str]:
    """(title, artist) from the file name: "Artist - Title.mp3", "01 Title.mp3"."""
    stem = re.sub(r"^\d{1,3}[\s._-]+", "", Path(path).stem).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()
    return stem, Path(path).parent.name if Path(path).parent.name.lower() not in {"music", "müzik"} else ""


def _norm(text: str) -> str:
    return text.lower().translate(str.maketrans("çğıöşüâî", "cgiosuai"))


def search(songs: list[Path], query: str) -> list[Path]:
    words = _norm(query).split()
    if not words:
        return list(songs)
    return [s for s in songs if all(w in _norm(f"{s.parent.name} {s.stem}") for w in words)]


# --- playlists ---------------------------------------------------------------------------------

def playlist_names() -> list[str]:
    return sorted(PLAYLISTS.load(), key=str.lower)


def playlist(name: str) -> list[Path]:
    lists = PLAYLISTS.load()
    key = next((k for k in lists if k.lower() == name.strip().lower()), None)
    return [Path(p) for p in lists.get(key, [])] if key else []


def save_playlist(name: str, songs: list[Path]) -> None:
    lists = PLAYLISTS.load()
    key = next((k for k in lists if k.lower() == name.strip().lower()), name.strip())
    lists[key] = [str(s) for s in songs]
    PLAYLISTS.save(lists)


def delete_playlist(name: str) -> bool:
    lists = PLAYLISTS.load()
    key = next((k for k in lists if k.lower() == name.strip().lower()), None)
    if key is None:
        return False
    del lists[key]
    PLAYLISTS.save(lists)
    return True


# --- radio -------------------------------------------------------------------------------------

RADIO_MIRRORS = ("de1", "nl1", "at1")
_radio_cache: dict[str, tuple[float, list]] = {}


def _radio(path: str, params: dict) -> list[dict]:
    from . import __version__

    last: Exception | None = None
    for mirror in RADIO_MIRRORS:
        try:
            rows = kit.get_json(f"https://{mirror}.api.radio-browser.info/json/{path}", params,
                               headers={"User-Agent": f"JARVIS/{__version__}"})
            return [station(r) for r in rows if r.get("url_resolved") or r.get("url")]
        except Exception as exc:    # try the next mirror
            last = exc
    raise kit.KitError(f"The radio directory didn't answer ({last}).")


def station(row: dict) -> dict:
    return {"id": row.get("stationuuid", ""), "name": (row.get("name") or "").strip(),
            "url": row.get("url_resolved") or row.get("url"), "tags": row.get("tags", ""),
            "country": row.get("countrycode", ""), "codec": row.get("codec", ""), "bitrate": row.get("bitrate", 0)}


def top_stations(country: str = "TR", limit: int = 60) -> list[dict]:
    """The most listened-to stations in a country (cached for a day)."""
    key = f"top:{country}"
    cached = _radio_cache.get(key)
    if cached and time.time() - cached[0] < 86400:
        return cached[1]
    rows = _radio("stations/search", {"countrycode": country, "order": "clickcount", "reverse": "true",
                                      "limit": limit, "hidebroken": "true"})
    _radio_cache[key] = (time.time(), rows)
    return rows


def find_stations(query: str, limit: int = 30) -> list[dict]:
    """By name first in Türkiye, then anywhere by name, then by genre."""
    query = query.strip()
    rows = _radio("stations/search", {"name": query, "countrycode": "TR", "order": "clickcount",
                                      "reverse": "true", "limit": limit, "hidebroken": "true"})
    if not rows:
        rows = _radio("stations/search", {"name": query, "order": "clickcount", "reverse": "true",
                                          "limit": limit, "hidebroken": "true"})
    if not rows:
        rows = _radio("stations/search", {"tag": query.lower(), "order": "clickcount", "reverse": "true",
                                          "limit": limit, "hidebroken": "true"})
    return rows


# --- the player --------------------------------------------------------------------------------

PLAYING, PAUSED, STOPPED, ENDED, BUFFERING = "playing", "paused", "stopped", "ended", "buffering"


class Backend:
    """What the player needs from an audio engine."""

    def load(self, url: str) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def state(self) -> str: return STOPPED
    def position(self) -> float: return 0.0
    def duration(self) -> float: return 0.0
    def seek(self, seconds: float) -> None: ...
    def set_volume(self, volume: int) -> None: ...
    def pump(self) -> None: ...
    def close(self) -> None: ...


class WMPBackend(Backend):
    """Windows Media Player's engine; made and used on the player thread only."""

    STATES = {1: STOPPED, 2: PAUSED, 3: PLAYING, 6: BUFFERING, 7: BUFFERING, 8: ENDED, 9: BUFFERING,
              10: STOPPED, 11: BUFFERING}

    def __init__(self) -> None:
        import ctypes

        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        self._ctypes = ctypes
        self.wmp = comtypes.client.CreateObject("WMPlayer.OCX")
        self.wmp.settings.autoStart = False
        self._msg = ctypes.create_string_buffer(64)

    def load(self, url: str) -> None:
        self.wmp.URL = url

    def play(self) -> None:
        self.wmp.controls.play()

    def pause(self) -> None:
        self.wmp.controls.pause()

    def stop(self) -> None:
        self.wmp.controls.stop()

    def state(self) -> str:
        return self.STATES.get(int(self.wmp.playState), STOPPED)

    def position(self) -> float:
        return float(self.wmp.controls.currentPosition or 0.0)

    def duration(self) -> float:
        media = self.wmp.currentMedia
        return float(media.duration or 0.0) if media is not None else 0.0

    def seek(self, seconds: float) -> None:
        self.wmp.controls.currentPosition = max(0.0, seconds)

    def set_volume(self, volume: int) -> None:
        self.wmp.settings.volume = int(max(0, min(100, volume)))

    def pump(self) -> None:
        # The COM object does its work through window messages on this thread.
        user32 = self._ctypes.windll.user32
        while user32.PeekMessageW(self._msg, None, 0, 0, 1):
            user32.TranslateMessage(self._msg)
            user32.DispatchMessageW(self._msg)

    def close(self) -> None:
        try:
            self.wmp.close()
        except Exception:
            pass


class Player:
    """The queue and the controls. Thread-safe: every call is queued for the
    player thread, and `now()` reads a snapshot it keeps up to date."""

    def __init__(self, backend_factory=None, threaded: bool = True) -> None:
        self._factory = backend_factory or WMPBackend
        self._threaded = threaded
        self._commands: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.backend: Backend | None = None
        self.items: list[dict] = []          # {"kind": "song"|"radio", "url", "title", "artist"}
        self.index = -1
        self.order: list[int] = []
        settings = MUSIC_SETTINGS.load()
        self.shuffle = bool(settings.get("shuffle"))
        self.repeat = settings.get("repeat", "off")
        self.volume = int(settings.get("volume", 70))
        self._wanted = STOPPED               # what the user asked for, as opposed to what the engine says
        self._snapshot = {"state": STOPPED, "item": None, "position": 0.0, "duration": 0.0}
        self.error = ""

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    # --- called from anywhere ---------------------------------------------------------------
    def do(self, name: str, *args) -> None:
        if not self._threaded:
            self._run(name, args)
            return
        self._commands.put((name, args))
        self._ensure_thread()

    def play_items(self, items: list[dict], start: int = 0) -> None:
        self.do("set_queue", items, start)

    def play_songs(self, songs: list[Path], start: int = 0) -> None:
        self.play_items([song_item(s) for s in songs], start)

    def play_station(self, station_row: dict) -> None:
        self.play_items([{"kind": "radio", "url": station_row["url"], "title": station_row["name"],
                          "artist": station_row.get("tags", "").split(",")[0], "id": station_row.get("id", "")}])

    def now(self) -> dict:
        with self._lock:
            return dict(self._snapshot, shuffle=self.shuffle, repeat=self.repeat, volume=self.volume,
                        count=len(self.items), error=self.error)

    def shutdown(self) -> None:
        if self._thread is not None:
            self._commands.put(("quit", ()))
            self._thread.join(timeout=2)
            self._thread = None

    # --- the player thread -------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-music")
            self._thread.start()

    def _loop(self) -> None:
        try:
            self.backend = self._factory()
            self.backend.set_volume(self.volume)
        except Exception as exc:
            with self._lock:
                self.error = f"Music playback isn't available here ({exc})."
            self.backend = None
        while True:
            try:
                name, args = self._commands.get(timeout=0.1)
            except queue.Empty:
                name = None
            if name == "quit":
                if self.backend is not None:
                    self.backend.stop()
                    self.backend.close()
                return
            if name is not None:
                self._run(name, args)
            self.tick()

    def _engine(self) -> Backend | None:
        if self.backend is None and not self._threaded:
            self.backend = self._factory()
            self.backend.set_volume(self.volume)
        return self.backend

    def _run(self, name: str, args: tuple) -> None:
        engine = self._engine()
        if engine is None:
            return
        try:
            getattr(self, "_cmd_" + name)(engine, *args)
        except Exception as exc:          # a bad file or stream must not kill the thread
            with self._lock:
                self.error = str(exc)[:200]

    def _cmd_set_queue(self, engine: Backend, items: list[dict], start: int) -> None:
        self.items = list(items)
        self._reorder(keep=start)
        self._start(engine, self.order.index(start) if start in self.order else 0)

    def _cmd_add(self, engine: Backend, items: list[dict]) -> None:
        self.items += items
        self.order += list(range(len(self.items) - len(items), len(self.items)))
        if self._wanted == STOPPED and self.index < 0:
            self._start(engine, 0)

    def _cmd_toggle(self, engine: Backend) -> None:
        if self._wanted == PLAYING:
            self._cmd_pause(engine)
        else:
            self._cmd_resume(engine)

    def _cmd_pause(self, engine: Backend) -> None:
        if self._wanted == PLAYING:
            engine.pause()
            self._wanted = PAUSED

    def _cmd_resume(self, engine: Backend) -> None:
        if self.index < 0 and self.items:
            self._start(engine, 0)
        elif self.index >= 0:
            engine.play()
            self._wanted = PLAYING

    def _cmd_stop(self, engine: Backend) -> None:
        engine.stop()
        self._wanted = STOPPED

    def _cmd_next(self, engine: Backend) -> None:
        self._advance(engine, user=True)

    def _cmd_previous(self, engine: Backend) -> None:
        if engine.position() > 4 or self.index <= 0:      # like every player: first back to the start
            engine.seek(0)
            if self._wanted != PLAYING:
                engine.play()
                self._wanted = PLAYING
            return
        self._start(engine, self.index - 1)

    def _cmd_seek(self, engine: Backend, seconds: float) -> None:
        engine.seek(seconds)

    def _cmd_volume(self, engine: Backend, volume: int) -> None:
        self.volume = int(max(0, min(100, volume)))
        engine.set_volume(self.volume)
        self._remember()

    def _cmd_shuffle(self, engine: Backend, on: bool) -> None:
        self.shuffle = bool(on)
        self._remember()
        if not self.items:
            return
        current = self.order[self.index] if 0 <= self.index < len(self.order) else 0
        self._reorder(keep=current)
        self.index = self.order.index(current) if self.index >= 0 else -1

    def _cmd_repeat(self, engine: Backend, mode: str) -> None:
        self.repeat = mode if mode in {"off", "all", "one"} else "off"
        self._remember()

    def _reorder(self, keep: int = 0) -> None:
        self.order = list(range(len(self.items)))
        if self.shuffle and len(self.order) > 1:
            rest = [i for i in self.order if i != keep]
            random.shuffle(rest)
            self.order = [keep] + rest

    def _start(self, engine: Backend, position: int) -> None:
        if not self.items:
            return
        self.index = max(0, min(position, len(self.order) - 1))
        item = self.items[self.order[self.index]]
        engine.load(item["url"])
        engine.play()
        self._wanted = PLAYING
        with self._lock:
            self.error = ""
            self._snapshot.update(item=item, position=0.0, duration=0.0, state=BUFFERING)

    def _advance(self, engine: Backend, user: bool = False) -> None:
        if not self.items:
            return
        if self.repeat == "one" and not user:
            self._start(engine, self.index)
            return
        if self.index + 1 < len(self.order):
            self._start(engine, self.index + 1)
        elif self.repeat == "all" or user:
            if self.shuffle:
                self._reorder(keep=self.order[self.index])
                self.order = self.order[1:] + self.order[:1]
            self._start(engine, 0)
        else:
            engine.stop()
            self._wanted = STOPPED

    def tick(self) -> None:
        """Keep the snapshot fresh and carry on to the next song when one ends."""
        engine = self.backend
        if engine is None:
            return
        engine.pump()
        state = engine.state()
        item = self.items[self.order[self.index]] if 0 <= self.index < len(self.order) else None
        if self._wanted == PLAYING and state == ENDED and item is not None and item["kind"] == "song":
            self._advance(engine)
            return
        if self._wanted == PLAYING and state == STOPPED and item is not None and item["kind"] == "song":
            duration = engine.duration()
            if duration and engine.position() == 0 and self._snapshot.get("position", 0) > duration - 2:
                self._advance(engine)       # some files report Stopped rather than Ended
                return
        with self._lock:
            self._snapshot.update(state=state if self._wanted != STOPPED else STOPPED, item=item,
                                  position=engine.position(), duration=engine.duration())

    def _remember(self) -> None:
        settings = MUSIC_SETTINGS.load()
        settings.update(volume=self.volume, shuffle=self.shuffle, repeat=self.repeat)
        MUSIC_SETTINGS.save(settings)


def song_item(path: Path) -> dict:
    title, artist = describe(path)
    return {"kind": "song", "url": str(path), "title": title, "artist": artist}


player = Player()


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else \
        f"{seconds // 60}:{seconds % 60:02d}"


# --- the drum machine --------------------------------------------------------------------------

RATE = 44100
INSTRUMENTS = ("kick", "snare", "clap", "hat", "openhat", "tom", "doum", "tek")
LABELS = {"kick": "Kick", "snare": "Snare", "clap": "Clap", "hat": "Hi-hat", "openhat": "Open hat", "tom": "Tom",
          "doum": "Darbuka düm", "tek": "Darbuka tek"}


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def _noise(seconds: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, int(seconds * RATE))


def _highpass(x: np.ndarray, times: int = 1) -> np.ndarray:
    for _ in range(times):
        x = np.diff(x, prepend=0.0)
    return x


def _lowpass(x: np.ndarray, width: int) -> np.ndarray:
    return np.convolve(x, np.ones(width) / width, mode="same")


def synth(name: str) -> np.ndarray:
    """One hit of an instrument, made from sine sweeps and shaped noise."""
    if name == "kick":
        t = _t(0.45)
        freq = 45 + 110 * np.exp(-t * 35)
        body = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 7)
        click = _noise(0.003, 1) * 0.4
        body[:len(click)] += click
        out = body
    elif name == "snare":
        t = _t(0.25)
        rattle = _highpass(_noise(0.25, 2)) * np.exp(-t * 18) * 0.7
        tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30) * 0.6
        out = rattle + tone
    elif name == "clap":
        t = _t(0.3)
        noise = _lowpass(_highpass(_noise(0.3, 3)), 3)
        envelope = np.zeros_like(t)
        for start in (0.0, 0.011, 0.022):
            envelope = np.maximum(envelope, np.where(t >= start, np.exp(-(t - start) * 90), 0))
        envelope = np.maximum(envelope, np.where(t >= 0.03, np.exp(-(t - 0.03) * 16) * 0.5, 0))
        out = noise * envelope * 1.4
    elif name == "hat":
        t = _t(0.07)
        out = _highpass(_noise(0.07, 4), 2) * np.exp(-t * 70) * 0.35
    elif name == "openhat":
        t = _t(0.4)
        out = _highpass(_noise(0.4, 5), 2) * np.exp(-t * 9) * 0.3
    elif name == "tom":
        t = _t(0.4)
        freq = 100 + 45 * np.exp(-t * 12)
        out = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 9) * 0.8
    elif name == "doum":
        t = _t(0.45)
        freq = 88 + 20 * np.exp(-t * 20)
        out = (np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 8) +
               _lowpass(_noise(0.45, 6), 30) * np.exp(-t * 25) * 0.5)
    elif name == "tek":
        t = _t(0.12)
        ping = np.sin(2 * np.pi * 980 * t) * np.exp(-t * 55) * 0.5
        slap = _highpass(_noise(0.12, 7)) * np.exp(-t * 60) * 0.5
        out = ping + slap
    else:
        raise ValueError(f"No instrument called {name}.")
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak).astype(np.float32)


# Patterns: one string per instrument, one character per step: X accent,
# x hit, . rest. `unit` is steps per beat (4: sixteenths, 2: eighths).
PRESETS: dict[str, dict] = {
    "rock": {"bpm": 112, "unit": 4, "tracks": {
        "kick": "X.......X.x.....", "snare": "....X.......X...", "hat": "x.x.x.x.x.x.x.x."}},
    "pop": {"bpm": 100, "unit": 4, "tracks": {
        "kick": "X...x...X...x...", "clap": "....X.......X...", "hat": "..x...x...x...x."}},
    "hip-hop": {"bpm": 90, "unit": 4, "swing": 0.14, "tracks": {
        "kick": "X......x..X.....", "snare": "....X.......X...", "hat": "x.x.x.x.x.x.x.xx"}},
    "house": {"bpm": 124, "unit": 4, "tracks": {
        "kick": "X...X...X...X...", "clap": "....X.......X...", "openhat": "..x...x...x...x.",
        "hat": "x...x...x...x..."}},
    "trap": {"bpm": 140, "unit": 4, "tracks": {
        "kick": "X.........X..x..", "snare": "........X.......", "hat": "x.x.x.xxx.x.x.xx",
        "openhat": "...............x"}},
    "reggaeton": {"bpm": 95, "unit": 4, "tracks": {
        "kick": "X...X...X...X...", "snare": "...x..x....x..x.", "hat": "x.x.x.x.x.x.x.x."}},
    "düm tek (maqsum)": {"bpm": 100, "unit": 4, "tracks": {
        "doum": "X.......X.......", "tek": "..x...x.....x...", "hat": "....x.......x..."}},
    "karşılama 9/8": {"bpm": 120, "unit": 2, "tracks": {
        "doum": "X...X....", "tek": "..x...xx."}},
}


def pattern_steps(pattern: dict) -> int:
    return max((len(row) for row in pattern["tracks"].values()), default=16)


def render(pattern: dict, bars: int = 1, bpm: float | None = None) -> np.ndarray:
    """`bars` times through the pattern as one mono buffer, loop-ready."""
    bpm = float(bpm or pattern.get("bpm", 100))
    steps = pattern_steps(pattern)
    step = 60.0 / bpm / pattern.get("unit", 4)
    swing = float(pattern.get("swing", 0.0))
    length = int(round(steps * step * RATE))
    out = np.zeros(length * bars + RATE, np.float32)       # room for the last hit's tail
    sounds = {name: synth(name) for name in pattern["tracks"]}
    for bar in range(bars):
        for name, row in pattern["tracks"].items():
            for i, mark in enumerate(row):
                if mark not in "xX":
                    continue
                at = bar * length + int(round((i + (swing if i % 2 else 0)) * step * RATE))
                hit = sounds[name] * (1.0 if mark == "X" else 0.7)
                out[at:at + len(hit)] += hit[:len(out) - at]
    # Fold the tail of the last bar back onto the start so a loop doesn't click.
    tail = out[length * bars:]
    out = out[:length * bars]
    out[:len(tail)] += tail[:len(out)]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out * (0.9 / peak)).astype(np.float32)


class DrumLoop:
    """The drum machine's live sound: one bar on repeat, swapped when you change it."""

    def __init__(self) -> None:
        self.stream = None
        self._loop = np.zeros(1, np.float32)
        self._pos = 0
        self._lock = threading.Lock()
        self.volume = 0.8

    @property
    def playing(self) -> bool:
        return self.stream is not None

    def step_position(self, steps: int) -> int:
        with self._lock:
            return int(self._pos / max(1, len(self._loop)) * steps) % max(1, steps)

    def set(self, buffer: np.ndarray) -> None:
        with self._lock:
            ratio = self._pos / max(1, len(self._loop))
            self._loop = buffer
            self._pos = int(ratio * len(buffer)) % max(1, len(buffer))

    def play(self, buffer: np.ndarray) -> None:
        import sounddevice as sd

        self.set(buffer)
        if self.stream is not None:
            return

        def callback(outdata, frames, _time, _status):
            with self._lock:
                loop = self._loop
                index = (self._pos + np.arange(frames)) % len(loop)
                self._pos = (self._pos + frames) % len(loop)
                outdata[:, 0] = loop[index] * self.volume

        self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="float32", callback=callback,
                                      blocksize=1024)
        self.stream.start()

    def stop(self) -> None:
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._pos = 0


drums = DrumLoop()
