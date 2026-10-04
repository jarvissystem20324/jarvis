"""10.0 everyday, health, money and Türkiye: exact answers checked exactly
(moon, ages, units, scaling, BMI, KDV, settling up), imports and alerts, and
the four pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from fractions import Fraction

import pytest

from jarvis import daily, money, spending, turkey


# --- everyday ----------------------------------------------------------------------------------------

def test_the_moon():
    full = daily.moon(datetime(2026, 1, 3, 10, 0))      # a full moon
    new = daily.moon(datetime(2026, 1, 18, 20, 0))      # a new moon
    assert full["name"] == "Full moon" and full["lit"] > 0.97 and full["tr"] == "Dolunay"
    assert new["name"] == "New moon" and new["lit"] < 0.03
    assert 0 < (daily.moon(datetime(2026, 1, 10))["next_full"] - date(2026, 1, 10)).days <= 30


def test_dates_and_ages():
    assert daily.parse_date("14.05.1990") == date(1990, 5, 14) == daily.parse_date("1990-05-14")
    assert daily.parse_date("14 Mayıs 1990") == date(1990, 5, 14) == daily.parse_date("May 14, 1990")
    with pytest.raises(ValueError):
        daily.parse_date("someday")
    a = daily.age(date(1990, 5, 14), today=date(2026, 10, 4))
    assert (a["years"], a["months"], a["days"]) == (36, 4, 20)
    assert a["next_birthday"] == date(2027, 5, 14) and a["turning"] == 37
    leap = daily.age(date(2000, 2, 29), today=date(2026, 3, 1))
    assert leap["years"] == 26 and leap["next_birthday"] == date(2027, 2, 28)
    gap = daily.date_gap(date(2026, 10, 5), date(2026, 10, 19))
    assert gap["days"] == 14 and gap["weekdays"] == 10 and gap["weeks"] == 2
    assert daily.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_what_to_wear():
    cold = daily.what_to_wear(-3, 2, rain=70, wind=45)
    assert any("freezing" in s for s in cold) and any("umbrella" in s for s in cold) and any("windy" in s for s in cold)
    hot = daily.what_to_wear(24, 35, uv=9)
    assert any("Light" in s for s in hot) and any("layers" in s for s in hot) and any("UV 9" in s for s in hot)


def test_recipes_scale_exactly():
    recipe = "2 su bardağı un\n1/2 çay kaşığı tuz\n1½ cups milk\n3-4 eggs\n200 g butter"
    doubled = daily.scale_recipe(recipe, Fraction(2))
    assert doubled.splitlines() == ["4 su bardağı un", "1 çay kaşığı tuz", "3 cups milk", "6-8 eggs", "400 g butter"]
    assert daily.scale_recipe("3 eggs", Fraction(1, 2)) == "1½ eggs"
    assert daily.show_amount(Fraction(1, 3)) == "⅓" and daily.show_amount(Fraction(25, 2)) == "12.5"


def test_kitchen_units_including_turkish_ones():
    assert daily.kitchen_convert("2 cups flour to grams") == "2 cups flour ≈ 251 grams"
    assert daily.kitchen_convert("1 su bardağı süt kaç ml") == "1 su bardağı süt ≈ 200 ml"
    assert daily.kitchen_convert("100 g şeker kaç su bardağı").endswith("0.6 su bardağı")
    assert daily.kitchen_convert("3 tbsp to tsp") == "3 tbsp ≈ 9 tsp"
    with pytest.raises(ValueError):
        daily.kitchen_convert("2 cups to grams")       # of what?


def test_warranties_stash_and_declutter(base):
    from jarvis.ten import lifestyle

    tool = lifestyle.Lifestyle()
    soon = (date.today() - timedelta(days=700)).strftime("%d.%m.%Y")
    assert "under warranty until" in tool.warranty_cmd(f"add Laptop | {soon} | 24 | receipt in the blue folder")
    listing = tool.warranty_cmd("")
    assert "Laptop" in listing and "day(s) left" in listing
    tool.putit_cmd("passport | top drawer of the desk")
    tool.putit_cmd("spare key | under the plant pot")
    assert "top drawer" in tool.whereis_cmd("passport") and "plant pot" in tool.whereis_cmd("key")
    assert "haven't told me" in tool.whereis_cmd("umbrella")
    room = tool.declutter_cmd("kitchen | done 2")
    assert "1/6 done" in room and "☑ 2." in room


def test_the_warranty_reminder_comes_once(base, monkeypatch):
    from jarvis import alerts
    from jarvis.ten import lifestyle

    posted = []
    monkeypatch.setattr(alerts, "post", lambda title, body="", **kw: posted.append(title))
    daily.warranty_add("Phone", date.today() - timedelta(days=360), 12)
    jobs = {}

    class Watchers:
        def add(self, name, seconds, fn, first_after=0):
            jobs[name] = fn

    lifestyle.register_watchers(None, Watchers())
    jobs["warranties"]()
    jobs["warranties"]()
    assert len(posted) == 1 and "Phone" in posted[0]


# --- health ------------------------------------------------------------------------------------------

def test_water_habits_bmi_and_weight(base):
    from jarvis.ten import lifestyle

    tool = lifestyle.Lifestyle()
    assert "Today 250 / 2000 ml" in tool.water_cmd("glass")
    assert "Today 750" in tool.water_cmd("500")
    tool.water_cmd("goal 1000")
    assert "goal reached" in tool.water_cmd("250")
    tool.habit_cmd("add Read 20 pages")
    assert "streak 1" in tool.habit_cmd("done read 20 pages")
    assert daily.habit_streak([(date.today() - timedelta(days=i)).isoformat() for i in range(1, 4)]) == 3
    r = daily.bmi(72, 178)
    assert r["bmi"] == 22.7 and r["category"] == "a healthy weight" and r["healthy"] == (58.6, 78.9)
    assert "BMI 22.7" in tool.bmi_cmd("72 178") and "not medical advice" in tool.bmi_cmd("178 72")
    tool.weight_cmd("80")
    assert daily.WEIGHTS.load()[-1]["kg"] == 80.0


def test_food_lookup_reads_open_food_facts(monkeypatch):
    from jarvis import kit

    monkeypatch.setattr(kit, "get_json", lambda url, params=None, **kw: {"products": [
        {"product_name": "Ayran", "brands": "Sütaş,Other", "nutriments": {"energy-kcal_100g": 37, "proteins_100g": 1.7,
                                                                        "carbohydrates_100g": 2.6, "fat_100g": 2}},
        {"product_name": "No energy", "nutriments": {}},
        {"product_name": "Kilojoules only", "nutriments": {"energy_100g": 418.4}}]})
    rows = daily.food_lookup("ayran")
    assert rows[0] == {"name": "Ayran", "brand": "Sütaş", "kcal": 37, "protein": 1.7, "carbs": 2.6, "fat": 2}
    assert rows[1]["kcal"] == 100 and len(rows) == 2


# --- money -------------------------------------------------------------------------------------------

def test_budgets_alert_at_80_and_100_percent(base, monkeypatch):
    from jarvis import alerts
    from jarvis.toolkit import Toolkit

    posted = []
    monkeypatch.setattr(alerts, "post", lambda title, body="", **kw: posted.append(title))
    money.set_budget("food", 1000)
    toolkit = Toolkit()
    toolkit.spent("700 tl lunch #food")
    assert posted == []
    reply = toolkit.spent("150 tl dinner #food")
    assert "85% of your food budget" in reply and len(posted) == 1
    toolkit.spent("200 tl pizza #food")
    assert "Over your food budget" in posted[-1]
    status = money.budget_status()
    assert status[0]["category"] == "food" and status[0]["spent"] == 1050


def test_bank_and_card_statements_import_once(base, tmp_path):
    bank = tmp_path / "hesap.csv"
    bank.write_text("Hesap Hareketleri\nTarih;Açıklama;Tutar;Bakiye\n"
                    "01.10.2026;MIGROS KADIKOY;-1.250,50;10.000,00\n"
                    "02.10.2026;MAAŞ;25.000,00;35.000,00\n"
                    "03.10.2026;UBER TRIP;-180,00;34.820,00\n", encoding="cp1254")
    rows = money.read_statement(bank)
    assert [(r["day"], r["what"], r["amount"]) for r in rows] == [
        (date(2026, 10, 1), "MIGROS KADIKOY", 1250.5), (date(2026, 10, 3), "UBER TRIP", 180.0)]
    assert money.import_statement(bank) == (2, 0)
    assert money.import_statement(bank) == (0, 2)            # no duplicates the second time
    categories = {e["what"]: e["category"] for e in spending.load()}
    assert categories["MIGROS KADIKOY"] == "groceries" and categories["UBER TRIP"] == "transport"
    card = tmp_path / "card.csv"
    card.write_text("Date,Description,Amount\n2026-10-05,STEAM PURCHASE,59.99\n2026-10-06,PAYMENT THANK YOU,-500\n"
                    "2026-10-07,NETFLIX,9.99\n2026-10-08,CAFE NERO,4.50\n")
    assert [(r["what"], r["amount"]) for r in money.read_statement(card)] == [
        ("STEAM PURCHASE", 59.99), ("NETFLIX", 9.99), ("CAFE NERO", 4.5)]     # the payment to the card isn't spending


def test_who_owes_who_settles_with_fewest_payments(base):
    money.owe_add("Ali", 600, ["Ali", "Ayşe", "Mehmet"], "dinner")
    money.owe_add("Ayşe", 300, ["Ayşe", "Mehmet"], "taxi")
    net = money.balances()
    assert net == {"Ali": 400.0, "Ayşe": -50.0, "Mehmet": -350.0}
    assert money.settle(net) == [("Mehmet", "Ali", 350.0), ("Ayşe", "Ali", 50.0)]
    from jarvis.ten import lifestyle

    reply = lifestyle.Lifestyle().owe_cmd("Zeynep paid 90 for Zeynep, Ali, Ayşe | coffee")
    assert "30" in reply and "To square up" in reply


def test_the_no_spend_challenge_checks_the_log(base):
    start = date.today() - timedelta(days=2)
    money.nospend_start(7, ["bills"], today=start)
    entries = spending.load()
    entries.append({"amount": 50, "currency": "TRY", "what": "coffee", "category": "food",
                    "at": datetime.combine(start + timedelta(days=1), datetime.min.time()).timestamp()})
    entries.append({"amount": 900, "currency": "TRY", "what": "internet", "category": "bills",
                    "at": datetime.combine(start, datetime.min.time()).timestamp()})
    spending._save(entries)
    status = money.nospend_status()
    assert status["elapsed"] == 3 and status["clean"] == 2 and list(status["slips"].values()) == [["coffee"]]


# --- Türkiye -----------------------------------------------------------------------------------------

def test_kdv_both_ways():
    assert turkey.kdv(1000, 20) == {"net": 1000, "kdv": 200, "gross": 1200, "rate": 20}
    assert turkey.kdv(1200, 20, included=True) == {"net": 1000, "kdv": 200, "gross": 1200, "rate": 20}
    assert turkey.tl(1234.5) == "1.234,50 ₺"
    from jarvis.ten import lifestyle

    reply = lifestyle.Lifestyle().kdv_cmd("1.200 20 dahil")
    assert "KDV hariç: 1.000,00 ₺" in reply and "KDV:       200,00 ₺" in reply


def test_traffic_and_bayrams(base, monkeypatch):
    from jarvis import kit

    def fake(url, params=None, **kw):
        if "TrafficIndex_Sc1_Cont" in url:
            return {"TI": 63, "TI_An": 63, "TI_Av": 48}
        if "History" in url:
            return [{"TrafficIndex": 40, "TrafficIndexDate": "2026-10-04T18:00:00"},
                    {"TrafficIndex": 63, "TrafficIndexDate": "2026-10-04T18:05:00"}]
        return [{"date": "2026-10-29", "localName": "Cumhuriyet Bayramı", "name": "Republic Day"},
                {"date": "2027-03-09", "localName": "Ramazan Bayramı 1. Gün", "name": "Eid al-Fitr"},
                {"date": "2027-03-10", "localName": "Ramazan Bayramı 2. Gün", "name": "Eid al-Fitr"},
                {"date": "2027-03-11", "localName": "Ramazan Bayramı 3. Gün", "name": "Eid al-Fitr"}]

    monkeypatch.setattr(kit, "get_json", fake)
    assert turkey.traffic_now() == {"now": 63, "usual": 48}
    assert [v for _, v in turkey.traffic_history()] == [40, 63]
    from jarvis.ten import lifestyle

    assert "63% — heavy, 15 points worse than usual" in lifestyle.Lifestyle().traffic_cmd("")
    items = turkey.upcoming(today=date(2026, 10, 28))
    assert items[0]["base"] == "Cumhuriyet Bayramı" and items[0]["in_days"] == 1
    ramazan = next(i for i in items if i["base"] == "Ramazan Bayramı")
    assert ramazan["days"] == 3 and ramazan["first"] == date(2027, 3, 9)


def test_edevlet_links():
    names = [name for name, _, _ in turkey.EDEVLET]
    assert "SGK Tescil ve Hizmet Dökümü" in names and all(url.startswith("https://") for _, url, _ in turkey.EDEVLET)
    from jarvis.ten import lifestyle

    assert "sgk-tescil" in lifestyle.Lifestyle().edevlet_cmd("hizmet dökümü")
    assert "arama?aranan=pasaport" in lifestyle.Lifestyle().edevlet_cmd("pasaport")


# --- the pages ---------------------------------------------------------------------------------------

from tests.test_gui import _display_available, app  # noqa: E402,F401
from tests.test_ten_ui import inline  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_four_life_pages(app, inline, monkeypatch):
    from jarvis import kit, weather

    monkeypatch.setattr(weather, "home_city", lambda: "")
    monkeypatch.setattr(kit, "get_json", lambda *a, **k: (_ for _ in ()).throw(kit.KitError("offline")))
    for key in ("everyday", "health", "money", "turkey"):
        app._show_tab(key)
        app.update()
        assert app.pages[key]._built and app.active_tab == key
    everyday = app.pages["everyday"]
    assert "lit" in everyday.moon_label.cget("text") and len(everyday.clock_labels) == 4
    everyday.tick_room(0, True)
    assert daily.DECLUTTER.load()[everyday.room.get()] == [0]
    health = app.pages["health"]
    health.drink(250)
    assert health.water_label.cget("text").startswith("250 /")
    health.preset.set("Tabata 20/10 × 8")
    health.reset_timer()
    assert health.plan[0] == ("GET READY", 5, 0) and len(health.plan) == 17
    health.running, health.left = True, 1
    health.tick_timer()
    assert health.step == 1 and health.left == 20 and "WORK" in health.phase.cget("text")
    health.running = False
    health.toggle_breathing()
    health.animate_breath()
    assert "Breathe in" in health.circle.itemcget(health.circle.find_all()[-1], "text")
    health.stop_breathing()
    money_page = app.pages["money"]
    money_page.start_nospend(5)
    assert "Day 1 of 5" in " ".join(w.cget("text") for w in money_page.nospend_box.winfo_children()
                                    if hasattr(w, "cget") and isinstance(w.cget("text"), str))
    turkey_page = app.pages["turkey"]
    assert "İBB yanıt vermedi" in turkey_page.traffic_words.cget("text")
