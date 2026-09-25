"""A YouTube video's captions, so JARVIS can summarise it or answer about it.

No key and no download of the video: the captions YouTube already has
(uploaded or auto-generated) are fetched with youtube-transcript-api, and the
title comes from YouTube's public oEmbed endpoint. Timestamps are kept every
thirty seconds or so, so an answer can say *where* in the video something is.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from . import net

_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/|m\.youtube\.com/watch\?(?:.*&)?v=)"
    r"([\w-]{11})"
)
MAX_CHARS = 120_000


class YouTubeError(Exception):
    pass


def video_id(text: str) -> str | None:
    match = _ID.search(text or "")
    if match:
        return match.group(1)
    bare = (text or "").strip()
    return bare if re.fullmatch(r"[\w-]{11}", bare) and re.search(r"\d|[A-Z_-]", bare) else None


def title(vid: str) -> str:
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={vid}", safe="")
    try:
        with net.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        return f"{data.get('title', '').strip()} — {data.get('author_name', '').strip()}".strip(" —")
    except Exception:
        return f"YouTube video {vid}"


def stamp(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _field(piece, name: str, default):
    return piece.get(name, default) if isinstance(piece, dict) else getattr(piece, name, default)


def join(snippets, every: float = 30.0) -> str:
    """Caption pieces as paragraphs, each starting with a [m:ss] stamp."""
    out: list[str] = []
    current: list[str] = []
    started = None
    for piece in snippets:
        text = re.sub(r"\s+", " ", str(_field(piece, "text", ""))).strip()
        start = float(_field(piece, "start", 0))
        if not text or text in {"[Music]", "[Müzik]", "[Applause]"}:
            continue
        if started is None:
            started = start
        if start - started >= every and current:
            out.append(f"[{stamp(started)}] " + " ".join(current))
            current, started = [], start
        current.append(text)
    if current:
        out.append(f"[{stamp(started or 0)}] " + " ".join(current))
    return "\n".join(out)


def transcript(vid: str, languages: tuple[str, ...] = ("en", "tr")) -> tuple[str, str]:
    """(language code, timestamped text). Raises YouTubeError."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise YouTubeError("YouTube summaries need youtube-transcript-api (pip install youtube-transcript-api).")
    try:
        listing = YouTubeTranscriptApi().list(vid)
        try:
            chosen = listing.find_transcript(list(languages))
        except Exception:
            chosen = next(iter(listing))
        fetched = chosen.fetch()
    except StopIteration:
        raise YouTubeError("This video has no captions, so there is nothing to read.")
    except Exception as exc:
        name = type(exc).__name__
        reason = {
            "TranscriptsDisabled": "captions are turned off for this video",
            "NoTranscriptFound": "this video has no captions",
            "VideoUnavailable": "the video is unavailable or private",
            "AgeRestricted": "the video is age-restricted",
            "IpBlocked": "YouTube is blocking caption requests from this network right now",
            "RequestBlocked": "YouTube is blocking caption requests from this network right now",
            "InvalidVideoId": "that isn't a valid video link",
        }.get(name, str(exc).splitlines()[0][:160] if str(exc) else name)
        raise YouTubeError(f"Couldn't read the captions: {reason}.") from exc
    text = join(fetched)
    if not text:
        raise YouTubeError("The captions came back empty.")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[… the rest of a very long video was cut]"
    return getattr(chosen, "language_code", "") or "", text
