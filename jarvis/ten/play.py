"""10.0 music and games: your own songs and playlists, Turkish (and any)
radio, the drum machine, and writing song lyrics.

The engine is jarvis/music.py; these are its commands, so everything the
Music page does can also be said in the chat ("/music play tarkan").
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import kit, music
from ..registry import command, field, split

G = "Music and games"
_last_stations: list[dict] = []


def _song_lines(songs: list[Path], limit: int = 10) -> str:
    lines = []
    for i, song in enumerate(songs[:limit], 1):
        title, artist = music.describe(song)
        lines.append(f"  {i}. {title}" + (f" — {artist}" if artist else ""))
    if len(songs) > limit:
        lines.append(f"  … and {len(songs) - limit} more")
    return "\n".join(lines)


def now_playing_text() -> str:
    now = music.player.now()
    item = now["item"]
    if now["error"]:
        return f"🎵 {now['error']}"
    if item is None or now["state"] == music.STOPPED:
        return "🎵 Nothing playing. /music play <song or artist> · /radio · the Music page"
    where = (f" {music.clock(now['position'])} / {music.clock(now['duration'])}" if item["kind"] == "song"
             and now["duration"] else "")
    state = {"paused": "⏸ Paused", "buffering": "⏳ Loading"}.get(now["state"], "▶ Playing")
    who = f" — {item['artist']}" if item.get("artist") else ""
    extra = []
    if now["shuffle"]:
        extra.append("shuffle")
    if now["repeat"] != "off":
        extra.append(f"repeat {now['repeat']}")
    return f"{state}: {item['title']}{who}{where}" + (f" ({', '.join(extra)})" if extra else "")


def _style(text: str) -> tuple[str | None, str]:
    """(the drum style named in `text`, the rest of it): "karsilama 120" → ("karşılama 9/8", "120")."""
    def key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", music._norm(value))

    plain = music._norm(text)
    for name in sorted(music.PRESETS, key=len, reverse=True):     # the full name, numbers and all
        if music._norm(name) in plain:
            return name, plain.replace(music._norm(name), " ")
    first, _, rest = plain.partition(" ")
    for name in music.PRESETS:                                       # or the start of it: "hiphop", "dum"
        if key(first) and key(name).startswith(key(first)):
            return name, rest
    return None, plain


def _wait_and_report() -> str:
    """Give the player a moment so the reply says what is actually playing."""
    import time

    for _ in range(20):
        time.sleep(0.1)
        now = music.player.now()
        if now["error"] or now["state"] in {music.PLAYING, music.PAUSED}:
            break
    return now_playing_text()


class Play:
    @command("music", "song", group=G,
             usage="/music play <song, artist or folder> · pause · resume · next · previous · stop · "
                   "shuffle on|off · repeat off|all|one · volume 0-100",
             help="plays your own music files", title="Music player", icon="🎵", page="music",
             fields=(field("action", "choice", "Action", "play",
                           ("play", "pause", "resume", "next", "previous", "stop")),
                     field("what", "text", "Song, artist or folder", optional=True)),
             template="{action} {what}")
    def music_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        verb, rest = verb.lower(), rest.strip()
        if not music.Player.available():
            return "🎵 Playing music works on Windows (it uses Windows Media Player's engine)."
        if not text:
            return now_playing_text()
        if verb in {"pause", "resume", "next", "previous", "stop", "toggle"}:
            music.player.do(verb)
            return {"pause": "⏸ Paused.", "stop": "⏹ Stopped."}.get(verb) or _wait_and_report()
        if verb == "shuffle":
            music.player.do("shuffle", rest.lower() != "off")
            return f"🔀 Shuffle {'off' if rest.lower() == 'off' else 'on'}."
        if verb == "repeat":
            mode = rest.lower() if rest.lower() in {"off", "all", "one"} else "all"
            music.player.do("repeat", mode)
            return f"🔁 Repeat {mode}."
        if verb in {"volume", "vol", "ses"}:
            m = re.search(r"\d+", rest)
            if not m:
                return f"🔊 Volume {music.player.now()['volume']}. /music volume 40"
            music.player.do("volume", int(m.group(0)))
            return f"🔊 Volume {min(100, int(m.group(0)))}."
        if verb in {"now", "playing"}:
            return now_playing_text()
        if verb in {"library", "songs"}:
            songs = music.library(refresh=True)
            folders = ", ".join(str(f) for f in music.music_folders()) or "no music folder"
            return f"🎵 {len(songs)} song(s) in {folders}.\n" + _song_lines(songs, 8)
        query = rest if verb in {"play", "çal", "oynat"} else text
        path = kit.path_arg(query)
        if path is not None and path.is_dir():
            songs = music.scan([path])
        elif path is not None:
            songs = [path]
        elif query:
            songs = music.search(music.library(), query)
        else:
            if music.player.now()["item"] is not None:
                music.player.do("resume")
                return _wait_and_report()
            songs = music.library()
            music.player.do("shuffle", True)
        if not songs:
            where = ", ".join(str(f) for f in music.music_folders()) or "your Music folder"
            return f"🎵 No song matches {query!r} in {where}. /music library lists what's there."
        music.player.play_songs(songs)
        reply = _wait_and_report()
        return reply + (f"\n{len(songs)} song(s) in the queue." if len(songs) > 1 else "")

    @command("playlist", "playlists", group=G,
             usage="/playlist · new <name> · add <name> | <songs> · play <name> [shuffle] · show <name> · "
                   "remove <name> | <n> · save <name> · delete <name>",
             help="your own playlists", title="Playlists", icon="📃", page="music",
             fields=(field("action", "choice", "Action", "play", ("play", "show", "new", "add", "save", "delete")),
                     field("name", "text", "Playlist"),
                     field("songs", "text", "Songs (for add)", optional=True)),
             template="{action} {name} | {songs}")
    def playlist_cmd(self, args: str, routed: bool = False):
        text = args.strip().rstrip("|").strip()
        verb, _, rest = text.partition(" ")
        verb = verb.lower()
        name, extra = split(rest, 2)
        name = name.strip()
        if not text or verb == "list":
            names = music.playlist_names()
            if not names:
                return "📃 No playlists yet. /playlist new Road trip · /playlist add Road trip | tarkan"
            return "📃 Playlists:\n" + "\n".join(f"  {n} ({len(music.playlist(n))} songs)" for n in names)
        if not name:
            return "Which playlist? For example: /playlist play Road trip"
        songs = music.playlist(name)
        if verb in {"new", "create"}:
            if name.lower() in {n.lower() for n in music.playlist_names()}:
                return f"📃 {name} already exists."
            music.save_playlist(name, [])
            return f"📃 Made {name}. Add songs: /playlist add {name} | <song or artist>"
        if verb == "add":
            path = kit.path_arg(extra)
            found = (music.scan([path]) if path and path.is_dir() else [path] if path else
                     music.search(music.library(), extra) if extra.strip() else [])
            if not found:
                return f"📃 No song matches {extra.strip()!r}."
            known = {str(s).lower() for s in songs}
            fresh = [s for s in found[:100] if str(s).lower() not in known]
            music.save_playlist(name, songs + fresh)
            return f"📃 Added {len(fresh)} song(s) to {name} ({len(songs) + len(fresh)} in all)."
        if verb == "save":
            items = [Path(i["url"]) for i in music.player.items if i["kind"] == "song"]
            if not items:
                return "📃 Nothing in the queue to save."
            music.save_playlist(name, items)
            return f"📃 Saved the queue as {name} ({len(items)} songs)."
        if verb == "delete":
            return f"📃 Deleted {name}." if music.delete_playlist(name) else f"📃 There's no playlist called {name}."
        if verb == "remove":
            m = re.search(r"\d+", extra)
            if not m or not 0 < int(m.group(0)) <= len(songs):
                return f"Usage: /playlist remove {name} | <number from /playlist show {name}>"
            gone = songs.pop(int(m.group(0)) - 1)
            music.save_playlist(name, songs)
            return f"📃 Took {music.describe(gone)[0]} out of {name}."
        if not songs:
            return f"📃 {name} is empty or doesn't exist. /playlist add {name} | <song or artist>"
        if verb == "show":
            return f"📃 {name}:\n" + _song_lines(songs, 50)
        if verb in {"play", "shuffle"}:
            if not music.Player.available():
                return "🎵 Playing music works on Windows."
            present = [s for s in songs if s.exists()]
            if not present:
                return f"📃 None of the songs in {name} are where they were."
            music.player.do("shuffle", verb == "shuffle" or "shuffle" in extra.lower())
            music.player.play_songs(present)
            missing = len(songs) - len(present)
            return _wait_and_report() + (f"\n({missing} song(s) have moved and were skipped.)" if missing else "")
        return "Usage: /playlist play|show|new|add|save|remove|delete <name>"

    @command("radio", group=G, usage="/radio · /radio <station or genre> · /radio <number> · /radio stop",
             help="Turkish radio, or any station in the world", title="Radio", icon="📻", page="music",
             fields=(field("station", "text", "Station or genre", optional=True, hint="Kral FM, türkü, jazz"),))
    def radio_cmd(self, args: str, routed: bool = False):
        global _last_stations
        text = args.strip()
        if text.lower() in {"stop", "off", "kapat"}:
            music.player.do("stop")
            return "📻 Off."
        if not music.Player.available():
            return "📻 The radio plays through Windows Media Player's engine, so it needs Windows."
        try:
            if text.isdigit() and _last_stations:
                index = int(text) - 1
                if not 0 <= index < len(_last_stations):
                    return f"📻 Pick 1 to {len(_last_stations)}."
                chosen = _last_stations[index]
            elif text:
                found = music.find_stations(text)
                if not found:
                    return f"📻 No station called {text!r}. /radio lists Türkiye's most popular."
                _last_stations = found
                chosen = found[0]
            else:
                _last_stations = music.top_stations()[:15]
                return "📻 Türkiye's most listened-to stations — /radio <number> to play:\n" + "\n".join(
                    f"  {i}. {s['name']}" + (f" ({s['tags'].split(',')[0]})" if s["tags"] else "")
                    for i, s in enumerate(_last_stations, 1))
        except kit.KitError as exc:
            return f"📻 {exc}"
        music.player.play_station(chosen)
        return _wait_and_report().replace("▶ Playing", "📻 Playing")

    @command("drums", "drummachine", "beat", group=G, usage="/drums [style] [bpm] [bars] · /drums play <style> · "
                                                             "/drums stop",
             help="a drum beat: rock, pop, hip-hop, house, trap, reggaeton, düm tek, karşılama 9/8 — saved as MP3",
             title="Drum machine", icon="🥁", page="music",
             fields=(field("style", "choice", "Style", "rock", tuple(music.PRESETS)),
                     field("bpm", "number", "Tempo (BPM)", optional=True),
                     field("bars", "number", "Bars", "8")),
             template="{style} {bpm} {bars}")
    def drums_cmd(self, args: str, routed: bool = False):
        from .. import audiofile

        text = args.strip().lower()
        if text in {"stop", "off"}:
            music.drums.stop()
            return "🥁 Stopped."
        live = text.startswith("play")
        text = text[4:].strip() if live else text
        if not text:
            return "🥁 Styles: " + ", ".join(music.PRESETS) + ". /drums house 124 8 saves a beat; " \
                                                              "the Music page has the step editor."
        style, rest = _style(text)
        if style is None:
            return f"🥁 I don't have {text.split()[0]!r}. Styles: " + ", ".join(music.PRESETS)
        numbers = [int(n) for n in re.findall(r"\d{1,3}", rest)]
        bpm = next((n for n in numbers if 40 <= n <= 240), None) or music.PRESETS[style]["bpm"]
        bars = next((n for n in numbers if 1 <= n <= 64 and n != bpm), 8)
        if live:
            try:
                music.drums.play(music.render(music.PRESETS[style], 1, bpm))
            except Exception as exc:
                return f"🥁 No sound device: {exc}"
            return f"🥁 Playing {style} at {bpm} BPM. /drums stop"
        audio = music.render(music.PRESETS[style], bars, bpm)
        target = kit.output_dir("audio") / f"beat_{kit.slug(style)}_{bpm}bpm_{kit.stamp()}.mp3"
        try:
            audiofile.save(audio, music.RATE, target)
        except Exception:
            target = audiofile.save(audio, music.RATE, target.with_suffix(".wav"))
        return f"🥁 {bars} bars of {style} at {bpm} BPM ({len(audio) / music.RATE:.0f} s):\n{target}"

    @command("lyrics", "songwriter", group=G, usage="/lyrics <what it's about> [| genre] [| language]",
             help="writes an original song: verses, chorus, bridge, and chords to play it with",
             title="Write my own song lyrics", icon="🎤", page="music",
             fields=(field("about", "long", "What's the song about?"),
                     field("genre", "text", "Genre", "pop", optional=True, hint="pop, rap, arabesk, rock…"),
                     field("language", "choice", "Language", "Türkçe", ("Türkçe", "English"))))
    def lyrics_cmd(self, args: str, routed: bool = False):
        about, genre, language = split(args, 3)
        if not about.strip():
            return "Usage: /lyrics a summer in Bodrum with friends | pop | Türkçe"
        prompt = (
            f"Write ORIGINAL song lyrics in {language.strip() or 'the language of the topic'} about: "
            f"{about.strip()}. Genre: {genre.strip() or 'pop'}.\n"
            "Never copy or closely imitate an existing song's lyrics. Give: a title; sections marked "
            "[Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Chorus]; lines that scan and rhyme "
            "naturally in that language; a chorus that's easy to remember. After the lyrics, add 'Chords:' "
            "with a simple progression for guitar or piano (and capo if useful), and a suggested tempo."
        )
        with kit.more_room(self.brain, 3000):
            return "🎤 " + self.brain.ask_once(prompt)
