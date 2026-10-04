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
_quiz: tuple | None = None          # the emoji puzzle being asked in the chat
_last_games: list = []              # the last /games list, so /game 2 means its second line


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

    # --- the Arcade -----------------------------------------------------------------------------
    @command("chess", group=G, usage="/chess [easy|medium|hard]", help="chess against JARVIS, on the Arcade page",
             title="Chess against JARVIS", icon="♟", page="arcade",
             fields=(field("level", "choice", "Level", "medium", ("easy", "medium", "hard")),))
    def chess_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        level = args.strip().lower() if args.strip().lower() in {"easy", "medium", "hard"} else ""
        return JarvisResponse(text=f"♟ Chess is on the Arcade page — you're White{', ' + level if level else ''}. "
                                   "Click a piece, then where it goes.",
                              open_page="arcade:chess" + (f"/{level}" if level else ""))

    @command("snake", group=G, usage="/snake", help="Snake, on the Arcade page", title="Snake", icon="🐍",
             page="arcade")
    def snake_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="🐍 Snake is on the Arcade page — arrow keys to steer, Space to pause.",
                              open_page="arcade:snake")

    @command("2048", group=G, usage="/2048", help="2048, on the Arcade page", title="2048", icon="🔢",
             page="arcade")
    def game2048_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="🔢 2048 is on the Arcade page — arrow keys slide the tiles.",
                              open_page="arcade:2048")

    def _word(self, lang: str, args: str) -> str:
        from .. import games

        game = games.WordGame(lang)
        guess = args.strip()
        tr = lang == "tr"
        if guess:
            problem = game.guess(guess)
            if problem:
                return ("🔤 " + {"Five letters, please.": "Beş harfli bir kelime yaz.",
                                 "You've tried that one.": "Bunu zaten denedin."}.get(problem, problem)) if tr \
                    else f"🔤 {problem}"
        rows = ["  " + " ".join(f"{games.TILES[m]}{letter}" for letter, m in row) for row in game.grid()]
        head = "🔤 Günün kelimesi" if tr else "🔤 Today's word"
        if game.won:
            tail = (f"Bildin! {len(game.guesses)}/6 — seri: {games.streak(lang)} gün." if tr else
                    f"Got it in {len(game.guesses)}/6 — streak {games.streak(lang)} day(s).")
        elif game.done:
            tail = (f"Bitti — kelime {games.upper(game.answer, lang)} idi. Yarın yeni kelime." if tr else
                    f"Out of guesses — it was {game.answer.upper()}. A new word tomorrow.")
        else:
            left = 6 - len(game.guesses)
            tail = (f"{left} hakkın kaldı. /kelime <tahmin>" if tr else f"{left} guess(es) left. /wordle <guess>")
        return "\n".join([head] + rows + [tail])

    @command("kelime", group=G, usage="/kelime [tahmin]", help="günün kelime oyunu (Türkçe, 5 harf, 6 hak)",
             title="Daily word game (Türkçe)", icon="🔤", page="arcade",
             fields=(field("guess", "text", "Tahmin", optional=True),))
    def kelime_cmd(self, args: str, routed: bool = False):
        return self._word("tr", args)

    @command("wordle", group=G, usage="/wordle [guess]", help="the daily word game in English (5 letters, "
                                                                    "6 tries)", title="Daily word game (English)",
             icon="🔤", page="arcade", fields=(field("guess", "text", "Guess", optional=True),))
    def wordle_cmd(self, args: str, routed: bool = False):
        return self._word("en", args)

    @command("emojiquiz", "emoji", group=G, usage="/emojiquiz · /emojiquiz <answer> · /emojiquiz skip",
             help="guess the film, series or saying from emojis", title="Emoji quiz", icon="🤔", page="arcade",
             fields=(field("answer", "text", "Your answer (blank for a new one)", optional=True),))
    def emojiquiz_cmd(self, args: str, routed: bool = False):
        from .. import games

        global _quiz
        answer = args.strip()
        if not answer or _quiz is None:
            _quiz = games.quiz_round(count=1)[0]
            return f"🤔 {_quiz[0]}   ({_quiz[3]})\nWhat is it? /emojiquiz <answer> · /emojiquiz skip"
        if answer.lower() in {"skip", "pass", "geç", "pas"}:
            was, _quiz = _quiz, games.quiz_round(count=1)[0]
            return f"It was: {was[1]}.\n🤔 Next: {_quiz[0]}   ({_quiz[3]})"
        if games.check_answer(answer, _quiz):
            was, _quiz = _quiz, games.quiz_round(count=1)[0]
            return f"✅ Yes — {was[1]}!\n🤔 Next: {_quiz[0]}   ({_quiz[3]})"
        return f"❌ Not quite. {_quiz[0]} — try again, or /emojiquiz skip."

    # --- gaming -----------------------------------------------------------------------------------
    @command("games", group=G, usage="/games [search] · /game <name or number>",
             help="the games installed on this PC (Steam, Epic, GOG)", title="Game library", icon="🎮",
             page="gaming", fields=(field("search", "text", "Search", optional=True),))
    def games_cmd(self, args: str, routed: bool = False):
        global _last_games
        from .. import gaming

        found = gaming.library()
        if args.strip():
            found = gaming.find(found, args)
        if not found:
            return "🎮 No games found" + (f" matching {args.strip()!r}." if args.strip() else
                                         " — Steam, Epic and GOG games show up here once installed.")
        _last_games = found
        lines = [f"🎮 {len(found)} game(s) — /game <number> starts one:"]
        lines += [f"  {i}. {g.name} ({g.source}" + (f", {g.size / 1e9:.1f} GB" if g.size else "") + ")"
                  for i, g in enumerate(found[:40], 1)]
        return "\n".join(lines)

    @command("game", "launch", group=G, usage="/game <name or number from /games>", help="starts an installed game",
             title="Start a game", icon="🕹", page="gaming", fields=(field("name", "text", "Game"),))
    def game_cmd(self, args: str, routed: bool = False):
        from .. import gaming

        text = args.strip()
        if not text:
            return self.games_cmd("")
        if text.isdigit() and _last_games and 0 < int(text) <= len(_last_games):
            chosen = [_last_games[int(text) - 1]]
        else:
            chosen = gaming.find(gaming.library(), text)
        if not chosen:
            return f"🎮 I can't find {text!r} among your games. /games lists them."
        if len(chosen) > 1:
            return "🎮 Which one? " + ", ".join(g.name for g in chosen[:8])
        try:
            gaming.launch(chosen[0])
        except OSError as exc:
            return f"🎮 Couldn't start {chosen[0].name}: {exc}"
        return f"🎮 Starting {chosen[0].name} ({chosen[0].source}). Have fun!"

    @command("overlay", group=G, usage="/overlay [on|off]", help="CPU, GPU, RAM and ping on top of your game",
             title="Performance overlay", icon="📊", page="gaming",
             fields=(field("state", "choice", "Overlay", "on", ("on", "off")),))
    def overlay_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        off = args.strip().lower() == "off"
        return JarvisResponse(text="📊 Overlay " + ("off." if off else "on — top-left of the screen. It shows in "
                                                                     "windowed and borderless games."),
                              open_page="gaming:overlay-off" if off else "gaming:overlay-on")

    @command("guide", "gameguide", group=G, usage="/guide <game> | <what you're stuck on>",
             help="searches guides and wikis and sums up the answer, with sources", title="Game guide search",
             icon="🗺", page="gaming", fields=(field("game", "text", "Game"), field("question", "text", "Question")))
    def guide_cmd(self, args: str, routed: bool = False):
        from .. import shield, websearch

        game, question = split(args, 2)
        if not game.strip() or not question.strip():
            return "Usage: /guide Elden Ring | where is the Bloodhound's Fang"
        try:
            results = websearch.search(f"{game} {question} guide")
        except Exception as exc:
            return f"🗺 The web search failed: {exc}"
        if not results:
            return f"🗺 Nothing found for {question!r} in {game}."
        listing = "\n".join(f"- {r.title}: {r.url}\n  {r.snippet[:300]}" for r in results[:6])
        wrapped, _ = shield.wrap(listing, "search results")
        answer = self.brain.ask_once(f"{shield.RULE}\nFrom these search results about the game {game}, answer: "
                                     f"{question}. Give the steps plainly in 3-8 lines and say which result each "
                                     f"comes from. If the results don't answer it, say so.\n\n{wrapped}")
        return f"🗺 {answer.strip()}\n\n" + "\n".join(f"  • {r.url}" for r in results[:4])

    @command("gamesettings", "bestsettings", group=G, usage="/gamesettings <game> [| target fps]",
             help="the in-game graphics settings that suit this PC", title="Best settings for my PC", icon="⚙",
             page="gaming", fields=(field("game", "text", "Game"),
                                     field("fps", "choice", "Aim for", "60", ("60", "144", "30"))))
    def gamesettings_cmd(self, args: str, routed: bool = False):
        import psutil

        from .. import gaming
        from .system import ps_json

        game, fps = split(args, 2)
        if not game.strip():
            return "Usage: /gamesettings Cyberpunk 2077 | 60"
        cpu = next(iter(ps_json("Get-CimInstance Win32_Processor | Select -First 1 Name")), {}).get("Name", "")
        gpus = ", ".join(f"{d['name']} (driver {d['shown']})" for d in gaming.gpu_drivers()) or "unknown GPU"
        width, height = gaming.screen_size()
        specs = (f"CPU: {cpu or 'unknown'}; GPU: {gpus}; RAM: {psutil.virtual_memory().total / 2**30:.0f} GB; "
                 f"screen: {width}x{height}")
        answer = self.brain.ask_once(
            f"Recommend in-game graphics settings for {game.strip()} on this PC, aiming for {fps.strip() or '60'} fps. "
            f"{specs}. If there are two GPUs, it's a laptop: the game should run on the dedicated one. "
            "List the settings that matter most (resolution, preset, upscaling, shadows, textures, etc.) with a value "
            "for each, then one line on what to lower first if it stutters. Be honest if this PC is below the "
            "game's minimum.")
        return f"⚙ {specs}\n\n{answer.strip()}"

    @command("gpudriver", "driver", group=G, usage="/gpudriver", help="how old your graphics driver is, and where "
                                                                        "to update it", title="GPU driver check",
             icon="🧩", page="gaming")
    def gpudriver_cmd(self, args: str, routed: bool = False):
        from .. import gaming

        drivers = gaming.gpu_drivers()
        if not drivers:
            return "🧩 Windows didn't report a graphics card."
        lines = ["🧩 Graphics drivers:"]
        for d in drivers:
            age = d["age_days"]
            when = f"{d['date']:%d %b %Y}" if d["date"] else "unknown date"
            verdict = ("up to date enough" if age is not None and age < 120 else
                       f"{age // 30} months old — worth updating" if age is not None else "age unknown")
            lines.append(f"  {d['name']}: {d['shown']} ({when}) — {verdict}")
            if age is not None and age >= 120 and d["page"]:
                lines.append(f"    Get the latest: {d['page']}")
        lines.append("New drivers often fix crashes and add performance for new games. (JARVIS can't ask the "
                     "makers for their latest version number, so this goes by the driver's age.)")
        return "\n".join(lines)

    @command("teams", "teampicker", group=G, usage="/teams <names, comma-separated> [| number of teams]",
             help="splits players into fair random teams (add skill like ali:5 to balance)",
             title="Team randomiser", icon="🎲", page="gaming",
             fields=(field("names", "long", "Players (comma-separated; ali:5 adds a skill)"),
                     field("teams", "number", "Teams", "2")))
    def teams_cmd(self, args: str, routed: bool = False):
        import random

        names_text, count_text = split(args, 2)
        players = []
        for part in re.split(r"[,\n;]+", names_text):
            name, _, skill = part.strip().partition(":")
            if name.strip():
                try:
                    players.append((name.strip(), float(skill) if skill.strip() else None))
                except ValueError:
                    players.append((part.strip(), None))
        count = int(count_text) if count_text.strip().isdigit() else 2
        if len(players) < 2 or count < 2 or count > len(players):
            return "Usage: /teams Ali, Ayşe, Mehmet, Zeynep | 2   (add skills to balance: Ali:5, Ayşe:3)"
        random.shuffle(players)
        teams: list[list[tuple]] = [[] for _ in range(count)]
        if any(skill is not None for _, skill in players):
            # Strongest first, each to the team that is weakest so far: even totals.
            for player in sorted(players, key=lambda p: -(p[1] or 0)):
                weakest = min(range(count), key=lambda t: (sum(s or 0 for _, s in teams[t]), len(teams[t])))
                teams[weakest].append(player)
        else:
            for i, player in enumerate(players):
                teams[i % count].append(player)
        lines = ["🎲 Teams:"]
        for i, team in enumerate(teams, 1):
            total = sum(s or 0 for _, s in team)
            lines.append(f"  Team {i}: " + ", ".join(n for n, _ in team) + (f"  (skill {total:g})" if total else ""))
        return "\n".join(lines)

    @command("aimtrainer", "aim", group=G, usage="/aimtrainer", help="click the targets: 30 seconds, best score kept",
             title="Aim trainer", icon="🎯", page="gaming")
    def aimtrainer_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="🎯 Aim trainer is on the Gaming page.", open_page="gaming:aim")

    @command("keytest", "mousetest", group=G, usage="/keytest", help="test every key and mouse button, and your "
                                                                       "clicks per second",
             title="Keyboard and mouse tester", icon="⌨", page="gaming")
    def keytest_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="⌨ The tester is on the Gaming page — press keys and click.",
                              open_page="gaming:keys")

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
