"""10.0 PC, Security and Antivirus: the parts that can be checked without
changing the machine — parsers, explanations, archives, metadata removal,
the security score's shape, and that every page opens."""

from __future__ import annotations

import sys
import zipfile

import pytest


@pytest.fixture
def jarvis(base):
    from jarvis.assistant import Jarvis

    return Jarvis(voice_enabled=False)


def test_bugcheck_explanations(jarvis):
    from jarvis.ten import system

    assert "MEMORY_MANAGEMENT" in system.explain_bugcheck(0x1A)
    assert "VIDEO_TDR_FAILURE" in jarvis.process("/bsod 0x00000116").text
    assert "search this code" in system.explain_bugcheck(0x12345)


def test_zip_and_unzip_round_trip(jarvis, tmp_path):
    folder = tmp_path / "stuff"
    folder.mkdir()
    (folder / "a.txt").write_text("hello", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "b.txt").write_text("world", encoding="utf-8")
    out = jarvis.process(f"/zip {folder}").text
    archive = tmp_path / "stuff.zip"
    assert archive.exists() and "stuff.zip" in out
    out = jarvis.process(f"/unzip {archive} | {tmp_path / 'back'}").text
    assert (tmp_path / "back" / "stuff" / "sub" / "b.txt").read_text(encoding="utf-8") == "world"


def test_unzip_refuses_paths_outside_the_folder(tmp_path):
    from jarvis.ten import system

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        system.extract(bad, tmp_path / "out")


def test_winget_table_parsing():
    from jarvis.ten import system

    text = ("Name               Id                    Version  Source\n"
            "------------------------------------------------------\n"
            "VLC media player   VideoLAN.VLC          3.0.21   winget\n"
            "7-Zip              7zip.7zip             24.08    winget\n")
    rows = system.parse_winget_table(text)
    assert [r["Id"] for r in rows] == ["VideoLAN.VLC", "7zip.7zip"]


def test_keep_awake_starts_and_stops():
    from jarvis.ten import system

    if not system.awake.supported():
        assert "Windows and macOS" in system.System().awake_cmd("on")
        return
    system.awake.start(0)
    assert system.awake.on
    system.awake.stop()
    assert not system.awake.on


def test_photo_metadata_is_removed(base, tmp_path):
    from PIL import Image

    from jarvis.ten import shield10

    path = tmp_path / "p.jpg"
    image = Image.new("RGB", (40, 30), "red")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x0110] = "Model X"
    image.save(path, exif=exif)
    target, found = shield10.strip_metadata(path)
    assert any("Make" in f for f in found)
    with Image.open(target) as clean:
        assert not dict(clean.getexif())
        assert clean.size == (40, 30)


def test_device_vendors_and_private_macs():
    from jarvis.ten import shield10

    assert shield10.vendor("B8:27:EB:12:34:56") == "Raspberry Pi"
    assert "private" in shield10.vendor("DA:A1:19:00:00:01")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_security_score_has_checks():
    from jarvis.ten import shield10

    value, checks = shield10.score()
    assert 0 <= value <= 100 and checks and all({"name", "ok", "fix"} <= set(c) for c in checks)


def test_powershell_dates_plain_and_wrapped():
    from datetime import datetime

    from jarvis.ten.system import _ps_date

    stamp = "/Date(1788901200000)/"
    assert _ps_date(stamp) == datetime.fromtimestamp(1788901200)
    assert _ps_date({"value": stamp, "DateTime": "9 Eylül 2026"}) == datetime.fromtimestamp(1788901200)
    assert _ps_date(None) is None and _ps_date({}) is None


def test_another_antivirus_in_charge_is_not_reported_as_a_fault(monkeypatch):
    # With McAfee installed Windows keeps Defender passive, real-time off by
    # design. The score once marked that red and said "turn it back on".
    from jarvis.ten import shield10

    rows = [{"displayName": "Windows Defender", "productState": 393472},   # 0x060100: passive
            {"displayName": "McAfee", "productState": 266240}]             # 0x041000: on, up to date
    monkeypatch.setattr(shield10, "ps_json", lambda script, timeout=30: rows if "SecurityCenter2" in script else [])
    assert [(p["name"], p["on"], p["current"]) for p in shield10.antivirus_products()] == [
        ("Windows Defender", False, True), ("McAfee", True, True)]
    assert shield10.other_antivirus()["name"] == "McAfee"

    passive = {"service": True, "antivirus": True, "realtime": False, "behavior": False, "tamper": False,
               "mode": "SxS Passive Mode", "signatures": None, "version": "1.2", "quick_age": None,
               "full_age": None, "quick_end": None, "full_end": None}
    monkeypatch.setattr(shield10, "defender", lambda: passive)
    monkeypatch.setattr(shield10, "firewall", lambda: [{"name": "Domain", "on": True}])
    monkeypatch.setattr(shield10, "last_update", lambda: None)
    value, checks = shield10.score()
    names = {c["name"]: c["ok"] for c in checks}
    assert names["Real-time protection is on (McAfee)"] and names["Antivirus is on (McAfee)"]
    assert not any("Defender" in name for name in names)
    reply = shield10.Shield10().defender_cmd("")
    assert "McAfee is your active antivirus" in reply and "passive" in reply


def test_scanner_says_so_when_defender_is_missing(monkeypatch, tmp_path):
    from jarvis.ten import shield10

    monkeypatch.setattr(shield10, "MPCMD", tmp_path / "missing.exe")
    assert "isn't available" in shield10.scanner.start("quick")


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_pc_security_and_antivirus_pages_open(app, monkeypatch):
    from jarvis.ten import shield10, system

    monkeypatch.setattr(system, "nvidia", lambda: [])
    monkeypatch.setattr(system, "gpu_load_counters", lambda: None)
    monkeypatch.setattr(system, "cpu_temperature", lambda: None)
    monkeypatch.setattr(shield10, "score", lambda: (80, [{"name": "Firewall", "ok": False, "weight": 1, "fix": "on",
                                                          "page": "firewall"}]))
    monkeypatch.setattr(shield10, "defender", lambda: {})
    monkeypatch.setattr(shield10, "other_antivirus", lambda: None)
    monkeypatch.setattr(app, "run_tool", lambda text, done, name="": None)
    for key in ("pc", "security", "antivirus"):
        app._show_tab(key)
        app.update()
        assert app.active_tab == key and app.pages[key].grid_info() and app.pages[key]._built
    pc = app.pages["pc"]
    pc.tick()
    assert pc.values["cpu"].cget("text").endswith("%")
