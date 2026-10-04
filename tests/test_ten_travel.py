"""10.0 travel and maps: map maths, nearby places (and the fallback when
Overpass is busy), saved places, trip budgets, itineraries into the
calendar, the documents checklist, jet lag, and the two pages."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis import travel


def test_map_maths_round_trips():
    x, y = travel.to_pixels(41.0256, 28.9742, 15)
    lat, lon = travel.to_latlon(x, y, 15)
    assert abs(lat - 41.0256) < 1e-6 and abs(lon - 28.9742) < 1e-6
    assert travel.to_pixels(0, 0, 0) == (128.0, 128.0)
    assert 340_000 < travel.distance_m(41.0082, 28.9784, 39.9334, 32.8597) < 360_000     # Istanbul-Ankara
    assert travel.show_distance(850) == "850 m" and travel.show_distance(2345) == "2.3 km"
    assert travel.nearby_kind("eczane") == "pharmacy" and travel.nearby_kind("ATMs") == "atm"


def test_nearby_from_overpass_and_the_fallback(monkeypatch):
    calls = []

    def fake_get(url, timeout=20):
        calls.append(url)
        if "overpass" in url:
            return json.dumps({"elements": [
                {"lat": 41.0260, "lon": 28.9745, "tags": {"name": "Galata Eczanesi", "opening_hours": "09:00-19:00"}},
                {"center": {"lat": 41.0300, "lon": 28.9800}, "tags": {"brand": "Far Eczane"}},
                {"lat": 41.2, "lon": 29.2, "tags": {"name": "Too far"}}]}).encode()
        raise AssertionError(url)

    monkeypatch.setattr(travel, "_get", fake_get)
    rows = travel.nearby(41.0256, 28.9742, "pharmacy")
    assert [r["name"] for r in rows] == ["Galata Eczanesi", "Far Eczane"] and rows[0]["distance"] < 60
    assert rows[0]["hours"] == "09:00-19:00"

    def busy(url, timeout=20):
        raise travel.TravelError("504 Gateway Timeout")

    monkeypatch.setattr(travel, "_get", busy)
    monkeypatch.setattr(travel, "_nominatim", lambda params: [
        {"name": "Hilal Eczanesi", "lat": "41.0262", "lon": "28.9750", "display_name": "Hilal Eczanesi, Kuledibi"}])
    rows = travel.nearby(41.0256, 28.9742, "pharmacy")
    assert rows[0]["name"] == "Hilal Eczanesi" and rows[0]["address"] == "Kuledibi"


def test_saved_places_and_where_i_am(base, monkeypatch):
    from jarvis.ten import travel10

    monkeypatch.setattr(travel, "search", lambda q, limit=6: [{"name": "Moda", "label": "Moda", "lat": 40.98,
                                                                "lon": 29.02, "kind": "suburb"}])
    tool = travel10.Travel10()
    assert "Saved Home" in tool.places_cmd("add Home | Moda Caddesi 12")
    assert "Saved Work" in tool.places_cmd("add Work | 41.0786, 29.0125 | the office")
    listing = tool.places_cmd("")
    assert "Home — 40.9800" in listing and "the office" in listing
    assert travel.where_am_i() == ("Home", 40.98, 29.02)
    assert "Removed Work" in tool.places_cmd("remove work")


def test_nearby_command(base, monkeypatch):
    from jarvis.ten import travel10

    monkeypatch.setattr(travel, "search", lambda q, limit=6: [{"name": "Kadıköy", "lat": 40.99, "lon": 29.03,
                                                                "label": "", "kind": ""}])
    monkeypatch.setattr(travel, "nearby", lambda lat, lon, kind: [
        {"name": "Moda Eczanesi", "distance": 240, "address": "Moda Cd.", "hours": "", "lat": 0, "lon": 0}])
    reply = travel10.Travel10().nearby_cmd("eczane near Kadıköy")
    assert "Nearest pharmacies to Kadıköy" in reply and "240 m  Moda Eczanesi — Moda Cd." in reply
    assert "OpenStreetMap" in reply
    assert "Nearby what?" in travel10.Travel10().nearby_cmd("unicorns")


class Brain:
    def __init__(self, reply):
        self.reply = reply

    def ask_once(self, prompt, **kw):
        return self.reply


def test_trip_budget_converts_to_lira(base, monkeypatch):
    from jarvis import calc
    from jarvis.ten import travel10

    tool = travel10.Travel10()
    tool.brain = Brain(json.dumps({"currency": "EUR", "per_day_per_person": {"stay": 60, "food": 40, "transport": 10,
                                                                             "activities": 20, "other": 10},
                                   "tips": ["Buy a 72-hour transit pass"]}))
    monkeypatch.setattr(calc, "convert_currency", lambda amount, a, b: (amount * 50, "test rates"))
    reply = tool.tripbudget_cmd("Rome | 5 | 2 | mid")
    assert "1,400 EUR" in reply and "≈ 70,000 TRY" in reply and "72-hour" in reply


def test_itinerary_goes_into_the_calendar(base):
    from jarvis import life
    from jarvis.ten import travel10

    tool = travel10.Travel10()
    tool.brain = Brain(json.dumps({"title": "Rome", "days": [
        {"day": 1, "items": [{"time": "09:00", "minutes": 120, "title": "Colosseum", "where": "Piazza del Colosseo"}]},
        {"day": 2, "items": [{"time": "10:30", "title": "Vatican Museums"}]}]}))
    reply = tool.itinerary_cmd("2 days in Rome | 14.11.2026 | add")
    assert "Sat 14 Nov" in reply and "09:00  Colosseum — Piazza del Colosseo" in reply and ".ics" in reply
    events = life.CALENDAR.load()
    assert [e["title"] for e in events] == ["Colosseum", "Vatican Museums"]
    assert datetime.fromtimestamp(events[1]["start"]) == datetime(2026, 11, 15, 10, 30)


def test_documents_checklist(base):
    from jarvis.ten import travel10

    reply = travel10.Travel10().traveldocs_cmd("Rome | done 1")
    assert "1/18 ready" in reply and "☑ 1. Passport valid" in reply


def test_jet_lag():
    plan = travel.jetlag_plan(ZoneInfo("Europe/Istanbul"), ZoneInfo("Asia/Tokyo"), datetime(2026, 11, 14, 21, 30))
    assert plan["hours"] == 6 and plan["east"] and plan["days"] == 6
    assert len(plan["before"]) == 3 and "3 h earlier" in plan["before"][-1]
    west = travel.jetlag_plan(ZoneInfo("Europe/Istanbul"), ZoneInfo("America/New_York"), datetime(2026, 11, 14, 9))
    assert west["hours"] == -8 and not west["east"] and west["days"] == 6 and "later" in west["before"][0]
    from jarvis.ten import travel10

    assert "little or no jet lag" in travel10.Travel10().jetlag_cmd("Istanbul | Athens | 14.11.2026 10:00")


from tests.test_gui import _display_available, app  # noqa: E402,F401
from tests.test_ten_ui import inline  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_map_and_travel_pages(app, inline, monkeypatch, tmp_path):
    from PIL import Image

    tile_file = tmp_path / "tile.png"
    Image.new("RGB", (256, 256), "#aad3df").save(tile_file)
    monkeypatch.setattr(travel, "tile", lambda z, x, y: tile_file)
    monkeypatch.setattr(travel, "where_am_i", lambda: ("Home", 41.0256, 28.9742))
    monkeypatch.setattr(travel, "search", lambda q, limit=6: [{"name": "Galata Kulesi", "label": "", "lat": 41.0256,
                                                                "lon": 28.9742, "kind": "tower"}])
    monkeypatch.setattr(travel, "nearby", lambda lat, lon, kind: [
        {"name": "Hilal Eczanesi", "lat": 41.0262, "lon": 28.975, "distance": 70, "icon": "💊", "address": "",
         "hours": "", "phone": ""}])
    app._show_tab("map")
    app.update()
    page = app.pages["map"]
    assert page.here == (41.0256, 28.9742) and page.map.zoom == 14
    page.map.draw()
    assert page.map.images                      # tiles came in
    before = page.map.center
    page.map._press(type("E", (), {"x": 100, "y": 100})())
    page.map._move(type("E", (), {"x": 160, "y": 100})())
    assert page.map.center[1] < before[1]       # dragged right → looking further west
    page.map.zoom_at(200, 200, 1)
    assert page.map.zoom == 15
    page.open_target("Galata Kulesi")
    assert page.results.size() == 1 and page.map.pins[0]["label"] == "Galata Kulesi"
    page.around("pharmacy")
    assert "70 m" in page.results.get(0)
    page.map.pins.clear()
    page.close()
    app._show_tab("travel")
    app.update()
    travel_page = app.pages["travel"]
    travel_page.tick(0, True)
    assert travel.TRAVEL_DOCS.load()["My trip"] == [0] and travel_page.progress.cget("text").startswith("1/")
