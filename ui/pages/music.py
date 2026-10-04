"""Music (10.0): play your own songs, make playlists, listen to the radio,
program a beat on the drum machine, and write a song.

The player itself is jarvis/music.py (Windows Media Player's engine on its
own thread); this page only sends it commands and reads what it's doing
twice a second. Long lists (a whole music library, a country's radio) are
plain Tk listboxes, which show thousands of rows instantly.
"""

from __future__ import annotations

import copy
import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jarvis import kit, music
from ui.pages.base import Hub, button, label, plain, show_in_folder, text_font


class MusicPage(Hub):
    key = "music"
    title = "Music"
    icon = "🎵"
    subtitle = "Your songs and playlists, radio from Türkiye and everywhere, a drum machine, and songwriting."

    def build_body(self) -> None:
        c = self.colors
        self.songs: list[Path] = []
        self.shown_songs: list[Path] = []
        self.stations: list[dict] = []

        # --- now playing ---------------------------------------------------------------------
        now = self.card("Now playing", "", "▶", span=2)
        self.now_title = label(now.inner, "Nothing playing", size=16, bold=True)
        self.now_title.pack(anchor="w")
        self.now_artist = label(now.inner, "Pick a song, a playlist or a station below.", size=12, muted=True)
        self.now_artist.pack(anchor="w")
        bar = plain(now.inner)
        bar.pack(fill="x", pady=(8, 0))
        for text, verb in (("⏮", "previous"), ("⏯", "toggle"), ("⏭", "next"), ("⏹", "stop")):
            button(bar, text, lambda v=verb: music.player.do(v), width=44, height=34,
                   accent=verb == "toggle").pack(side="left", padx=(0, 4))
        self.shuffle_btn = button(bar, "🔀 Shuffle", self.toggle_shuffle, height=34)
        self.shuffle_btn.pack(side="left", padx=(10, 4))
        self.repeat_btn = button(bar, "🔁 Repeat: off", self.cycle_repeat, height=34)
        self.repeat_btn.pack(side="left")
        label(bar, "🔊", size=14).pack(side="left", padx=(16, 4))
        self.volume = ctk.CTkSlider(bar, from_=0, to=100, number_of_steps=100, width=140,
                                    command=lambda v: music.player.do("volume", int(v)))
        self.volume.set(music.player.now()["volume"])
        self.volume.pack(side="left")
        line = plain(now.inner)
        line.pack(fill="x", pady=(8, 0))
        self.elapsed = label(line, "0:00", size=11, muted=True)
        self.elapsed.pack(side="left")
        self.seek = ctk.CTkSlider(line, from_=0, to=1, number_of_steps=1000, command=self._seeking)
        self.seek.set(0)
        self.seek.pack(side="left", fill="x", expand=True, padx=8)
        self.total = label(line, "0:00", size=11, muted=True)
        self.total.pack(side="left")
        self._seek_job = None
        self._seek_hold = 0

        # --- your music ------------------------------------------------------------------------
        mine = self.card("Your music", "Double-click to play; right-click to add to a playlist.", "🎧")
        row = plain(mine.inner)
        row.pack(fill="x")
        self.search = ctk.CTkEntry(row, placeholder_text="Search songs and artists…", fg_color=c["bg"])
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<KeyRelease>", lambda e: self.filter_songs())
        button(row, "＋ Folder", self.add_folder, height=28).pack(side="left", padx=(6, 0))
        self.song_list = self._listbox(mine.inner, 14)
        self.song_list.bind("<Double-Button-1>", lambda e: self.play_song())
        self.song_list.bind("<Return>", lambda e: self.play_song())
        self.song_list.bind("<Button-3>", self._song_menu)
        self.song_note = label(mine.inner, "", size=11, muted=True)
        self.song_note.pack(anchor="w")

        # --- playlists -------------------------------------------------------------------------
        lists = self.card("Playlists", "Your own mixes, saved on this PC.", "📃")
        self.playlist_list = self._listbox(lists.inner, 8)
        self.playlist_list.bind("<Double-Button-1>", lambda e: self.play_playlist(False))
        self.playlist_list.bind("<<ListboxSelect>>", lambda e: self.show_playlist())
        row = plain(lists.inner)
        row.pack(fill="x", pady=(6, 0))
        button(row, "▶ Play", lambda: self.play_playlist(False), accent=True, height=28).pack(side="left")
        button(row, "🔀", lambda: self.play_playlist(True), width=34, height=28).pack(side="left", padx=4)
        button(row, "＋ New", self.new_playlist, height=28).pack(side="left")
        button(row, "💾 Save queue", self.save_queue, height=28).pack(side="left", padx=4)
        button(row, "🗑", self.delete_playlist, width=34, height=28).pack(side="left")
        self.playlist_songs = label(lists.inner, "", size=11, muted=True, wrap=420)
        self.playlist_songs.pack(anchor="w", pady=(6, 0))

        # --- radio -----------------------------------------------------------------------------
        radio = self.card("Radio", "Türkiye's most listened-to stations, or search any station or genre.", "📻",
                          span=2)
        row = plain(radio.inner)
        row.pack(fill="x")
        self.radio_search = ctk.CTkEntry(row, placeholder_text="Station or genre: Kral, türkü, jazz, lofi…",
                                         fg_color=c["bg"])
        self.radio_search.pack(side="left", fill="x", expand=True)
        self.radio_search.bind("<Return>", lambda e: self.find_radio())
        button(row, "Search", self.find_radio, height=28).pack(side="left", padx=6)
        button(row, "Türkiye top", self.load_radio, height=28).pack(side="left")
        button(row, "★ Favourites", self.show_favourites, height=28).pack(side="left", padx=6)
        self.radio_list = self._listbox(radio.inner, 8)
        self.radio_list.bind("<Double-Button-1>", lambda e: self.play_station())
        self.radio_list.bind("<Return>", lambda e: self.play_station())
        row = plain(radio.inner)
        row.pack(fill="x", pady=(6, 0))
        button(row, "▶ Play", self.play_station, accent=True, height=28).pack(side="left")
        button(row, "★ Add to favourites", self.add_favourite, height=28).pack(side="left", padx=6)
        self.radio_note = label(row, "", size=11, muted=True)
        self.radio_note.pack(side="left", padx=6)

        # --- drum machine ----------------------------------------------------------------------
        drums = self.card("Drum machine", "Click a step to add a hit, again to accent it, again to clear it.", "🥁",
                          span=2)
        row = plain(drums.inner)
        row.pack(fill="x")
        self.style_var = tkinter.StringVar(value="rock")
        ctk.CTkOptionMenu(row, values=list(music.PRESETS), variable=self.style_var, width=170, fg_color=c["bg"],
                          button_color=c["accent_dim"], command=lambda v: self.load_style()).pack(side="left")
        self.bpm_label = label(row, "", size=12, width=80)
        self.bpm_label.pack(side="left", padx=(12, 4))
        self.bpm = ctk.CTkSlider(row, from_=60, to=180, number_of_steps=120, width=180,
                                 command=lambda v: self.drums_changed())
        self.bpm.pack(side="left")
        self.drum_play = button(row, "▶ Play", self.toggle_drums, accent=True, height=30)
        self.drum_play.pack(side="left", padx=(12, 4))
        button(row, "💾 Save MP3", self.save_beat, height=30).pack(side="left")
        button(row, "Clear", self.clear_drums, height=30).pack(side="left", padx=4)
        self.grid_box = plain(drums.inner)
        self.grid_box.pack(anchor="w", pady=(10, 0))
        self.drum_note = label(drums.inner, "", size=11, muted=True)
        self.drum_note.pack(anchor="w", pady=(6, 0))
        self.cells: dict[tuple[str, int], tkinter.Label] = {}
        self._playhead = -1
        self.load_style()

        self.section("Write a song")
        self.tool_card("lyrics", span=2)

        self.every("now", 500, self.refresh_now)
        self.every("playhead", 60, self.move_playhead)

    def _listbox(self, parent, height: int) -> tkinter.Listbox:
        c = self.colors
        box = tkinter.Listbox(parent, height=height, activestyle="none", bd=0, highlightthickness=0,
                              font=text_font(self, 12)[0], bg=c["bg"], fg=c["text"],
                              selectbackground=c["accent_dim"], selectforeground=c["text"], exportselection=False)
        box.pack(fill="x", pady=(6, 0))
        return box

    def on_show(self) -> None:
        if not self.songs:
            self.load_songs()
        if not self.stations:
            self.load_radio()
        self.fill_playlists()
        self.refresh_now()

    def on_hide(self) -> None:
        pass        # music keeps playing on other pages; the drum loop too, until Stop

    # --- now playing ---------------------------------------------------------------------------
    def refresh_now(self) -> None:
        now = music.player.now()
        item = now["item"]
        c = self.colors
        if now["error"]:
            self.now_title.configure(text="Can't play that")
            self.now_artist.configure(text=now["error"])
        elif item is None or now["state"] == music.STOPPED:
            self.now_title.configure(text="Nothing playing")
            self.now_artist.configure(text="Pick a song, a playlist or a station below.")
        else:
            state = {"paused": "⏸  ", "buffering": "⏳  "}.get(now["state"], "")
            self.now_title.configure(text=state + item["title"])
            kind = "📻 Radio" if item["kind"] == "radio" else ""
            self.now_artist.configure(text=" · ".join(x for x in (kind, item.get("artist", "")) if x))
        duration = now["duration"] or 0
        if self._seek_hold <= 0 and duration:
            self.seek.set(min(1.0, now["position"] / duration))
        self._seek_hold -= 1
        self.elapsed.configure(text=music.clock(now["position"]))
        self.total.configure(text=music.clock(duration) if duration else ("live" if item and
                                                                          item["kind"] == "radio" else "0:00"))
        self.shuffle_btn.configure(fg_color=c["accent_dim"] if now["shuffle"] else c["bg"])
        self.repeat_btn.configure(text=f"🔁 Repeat: {now['repeat']}",
                                  fg_color=c["accent_dim"] if now["repeat"] != "off" else c["bg"])

    def _seeking(self, value: float) -> None:
        self._seek_hold = 3            # don't let the clock move the knob while it's being dragged
        if self._seek_job is not None:
            self.after_cancel(self._seek_job)
        self._seek_job = self.after(150, lambda: self._seek_to(value))

    def _seek_to(self, value: float) -> None:
        self._seek_job = None
        duration = music.player.now()["duration"]
        if duration:
            music.player.do("seek", float(value) * duration)

    def toggle_shuffle(self) -> None:
        music.player.do("shuffle", not music.player.now()["shuffle"])
        self.after(150, self.refresh_now)

    def cycle_repeat(self) -> None:
        nxt = {"off": "all", "all": "one", "one": "off"}[music.player.now()["repeat"]]
        music.player.do("repeat", nxt)
        self.after(150, self.refresh_now)

    # --- your music ------------------------------------------------------------------------------
    def load_songs(self, refresh: bool = False) -> None:
        self.song_note.configure(text="Reading your music folder…")

        def done(songs):
            self.songs = songs if isinstance(songs, list) else []
            self.filter_songs()
            folders = ", ".join(f.name for f in music.music_folders()) or "no music folder"
            self.song_note.configure(text=f"{len(self.songs)} songs in {folders}" if self.songs else
                                     "No songs found. ＋ Folder adds where you keep your music.")

        self.run(lambda: music.library(refresh), done)

    def filter_songs(self) -> None:
        self.shown_songs = music.search(self.songs, self.search.get())
        self.song_list.delete(0, "end")
        for song in self.shown_songs[:5000]:
            title, artist = music.describe(song)
            self.song_list.insert("end", f"{title}" + (f"  —  {artist}" if artist else ""))

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self)
        if folder:
            settings = music.MUSIC_SETTINGS.load()
            settings["folders"] = sorted(set(settings.get("folders", [])) | {folder})
            music.MUSIC_SETTINGS.save(settings)
            self.load_songs(refresh=True)

    def play_song(self) -> None:
        chosen = self.song_list.curselection()
        if not chosen or not self.shown_songs:
            return
        if not music.Player.available():
            self.song_note.configure(text="Playing music works on Windows.")
            return
        music.player.play_songs(self.shown_songs[:5000], chosen[0])
        self.after(400, self.refresh_now)

    def _song_menu(self, event) -> None:
        index = self.song_list.nearest(event.y)
        if index < 0 or index >= len(self.shown_songs):
            return
        self.song_list.selection_clear(0, "end")
        self.song_list.selection_set(index)
        song = self.shown_songs[index]
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Play", command=self.play_song)
        menu.add_command(label="Play next", command=lambda: music.player.do("add", [music.song_item(song)]))
        add = tkinter.Menu(menu, tearoff=0)
        for name in music.playlist_names():
            add.add_command(label=name, command=lambda n=name: self.add_to_playlist(n, song))
        add.add_separator()
        add.add_command(label="New playlist…", command=lambda: self.add_to_playlist(None, song))
        menu.add_cascade(label="Add to playlist", menu=add)
        menu.add_command(label="Show in folder", command=lambda: show_in_folder(song))
        menu.tk_popup(event.x_root, event.y_root)

    def add_to_playlist(self, name: str | None, song: Path) -> None:
        if name is None:
            name = (ctk.CTkInputDialog(text="Name the new playlist:", title="Playlist").get_input() or "").strip()
            if not name:
                return
        songs = music.playlist(name)
        if str(song).lower() not in {str(s).lower() for s in songs}:
            music.save_playlist(name, songs + [song])
        self.fill_playlists()
        self.song_note.configure(text=f"Added to {name}.")

    # --- playlists -------------------------------------------------------------------------------
    def fill_playlists(self) -> None:
        self.playlist_list.delete(0, "end")
        self.playlist_names = music.playlist_names()
        for name in self.playlist_names:
            self.playlist_list.insert("end", f"{name}   ({len(music.playlist(name))})")
        if not self.playlist_names:
            self.playlist_songs.configure(text="No playlists yet. Right-click a song → Add to playlist.")

    def _chosen_playlist(self) -> str | None:
        chosen = self.playlist_list.curselection()
        return self.playlist_names[chosen[0]] if chosen else None

    def show_playlist(self) -> None:
        name = self._chosen_playlist()
        if name:
            songs = music.playlist(name)
            titles = [music.describe(s)[0] for s in songs[:8]]
            self.playlist_songs.configure(text=", ".join(titles) + (" …" if len(songs) > 8 else "") or "Empty.")

    def play_playlist(self, shuffle: bool) -> None:
        name = self._chosen_playlist()
        if name is None:
            self.playlist_songs.configure(text="Choose a playlist first.")
            return
        self.playlist_songs.configure(text="Starting…")
        self.app.run_tool(f"/playlist {'shuffle' if shuffle else 'play'} {name}",
                          lambda r: self.playlist_songs.configure(text=getattr(r, "text", str(r))), name="playlist")

    def new_playlist(self) -> None:
        name = (ctk.CTkInputDialog(text="Name the new playlist:", title="Playlist").get_input() or "").strip()
        if name:
            music.save_playlist(name, music.playlist(name))
            self.fill_playlists()

    def save_queue(self) -> None:
        name = (ctk.CTkInputDialog(text="Save what's queued as:", title="Playlist").get_input() or "").strip()
        if name:
            self.playlist_songs.configure(text=self.app.jarvis.playlist_cmd(f"save {name}"))
            self.fill_playlists()

    def delete_playlist(self) -> None:
        name = self._chosen_playlist()
        if name:
            music.delete_playlist(name)
            self.fill_playlists()
            self.playlist_songs.configure(text=f"Deleted {name}.")

    # --- radio -----------------------------------------------------------------------------------
    def _show_stations(self, rows, note: str) -> None:
        if not isinstance(rows, list):
            self.radio_note.configure(text=str(rows))
            return
        self.stations = rows
        self.radio_list.delete(0, "end")
        for row in rows:
            tag = row["tags"].split(",")[0] if row.get("tags") else ""
            self.radio_list.insert("end", f"{row['name']}" + (f"   ·  {tag}" if tag else ""))
        self.radio_note.configure(text=note if rows else "No stations found.")

    def load_radio(self) -> None:
        self.radio_note.configure(text="Loading stations…")
        self.run(lambda: music.top_stations(), lambda rows: self._show_stations(rows, "Türkiye's most popular"),
                 lambda exc: self.radio_note.configure(text=str(exc)))

    def find_radio(self) -> None:
        query = self.radio_search.get().strip()
        if not query:
            self.load_radio()
            return
        self.radio_note.configure(text="Searching…")
        self.run(lambda: music.find_stations(query), lambda rows: self._show_stations(rows, f"Results for {query}"),
                 lambda exc: self.radio_note.configure(text=str(exc)))

    def show_favourites(self) -> None:
        self._show_stations(music.MUSIC_SETTINGS.load().get("favorites", []), "Your favourites")

    def _chosen_station(self) -> dict | None:
        chosen = self.radio_list.curselection()
        return self.stations[chosen[0]] if chosen and chosen[0] < len(self.stations) else None

    def play_station(self) -> None:
        station = self._chosen_station()
        if station is None:
            self.radio_note.configure(text="Choose a station first.")
            return
        if not music.Player.available():
            self.radio_note.configure(text="The radio needs Windows.")
            return
        music.player.play_station(station)
        self.radio_note.configure(text=f"Tuning in to {station['name']}…")
        self.after(1500, self.refresh_now)

    def add_favourite(self) -> None:
        station = self._chosen_station()
        if station is None:
            return
        settings = music.MUSIC_SETTINGS.load()
        favourites = [f for f in settings.get("favorites", []) if f.get("url") != station["url"]]
        settings["favorites"] = favourites + [station]
        music.MUSIC_SETTINGS.save(settings)
        self.radio_note.configure(text=f"★ {station['name']} added.")

    # --- drum machine ----------------------------------------------------------------------------
    def load_style(self) -> None:
        self.pattern = copy.deepcopy(music.PRESETS[self.style_var.get()])
        steps = music.pattern_steps(self.pattern)
        for name in music.INSTRUMENTS:
            row = self.pattern["tracks"].get(name, "")
            self.pattern["tracks"][name] = (row + "." * steps)[:steps]
        self.bpm.set(self.pattern["bpm"])
        self.draw_grid()
        self.drums_changed()

    def draw_grid(self) -> None:
        from ui import theme

        c = self.colors
        # Every other beat a shade lighter, so the bars read at a glance in any theme.
        self._shade = theme._mix(theme._hex(c["panel"]), theme._hex(c["muted"]), 0.3)
        for child in self.grid_box.winfo_children():
            child.destroy()
        self.cells = {}
        steps = music.pattern_steps(self.pattern)
        beat = self.pattern.get("unit", 4)
        font = text_font(self, 11)[0]
        for r, name in enumerate(music.INSTRUMENTS):
            tkinter.Label(self.grid_box, text=music.LABELS[name], font=font, fg=c["muted"], bg=c["panel"],
                          anchor="w", width=13).grid(row=r, column=0, sticky="w")
            for i in range(steps):
                cell = tkinter.Label(self.grid_box, width=3, height=1, bd=0, cursor="hand2")
                cell.grid(row=r, column=i + 1, padx=(4 if i and i % beat == 0 else 1, 1), pady=1)
                cell.bind("<Button-1>", lambda e, n=name, s=i: self.toggle_step(n, s))
                self.cells[(name, i)] = cell
                self.paint(name, i)

    def paint(self, name: str, step: int, playing: bool = False) -> None:
        c = self.colors
        mark = self.pattern["tracks"][name][step]
        beat = self.pattern.get("unit", 4)
        if mark == "X":
            colour = c["accent"]
        elif mark == "x":
            colour = c["accent_dim"]
        else:
            colour = self._shade if (step // beat) % 2 == 0 else c["bg"]
        cell = self.cells.get((name, step))
        if cell is not None:
            cell.configure(bg=colour, highlightthickness=2 if playing else 0, highlightbackground=c["text"])

    def toggle_step(self, name: str, step: int) -> None:
        row = self.pattern["tracks"][name]
        nxt = {".": "x", "x": "X", "X": "."}[row[step]]
        self.pattern["tracks"][name] = row[:step] + nxt + row[step + 1:]
        self.paint(name, step)
        self.drums_changed()

    def clear_drums(self) -> None:
        steps = music.pattern_steps(self.pattern)
        self.pattern["tracks"] = {name: "." * steps for name in music.INSTRUMENTS}
        self.draw_grid()
        self.drums_changed()

    def drums_changed(self) -> None:
        bpm = int(self.bpm.get())
        self.pattern["bpm"] = bpm
        self.bpm_label.configure(text=f"{bpm} BPM")
        if music.drums.playing:
            music.drums.set(music.render(self.pattern, 1))

    def toggle_drums(self) -> None:
        if music.drums.playing:
            music.drums.stop()
            self.drum_play.configure(text="▶ Play")
            self._clear_playhead()
            return
        try:
            music.drums.play(music.render(self.pattern, 1))
        except Exception as exc:
            self.drum_note.configure(text=f"No sound device: {exc}")
            return
        self.drum_play.configure(text="⏹ Stop")

    def move_playhead(self) -> None:
        if not music.drums.playing:
            return
        steps = music.pattern_steps(self.pattern)
        step = music.drums.step_position(steps)
        if step == self._playhead:
            return
        self._clear_playhead()
        self._playhead = step
        for name in music.INSTRUMENTS:
            self.paint(name, step, playing=True)

    def _clear_playhead(self) -> None:
        if self._playhead >= 0:
            for name in music.INSTRUMENTS:
                self.paint(name, self._playhead)
        self._playhead = -1

    def save_beat(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        style = kit.slug(self.style_var.get())

        def work():
            from jarvis import audiofile

            audio = music.render(pattern, 8)
            target = kit.output_dir("audio") / f"beat_{style}_{pattern['bpm']}bpm_{kit.stamp()}.mp3"
            try:
                return audiofile.save(audio, music.RATE, target)
            except Exception:
                return audiofile.save(audio, music.RATE, target.with_suffix(".wav"))

        self.drum_note.configure(text="Saving 8 bars…")
        self.run(work, lambda path: self.drum_note.configure(text=f"Saved {Path(str(path)).name} in Output › audio"),
                 lambda exc: self.drum_note.configure(text=f"Couldn't save: {exc}"))
