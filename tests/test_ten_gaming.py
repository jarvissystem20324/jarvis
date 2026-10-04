"""10.0 gaming: finding games the way the launchers record them, driver
versions, fair teams, and the Gaming page's trainer, tester and overlay."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from jarvis import gaming


def _manifest(appid, name, installdir, size):
    return f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{installdir}"\n' \
           f'\t"SizeOnDisk"\t\t"{size}"\n\t"LastUpdated"\t\t"1700000000"\n}}\n'


def test_steam_games_in_every_library_folder(tmp_path):
    root, extra = tmp_path / "Steam", tmp_path / "D" / "SteamLibrary"
    (root / "steamapps").mkdir(parents=True)
    (extra / "steamapps").mkdir(parents=True)
    vdf = ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"' + str(root).replace("\\", "\\\\") + '"\n\t}\n'
           '\t"1"\n\t{\n\t\t"path"\t\t"' + str(extra).replace("\\", "\\\\") + '"\n\t\t"apps"\n\t\t{\n\t\t\t"570"\t\t'
           '"123"\n\t\t}\n\t}\n}\n')
    (root / "steamapps" / "libraryfolders.vdf").write_text(vdf, encoding="utf-8")
    (root / "steamapps" / "appmanifest_427520.acf").write_text(_manifest(427520, "Factorio", "Factorio", 2_200_000_000))
    (root / "steamapps" / "appmanifest_228980.acf").write_text(
        _manifest(228980, "Steamworks Common Redistributables", "Steamworks Shared", 1000))
    (extra / "steamapps" / "appmanifest_570.acf").write_text(_manifest(570, "Dota 2", "dota 2 beta", 40_000_000_000))
    assert gaming.parse_vdf(vdf)["libraryfolders"]["1"]["apps"] == {"570": "123"}
    games = gaming.steam_games(root)
    assert [g.name for g in games] == ["Factorio", "Dota 2"]          # the redistributable isn't a game
    dota = games[1]
    assert dota.launch == "steam://rungameid/570" and dota.size == 40_000_000_000
    assert dota.image_url.endswith("/570/header.jpg") and "dota 2 beta" in dota.folder


def test_epic_games_from_their_manifests(tmp_path):
    (tmp_path / "a.item").write_text(json.dumps({
        "DisplayName": "Fortnite", "AppName": "Fortnite", "CatalogNamespace": "fn", "CatalogItemId": "abc",
        "InstallLocation": "C:/Epic/Fortnite", "InstallSize": 30_000_000_000, "AppCategories": ["public", "games"]}))
    (tmp_path / "b.item").write_text(json.dumps({"DisplayName": "Unreal Engine", "AppCategories": ["engines"]}))
    (tmp_path / "c.item").write_text("not json")
    games = gaming.epic_games(tmp_path)
    assert [g.name for g in games] == ["Fortnite"]
    assert games[0].launch == "com.epicgames.launcher://apps/fn%3Aabc%3AFortnite?action=launch&silent=true"


def test_finding_a_game_by_name():
    games = [gaming.Game("Counter-Strike 2", "Steam", "x"), gaming.Game("Factorio", "Steam", "y")]
    assert gaming.find(games, "counter") == [games[0]] and gaming.find(games, "factorio") == [games[1]]


def test_driver_versions_and_ages(monkeypatch):
    from jarvis.ten import system

    assert gaming.nvidia_version("31.0.15.5222") == "552.22"
    assert gaming.nvidia_version("32.0.15.6094") == "560.94"
    old = int((datetime.now() - timedelta(days=400)).timestamp() * 1000)
    monkeypatch.setattr(system, "ps_json", lambda script, timeout=30: [
        {"Name": "NVIDIA GeForce RTX 3060", "DriverVersion": "31.0.15.5222", "DriverDate": f"/Date({old})/",
         "AdapterCompatibility": "NVIDIA"},
        {"Name": "Radeon 500 Series", "DriverVersion": "31.0.12027.9001", "DriverDate": None,
         "AdapterCompatibility": "Advanced Micro Devices, Inc."}])
    drivers = gaming.gpu_drivers()
    assert drivers[0]["shown"] == "552.22" and 399 <= drivers[0]["age_days"] <= 401 and drivers[0]["vendor"] == "nvidia"
    assert drivers[1]["vendor"] == "amd" and drivers[1]["age_days"] is None
    from jarvis.ten import play

    reply = play.Play().gpudriver_cmd("")
    assert "13 months old — worth updating" in reply and "nvidia.com" in reply


def test_teams_are_fair(monkeypatch):
    from jarvis.ten import play

    reply = play.Play().teams_cmd("Ali:9, Ayşe:8, Mehmet:2, Zeynep:1 | 2")
    totals = sorted(int(line.split("skill ")[1].rstrip(")")) for line in reply.splitlines()[1:])
    assert totals == [10, 10]
    plain = play.Play().teams_cmd("a, b, c, d, e, f | 3")
    assert plain.count("Team ") == 3 and all(line.count(",") == 1 for line in plain.splitlines()[1:])
    assert "Usage" in play.Play().teams_cmd("just me")


def test_game_commands(monkeypatch):
    from jarvis.ten import play

    games = [gaming.Game("Factorio", "Steam", "steam://rungameid/427520", size=2_200_000_000),
             gaming.Game("Fortnite", "Epic", "com.epicgames.launcher://x")]
    started = []
    monkeypatch.setattr(gaming, "library", lambda: games)
    monkeypatch.setattr(gaming, "launch", lambda game: started.append(game.name))
    listing = play.Play().games_cmd("")
    assert "1. Factorio (Steam, 2.2 GB)" in listing and "2. Fortnite (Epic)" in listing
    assert "Starting Fortnite" in play.Play().game_cmd("2") and started == ["Fortnite"]
    play.Play().game_cmd("factorio")
    assert started[-1] == "Factorio"
    assert "can't find" in play.Play().game_cmd("half-life 3")
    assert play.Play().overlay_cmd("off").open_page == "gaming:overlay-off"


from tests.test_gui import _display_available, app  # noqa: E402,F401
from tests.test_ten_ui import inline  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_gaming_page(app, inline, monkeypatch):
    import types

    from jarvis.ten import system

    monkeypatch.setattr(gaming, "library", lambda: [gaming.Game("Factorio", "GOG", "C:/games/factorio.exe")])
    monkeypatch.setattr(gaming, "sample", lambda: {"cpu": 12.0, "ram": 40.0, "gpu": 55.0, "gpu_temp": 61.0,
                                                   "vram": 30.0, "ping": 21.0})
    monkeypatch.setattr(system, "gpu_load_counters", lambda: None)
    from ui.pages import gaming as page_module

    monkeypatch.setattr(page_module.Overlay, "_sampler", lambda self: None)   # its loop would never end inline
    app._show_tab("gaming")
    app.update()
    page = app.pages["gaming"]
    assert "1 game(s) from GOG" in page.count.cget("text") and len(page.shelf.winfo_children()) == 1
    aim = page.aim
    aim.start()
    x, y, r = aim.target
    aim.click(types.SimpleNamespace(x=x, y=y))
    aim.click(types.SimpleNamespace(x=-50, y=-50))
    assert aim.hits == 1 and aim.misses == 1 and len(aim.times) == 1
    aim.ends = 0
    aim.tick()
    assert not aim.running and "Best 1" in aim.stats.cget("text")
    tester = page.key_test
    tester.key_down(types.SimpleNamespace(keysym="w", keycode=87))
    assert "w" in tester.pressed and "w" in tester.ever
    tester.key_up(types.SimpleNamespace(keysym="w", keycode=87))
    assert "w" not in tester.pressed
    page.open_target("overlay-on")
    assert page.overlay is not None
    page.overlay.show(gaming.sample())
    assert "GPU  55%" in page.overlay.text.cget("text") and "Ping 21 ms" in page.overlay.text.cget("text")
    page.open_target("overlay-off")
    assert page.overlay is None
