"""10.0 music: the library, playlists, the player's queue (over a fake
engine — no sound in a test run), radio, the drum machine and lyrics."""

from __future__ import annotations

import pytest

from jarvis import kit, music


class FakeEngine(music.Backend):
    def __init__(self):
        self.loaded, self.status, self.pos, self.length, self.vol = [], music.STOPPED, 0.0, 200.0, 70

    def load(self, url):
        self.loaded.append(url)
        self.pos = 0.0

    def play(self):
        self.status = music.PLAYING

    def pause(self):
        self.status = music.PAUSED

    def stop(self):
        self.status = music.STOPPED

    def state(self):
        return self.status

    def position(self):
        return self.pos

    def duration(self):
        return self.length

    def seek(self, seconds):
        self.pos = seconds

    def set_volume(self, volume):
        self.vol = volume


@pytest.fixture
def fake_player(base, monkeypatch):
    engine = FakeEngine()
    player = music.Player(lambda: engine, threaded=False)
    monkeypatch.setattr(music, "player", player)
    monkeypatch.setattr(music.Player, "available", staticmethod(lambda: True))
    return player, engine


def test_titles_from_file_names_and_turkish_search(tmp_path):
    folder = tmp_path / "Music" / "Tarkan"
    folder.mkdir(parents=True)
    for name in ("01 Tarkan - Şımarık.mp3", "Kuzu Kuzu.m4a", "cover.jpg"):
        (folder / name).write_bytes(b"x")
    songs = music.scan([tmp_path / "Music"])
    assert [s.name for s in songs] == ["01 Tarkan - Şımarık.mp3", "Kuzu Kuzu.m4a"]
    assert music.describe(songs[0]) == ("Şımarık", "Tarkan")
    assert music.describe(songs[1]) == ("Kuzu Kuzu", "Tarkan")          # the folder is the artist
    assert music.search(songs, "simarik") == [songs[0]]
    assert music.search(songs, "tarkan") == songs


def test_playlists_are_kept_case_insensitively(base, tmp_path):
    song = tmp_path / "a.mp3"
    music.save_playlist("Road Trip", [song])
    assert music.playlist("road trip") == [song]
    music.save_playlist("ROAD TRIP", [song, song])
    assert music.playlist_names() == ["Road Trip"] and len(music.playlist("Road Trip")) == 2
    assert music.delete_playlist("road trip") and music.playlist_names() == []


def test_the_queue_moves_on_shuffles_and_repeats(fake_player, tmp_path):
    player, engine = fake_player
    songs = [tmp_path / f"{n}.mp3" for n in "abc"]
    player.play_songs(songs)
    assert engine.loaded == [str(songs[0])] and player.now()["state"] != music.STOPPED
    player.do("next")
    assert engine.loaded[-1] == str(songs[1])
    engine.status = music.ENDED                 # the song finished on its own
    player.tick()
    assert engine.loaded[-1] == str(songs[2])
    engine.status = music.ENDED
    player.tick()
    assert engine.status == music.STOPPED and len(engine.loaded) == 3     # end of the queue, repeat off
    player.do("repeat", "all")
    player.play_songs(songs, 2)
    engine.status = music.ENDED
    player.tick()
    assert engine.loaded[-1] == str(songs[0])   # wrapped round
    engine.pos = 30
    player.do("previous")
    assert engine.pos == 0 and engine.loaded[-1] == str(songs[0])   # back to the start of the song first
    player.do("shuffle", True)
    player.play_songs(songs, 1)
    assert engine.loaded[-1] == str(songs[1]) and sorted(player.order) == [0, 1, 2] and player.order[0] == 1
    player.do("volume", 150)
    assert engine.vol == 100 and music.MUSIC_SETTINGS.load()["volume"] == 100


def test_a_broken_file_doesnt_stop_the_player(fake_player, tmp_path):
    player, engine = fake_player

    def bad(url):
        raise OSError("can't read that file")

    engine.load = bad
    player.play_songs([tmp_path / "broken.mp3"])
    assert "can't read" in player.now()["error"]


def test_radio_lists_and_plays_stations(fake_player, monkeypatch):
    from jarvis.ten import play

    calls = []

    def fake_get_json(url, params=None, headers=None, timeout=15):
        calls.append(params)
        if "nothing" in (params.get("name"), params.get("tag")):
            return []
        return [{"stationuuid": "1", "name": "Kral FM", "url_resolved": "http://kral.example/stream",
                 "tags": "pop,türkçe", "countrycode": "TR"},
                {"stationuuid": "2", "name": "Radyo 7", "url": "http://r7.example/stream", "tags": ""}]

    monkeypatch.setattr(kit, "get_json", fake_get_json)
    monkeypatch.setattr(music, "_radio_cache", {})
    monkeypatch.setattr(play, "_wait_and_report", lambda: "▶ Playing: something")
    p = play.Play()
    listing = p.radio_cmd("")
    assert "1. Kral FM (pop)" in listing and "2. Radyo 7" in listing
    p.radio_cmd("2")
    player, engine = fake_player
    assert engine.loaded[-1] == "http://r7.example/stream" and player.now()["item"]["kind"] == "radio"
    p.radio_cmd("kral")
    assert engine.loaded[-1] == "http://kral.example/stream"
    assert "No station" in p.radio_cmd("nothing")
    assert len([c for c in calls if c.get("name") == "nothing"]) == 2 and calls[-1].get("tag") == "nothing"
    assert p.radio_cmd("stop") == "📻 Off."


def test_music_command_plays_what_you_ask_for(fake_player, tmp_path, monkeypatch):
    from jarvis.ten import play

    songs = [tmp_path / "Sezen Aksu - Firuze.mp3", tmp_path / "Barış Manço - Gülpembe.mp3"]
    for song in songs:
        song.write_bytes(b"x")
    monkeypatch.setattr(music, "library", lambda refresh=False: songs)
    monkeypatch.setattr(play, "_wait_and_report", play.now_playing_text)
    player, engine = fake_player
    reply = play.Play().music_cmd("play baris")
    assert engine.loaded == [str(songs[1])] and "Gülpembe — Barış Manço" in reply
    assert "No song matches" in play.Play().music_cmd("play nothing like this")
    assert play.Play().music_cmd("pause") == "⏸ Paused." and engine.status == music.PAUSED
    assert "Volume 30" in play.Play().music_cmd("volume 30")
    music.save_playlist("Klasikler", songs)
    play.Play().playlist_cmd("play Klasikler")
    assert engine.loaded[-1] == str(songs[0])
    assert "2 songs" in play.Play().playlist_cmd("")


def test_every_drum_sound_and_a_loop_of_the_right_length():
    for name in music.INSTRUMENTS:
        hit = music.synth(name)
        assert 0.05 < len(hit) / music.RATE < 0.5 and abs(abs(hit).max() - 1) < 1e-5, name
    rock = music.PRESETS["rock"]
    loop = music.render(rock, bars=2, bpm=120)
    assert len(loop) == round(16 * (60 / 120 / 4) * music.RATE) * 2 and abs(loop).max() <= 0.91
    nine = music.PRESETS["karşılama 9/8"]
    assert music.pattern_steps(nine) == 9
    assert len(music.render(nine, 1, 120)) == round(9 * (60 / 120 / 2) * music.RATE)


def test_drum_styles_by_name_even_without_turkish_letters(base, monkeypatch):
    from jarvis import audiofile
    from jarvis.ten import play

    assert play._style("karsilama 120")[0] == "karşılama 9/8"
    assert play._style("hiphop")[0] == "hip-hop" and play._style("dum tek 90")[0] == "düm tek (maqsum)"
    assert play._style("polka")[0] is None
    saved = []
    monkeypatch.setattr(audiofile, "save", lambda audio, rate, path: saved.append((len(audio), path)) or path)
    reply = play.Play().drums_cmd("house 124 2")
    assert "2 bars of house at 124 BPM" in reply and saved[0][1].suffix == ".mp3"
    assert "Styles:" in play.Play().drums_cmd("")


def test_lyrics_ask_for_an_original_song():
    from jarvis.ten import play

    asked = []

    class Brain:
        def ask_once(self, prompt, **kw):
            asked.append(prompt)
            return "[Chorus] …"

    p = play.Play()
    p.brain = Brain()
    assert p.lyrics_cmd("a summer in Bodrum | pop | Türkçe").startswith("🎤 [Chorus]")
    assert "ORIGINAL" in asked[0] and "Türkçe" in asked[0] and "Never copy" in asked[0]


from tests.test_gui import _display_available, app  # noqa: E402,F401
from tests.test_ten_ui import inline  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_music_page(app, inline, fake_player, tmp_path, monkeypatch):
    songs = [tmp_path / f"Artist - Song {n}.mp3" for n in range(3)]
    monkeypatch.setattr(music, "library", lambda refresh=False: songs)
    monkeypatch.setattr(music, "top_stations", lambda country="TR", limit=60: [
        {"id": "1", "name": "Kral FM", "url": "http://kral.example", "tags": "pop"}])
    app._show_tab("music")
    app.update()
    page = app.pages["music"]
    assert page.song_list.size() == 3 and page.radio_list.size() == 1
    page.search.insert(0, "song 2")
    page.filter_songs()
    page.song_list.selection_set(0)
    page.play_song()
    player, engine = fake_player
    assert engine.loaded == [str(songs[2])]
    page.refresh_now()
    assert "Song 2" in page.now_title.cget("text")
    page.radio_list.selection_set(0)
    page.play_station()
    assert engine.loaded[-1] == "http://kral.example"
    page.style_var.set("house")
    page.load_style()
    before = page.pattern["tracks"]["tom"]
    page.toggle_step("tom", 3)
    assert page.pattern["tracks"]["tom"][3] == "x" and before[3] == "."
    page.clear_drums()
    assert set("".join(page.pattern["tracks"].values())) == {"."}
