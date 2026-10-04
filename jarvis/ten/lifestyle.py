"""10.0 everyday life, health, money and Türkiye — the commands behind the
Everyday, Health, Money and Türkiye pages.

The logic lives in jarvis/daily.py, jarvis/money.py and jarvis/turkey.py;
this module turns it into commands and runs the gentle background checks:
a warranty about to run out, water when you're behind, strong UV in the
morning, and a bayram tomorrow.
"""

from __future__ import annotations

import base64
import io
import re
import time
from datetime import date, datetime, timedelta
from fractions import Fraction

from .. import alerts, daily, kit, money, prefs, spending, turkey
from ..registry import command, field, split

EVERYDAY, HEALTH, TR = "Everyday", "Health and money", "Türkiye"
NOT_ADVICE = "(General information, not medical advice.)"
REMINDED = kit.Store("life_reminders.json", {})


def _money(value: float) -> str:
    return spending.money(value, spending.default_currency())


class Lifestyle:
    # --- everyday ---------------------------------------------------------------------------------
    @command("moon", group=EVERYDAY, usage="/moon [date]", help="the moon's phase, and the next full and new moon",
             title="Moon phase", icon="🌙", page="everyday", fields=(field("day", "date", "Date", optional=True),))
    def moon_cmd(self, args: str, routed: bool = False):
        try:
            day = daily.parse_date(args) if args.strip() else None
        except ValueError as exc:
            return str(exc)
        m = daily.moon(datetime.combine(day, datetime.min.time()).replace(hour=12) if day else None)
        return (f"{m['emoji']} {m['name']} ({m['tr']}) — {m['lit'] * 100:.0f}% lit, {m['age']:.1f} days old.\n"
                f"Next full moon {m['next_full']:%a %d %b}, next new moon {m['next_new']:%a %d %b}.")

    @command("worldclock", "clocks", group=EVERYDAY, usage="/worldclock · /worldclock add <city> · remove <city>",
             help="your board of clocks around the world", title="World clock board", icon="🕰", page="everyday",
             fields=(field("action", "choice", "Action", "add", ("add", "remove")), field("city", "text", "City")),
             template="{action} {city}")
    def worldclock_cmd(self, args: str, routed: bool = False):
        from .. import clock

        cities = prefs.get("world_clocks", ["Istanbul", "London", "New York", "Tokyo"])
        verb, _, place = args.strip().partition(" ")
        if verb.lower() in {"add", "remove", "ekle", "sil"} and place.strip():
            if verb.lower() in {"add", "ekle"}:
                try:
                    clock.zone_for(place)
                except clock.ClockError as exc:
                    return str(exc)
                cities = [c for c in cities if c.lower() != place.strip().lower()] + [place.strip().title()]
            else:
                cities = [c for c in cities if c.lower() != place.strip().lower()]
            prefs.set("world_clocks", cities)
        lines = ["🕰 World clocks:"]
        for city in cities:
            try:
                label, zone = clock.zone_for(city)
            except clock.ClockError:
                continue
            now = datetime.now(zone)
            hours = now.utcoffset().total_seconds() / 3600
            lines.append(f"  {label:<14} {now:%H:%M}  {now:%a}  (UTC{hours:+g})")
        return "\n".join(lines)

    @command("age", group=EVERYDAY, usage="/age <birth date>", help="exactly how old, and days to the next birthday",
             title="Age calculator", icon="🎂", page="everyday", fields=(field("born", "date", "Born on"),))
    def age_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /age 14.05.1990"
        try:
            a = daily.age(daily.parse_date(args))
        except ValueError as exc:
            return str(exc)
        return (f"🎂 {a['years']} years, {a['months']} months and {a['days']} days — {a['total_days']:,} days "
                f"({a['weeks']:,} weeks). Born on a {a['weekday']}.\nTurning {a['turning']} on "
                f"{a['next_birthday']:%d %b %Y}, in {a['days_to_birthday']} day(s).")

    @command("datediff", "days", group=EVERYDAY, usage="/datediff <date> [| <date>]",
             help="days, weeks and working days between two dates (or from today)", title="Date difference",
             icon="📆", page="everyday", fields=(field("start", "date", "From"), field("end", "date", "To")))
    def datediff_cmd(self, args: str, routed: bool = False):
        first, second = split(args, 2)
        if not first.strip():
            return "Usage: /datediff 01.01.2026 | 29.10.2026"
        try:
            a, b = daily.parse_date(first), daily.parse_date(second or "today")
        except ValueError as exc:
            return str(exc)
        gap = daily.date_gap(a, b)
        return (f"📆 {gap['days']} day(s) — {gap['weeks']} week(s) and {gap['rest']} day(s), about "
                f"{gap['months']} months. Working days (Mon-Fri): {gap['weekdays']}.")

    @command("wear", "outfit", group=EVERYDAY, usage="/wear [city]", help="what to wear for today's weather",
             title="What to wear", icon="🧥", page="everyday", fields=(field("city", "text", "City", optional=True),))
    def wear_cmd(self, args: str, routed: bool = False):
        from .. import weather

        city = args.strip() or weather.home_city()
        if not city:
            return "Which city? /wear Ankara (or set your city in Settings)."
        try:
            day = daily.day_forecast(city)
        except weather.WeatherError as exc:
            return str(exc)
        advice = daily.what_to_wear(day["low"], day["high"], day["rain"], day["wind"], day["uv"])
        return (f"🧥 {day['place']} today: {day['low']:.0f}° to {day['high']:.0f}°, rain {day['rain']:.0f}%, "
                f"wind up to {day['wind']:.0f} km/h, UV {day['uv']:.0f}.\n" + "\n".join(advice))

    @command("fridgephoto", group=EVERYDAY, usage="/fridgephoto <photo of your fridge or counter>",
             help="recipes from what's in a photo of your fridge", title="Recipe from a fridge photo", icon="📸",
             page="everyday", fields=(field("photo", "file", "Photo", types=(("Pictures", "*.jpg *.jpeg *.png"),)),))
    def fridgephoto_cmd(self, args: str, routed: bool = False):
        from PIL import Image

        path = kit.path_arg(args) or getattr(self, "current_image", None)
        if not path:
            return "Usage: /fridgephoto C:/photos/fridge.jpg (or attach a photo first)"
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
        except OSError:
            return "I can't open that as a picture."
        image.thumbnail((1280, 1280))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85)
        return "📸 " + self.brain.ask_once(
            "List the foods you can clearly see in this photo of a fridge or kitchen counter (say if you're unsure "
            "of any). Then suggest 3 recipes that use mostly those, each with the extra ingredients needed and "
            "short steps. Answer in the user's language.",
            image_b64=base64.b64encode(buffer.getvalue()).decode("ascii")).strip()

    @command("grocery", "groceries", group=EVERYDAY, usage="/grocery <recipe or link> [| add]",
             help="a shopping list from a recipe, grouped by aisle — add it to /mylist if you like",
             title="Grocery list from a recipe", icon="🛒", page="everyday",
             fields=(field("recipe", "long", "Recipe (or a link to one)"),
                     field("add", "bool", "Add to my to-do list", "")),
             template="{recipe} | {add}")
    def grocery_cmd(self, args: str, routed: bool = False):
        recipe, add = split(args, 2)
        recipe = recipe.strip()
        if not recipe:
            return "Usage: /grocery <paste a recipe or a link> | add"
        if re.match(r"https?://", recipe):
            try:
                html = kit.get_text(recipe, limit=1_500_000)
            except kit.KitError as exc:
                return f"🛒 Couldn't open the link: {exc}"
            recipe = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", "", html)))
            recipe = recipe[:20000]
        try:
            data = kit.ask_json(self.brain, (
                "From this recipe, list the ingredients to buy as JSON: {\"items\": [{\"item\": \"...\", "
                "\"amount\": \"...\", \"aisle\": \"produce|meat and fish|dairy|bakery|pantry|frozen|spices|other\"}]}. "
                "Keep the recipe's language. Leave out water.\n\n" + recipe), room=2500)
        except Exception:
            return "🛒 I couldn't read a list of ingredients from that."
        items = [i for i in (data.get("items") if isinstance(data, dict) else []) or [] if i.get("item")]
        if not items:
            return "🛒 No ingredients found in that."
        by_aisle: dict[str, list[str]] = {}
        for i in items:
            by_aisle.setdefault(i.get("aisle") or "other", []).append(
                f"{i['item']}" + (f" — {i['amount']}" if i.get("amount") else ""))
        lines = ["🛒 Shopping list:"]
        for aisle, things in by_aisle.items():
            lines.append(f"  {aisle.capitalize()}:")
            lines += [f"    ☐ {t}" for t in things]
        if add.strip().lower() in {"add", "on", "yes", "true", "ekle"}:
            for i in items:
                self.eight_command("mylist", f"add {i['item']}")
            lines.append(f"Added {len(items)} item(s) to /mylist.")
        return "\n".join(lines)

    @command("scale", "scalerecipe", group=EVERYDAY, usage="/scale <recipe> | <serves now> | <serves wanted>",
             help="every amount in a recipe scaled for more or fewer people", title="Recipe scaler", icon="⚖",
             page="everyday", fields=(field("recipe", "long", "Recipe"), field("serves", "number", "It serves", "4"),
                                      field("want", "number", "I need it for", "6")))
    def scale_cmd(self, args: str, routed: bool = False):
        recipe, now, want = split(args, 3)
        try:
            factor = Fraction(int(want), int(now))
        except (ValueError, ZeroDivisionError):
            return "Usage: /scale <recipe> | 4 | 6   (serves 4 now, I need 6)"
        if not recipe.strip():
            return "Usage: /scale <recipe> | 4 | 6"
        return f"⚖ For {want.strip()} (×{daily.show_amount(factor)}):\n" + daily.scale_recipe(recipe.strip(), factor)

    @command("kitchen", group=EVERYDAY, usage="/kitchen 2 cups flour to grams · 200 g un kaç su bardağı",
             help="kitchen units: cups, spoons, su/çay bardağı, grams — by what the ingredient weighs",
             title="Kitchen unit converter", icon="🥄", page="everyday",
             fields=(field("question", "text", "Convert", hint="1 su bardağı un kaç gram"),))
    def kitchen_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /kitchen 2 cups flour to grams · /kitchen 1 su bardağı süt kaç ml"
        try:
            return "🥄 " + daily.kitchen_convert(args)
        except ValueError as exc:
            return str(exc)

    @command("warranty", "warranties", group=EVERYDAY,
             usage="/warranty add <item> | <date bought> | <months> [| note] · /warranty · /warranty remove <n>",
             help="your warranties, and a nudge before one runs out", title="Warranty tracker", icon="🧾",
             page="everyday", fields=(field("item", "text", "Item"), field("bought", "date", "Bought on"),
                                      field("months", "number", "Warranty (months)", "24"),
                                      field("note", "text", "Note (where's the receipt?)", optional=True)),
             template="add {item} | {bought} | {months} | {note}")
    def warranty_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            item, bought, months, note = split(rest, 4)
            try:
                entry = daily.warranty_add(item, daily.parse_date(bought or "today"), int(months or 24), note)
            except ValueError as exc:
                return str(exc)
            return f"🧾 {entry['item']}: under warranty until {date.fromisoformat(entry['until']):%d %b %Y}."
        if verb.lower() in {"remove", "delete"} and rest.strip().isdigit():
            rows = daily.warranties()
            index = int(rest) - 1
            if 0 <= index < len(rows):
                gone = rows[index]
                daily.WARRANTIES.save([r for r in daily.WARRANTIES.load() if r != {k: v for k, v in gone.items()
                                                                               if k != "days_left"}])
                return f"🧾 Removed {gone['item']}."
        rows = daily.warranties()
        if not rows:
            return "🧾 No warranties yet. /warranty add Laptop | 12.03.2025 | 24 | receipt in the blue folder"
        lines = ["🧾 Warranties (soonest first):"]
        for i, r in enumerate(rows, 1):
            state = "expired" if r["days_left"] < 0 else f"{r['days_left']} day(s) left"
            lines.append(f"  {i}. {r['item']} — until {date.fromisoformat(r['until']):%d %b %Y} ({state})"
                         + (f" · {r['note']}" if r.get("note") else ""))
        return "\n".join(lines)

    @command("putit", "stash", group=EVERYDAY, usage="/putit <thing> | <where>",
             help="remember where you put something", title="Where I put it", icon="📦", page="everyday",
             fields=(field("thing", "text", "Thing"), field("where", "text", "Where")))
    def putit_cmd(self, args: str, routed: bool = False):
        thing, place = split(args, 2)
        if not thing.strip() or not place.strip():
            return "Usage: /putit passport | top drawer of the desk"
        daily.stash_put(thing, place)
        return f"📦 Noted: {thing.strip()} is in {place.strip()}. Ask /whereis {thing.strip().split()[0]}."

    @command("whereis", group=EVERYDAY, usage="/whereis <thing>", help="where you said you put something",
             title="Where did I put it?", icon="🔍", page="everyday", fields=(field("thing", "text", "Thing"),))
    def whereis_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            rows = daily.STASH.load()
            if not rows:
                return "📦 Nothing noted yet. /putit passport | top drawer"
            return "📦 Things you've put away:\n" + "\n".join(f"  {r['thing']} → {r['place']}" for r in rows[-20:])
        hits = daily.stash_find(args)
        if not hits:
            return f"📦 You haven't told me where {args.strip()} is."
        return "\n".join(f"📦 {h['thing']}: {h['place']} (noted {h['at'].replace('T', ' ')})" for h in hits[:5])

    @command("declutter", group=EVERYDAY, usage="/declutter [room] · /declutter <room> | done <n>",
             help="a decluttering checklist for each room, ticked off as you go", title="Decluttering checklist",
             icon="🧹", page="everyday", fields=(field("room", "choice", "Room", "Kitchen", tuple(daily.CHECKLISTS)),))
    def declutter_cmd(self, args: str, routed: bool = False):
        room_text, action = split(args, 2)
        room = next((r for r in daily.CHECKLISTS if r.lower().startswith(room_text.strip().lower())), None) \
            if room_text.strip() else None
        state = daily.DECLUTTER.load()
        if room is None:
            return "🧹 Rooms: " + ", ".join(f"{r} ({len(state.get(r, []))}/{len(items)})"
                                           for r, items in daily.CHECKLISTS.items()) + "\n/declutter Kitchen"
        m = re.search(r"done\s+(\d+)", action)
        if m:
            index = int(m.group(1)) - 1
            if 0 <= index < len(daily.CHECKLISTS[room]):
                state[room] = sorted(set(state.get(room, [])) | {index})
                daily.DECLUTTER.save(state)
        done = set(state.get(room, []))
        lines = [f"🧹 {room} — {len(done)}/{len(daily.CHECKLISTS[room])} done:"]
        lines += [f"  {'☑' if i in done else '☐'} {i + 1}. {item}" for i, item in enumerate(daily.CHECKLISTS[room])]
        return "\n".join(lines)

    # --- health -----------------------------------------------------------------------------------
    @command("water", group=HEALTH, usage="/water [ml | glass | bottle] · /water goal 2500 · /water remind on|off",
             help="how much water you've had today, and gentle reminders", title="Water tracker", icon="💧",
             page="health", fields=(field("amount", "choice", "Add", "glass", ("glass", "bottle", "250", "500")),))
    def water_cmd(self, args: str, routed: bool = False):
        text = args.strip().lower()
        settings = daily.HEALTH.load()
        if text.startswith("goal"):
            m = re.search(r"\d+", text)
            if m:
                settings["water_goal"] = int(m.group(0))
                daily.HEALTH.save(settings)
            return f"💧 Daily goal: {settings['water_goal']} ml."
        if text.startswith("remind"):
            settings["water_reminders"] = "off" not in text
            daily.HEALTH.save(settings)
            return "💧 Reminders " + ("on — I'll nudge you when you fall behind (while JARVIS is open)."
                                     if settings["water_reminders"] else "off.")
        amounts = {"glass": 250, "bardak": 250, "cup": 250, "bottle": 500, "şişe": 500, "sise": 500}
        m = re.search(r"\d+", text)
        added = int(m.group(0)) if m else amounts.get(text.split()[0], 0) if text else 0
        total = daily.add_water(added) if added else daily.water_today()
        goal = settings.get("water_goal", 2000)
        bar = "▰" * min(10, int(total / goal * 10)) + "▱" * max(0, 10 - int(total / goal * 10))
        return (f"💧 {'+' + str(added) + ' ml · ' if added else ''}Today {total} / {goal} ml {bar}"
                + (" 🎉 goal reached!" if total >= goal else ""))

    @command("habit", "habits", group=HEALTH, usage="/habit add <name> · /habit done <name> · /habit · "
                                                   "/habit remove <name>",
             help="habits with streaks: tick them off each day", title="Habit tracker", icon="✅", page="health",
             fields=(field("action", "choice", "Action", "done", ("done", "add", "remove")),
                     field("name", "text", "Habit")), template="{action} {name}")
    def habit_cmd(self, args: str, routed: bool = False):
        verb, _, name = args.strip().partition(" ")
        data = daily.HABITS.load()
        key = next((k for k in data if k.lower() == name.strip().lower()), None)
        if verb.lower() == "add" and name.strip():
            data.setdefault(name.strip(), [])
            daily.HABITS.save(data)
            return f"✅ Tracking {name.strip()}. Tick it with /habit done {name.strip()}."
        if verb.lower() in {"done", "did", "yaptım"} and name.strip():
            streak = daily.habit_done(key or name)
            return f"✅ {key or name.strip()} done today — streak {streak} day(s)."
        if verb.lower() in {"remove", "delete"} and key:
            del data[key]
            daily.HABITS.save(data)
            return f"Stopped tracking {key}."
        if not data:
            return "✅ No habits yet. /habit add Read 20 pages"
        today = date.today()
        lines = ["✅ Habits (last 7 days):"]
        for name_, days in data.items():
            marks = "".join("●" if (today - timedelta(days=6 - i)).isoformat() in days else "·" for i in range(7))
            lines.append(f"  {marks}  {name_} — streak {daily.habit_streak(days)}")
        return "\n".join(lines)

    @command("kcal", "calories", group=HEALTH, usage="/kcal <food>",
             help="calories, protein, carbs and fat per 100 g, from Open Food Facts", title="Food calorie lookup",
             icon="🍎", page="health", fields=(field("food", "text", "Food", hint="ayran, simit, Nutella"),))
    def kcal_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /kcal ayran"
        try:
            rows = daily.food_lookup(args.strip())
        except kit.KitError as exc:
            return f"🍎 Open Food Facts didn't answer: {exc}"
        if not rows:
            return f"🍎 Nothing found for {args.strip()!r}."

        def grams(v):
            return f"{float(v):.1f} g" if v is not None else "?"

        lines = [f"🍎 Per 100 g (Open Food Facts):"]
        lines += [f"  {r['name']}" + (f" ({r['brand']})" if r["brand"] else "") +
                  f": {r['kcal']} kcal · protein {grams(r['protein'])} · carbs {grams(r['carbs'])} · fat "
                  f"{grams(r['fat'])}" for r in rows]
        return "\n".join(lines)

    @command("bmi", group=HEALTH, usage="/bmi <weight kg> <height cm>", help="body mass index and the healthy "
                                                                            "range for your height",
             title="BMI calculator", icon="⚖", page="health",
             fields=(field("weight", "number", "Weight (kg)"), field("height", "number", "Height (cm)")))
    def bmi_cmd(self, args: str, routed: bool = False):
        numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", args)]
        if len(numbers) < 2:
            height = daily.HEALTH.load().get("height_cm")
            if numbers and height:
                numbers.append(height)
            else:
                return "Usage: /bmi 72 178   (kg, cm)"
        weight, height = (numbers[0], numbers[1]) if numbers[1] > numbers[0] else (numbers[1], numbers[0])
        try:
            r = daily.bmi(weight, height)
        except ValueError as exc:
            return str(exc)
        settings = daily.HEALTH.load()
        settings["height_cm"] = height
        daily.HEALTH.save(settings)
        return (f"⚖ BMI {r['bmi']} — {r['category']}. At {height:.0f} cm, a healthy weight is about "
                f"{r['healthy'][0]}-{r['healthy'][1]} kg.\nBMI doesn't see muscle or age. {NOT_ADVICE}")

    @command("weight", group=HEALTH, usage="/weight [kg]", help="log your weight and see the trend",
             title="Weight chart", icon="📉", page="health", fields=(field("kg", "number", "Today's weight (kg)",
                                                                        optional=True),))
    def weight_cmd(self, args: str, routed: bool = False):
        from .. import charts
        from ..assistant import JarvisResponse

        m = re.search(r"\d+(?:[.,]\d+)?", args)
        rows = daily.log_weight(float(m.group(0).replace(",", "."))) if m else daily.WEIGHTS.load()
        if not rows:
            return "📉 No weights logged. /weight 72.5"
        recent = rows[-60:]
        change = recent[-1]["kg"] - recent[0]["kg"]
        text = (f"📉 {recent[-1]['kg']} kg on {recent[-1]['day']}" +
                (f" · {change:+.1f} kg since {recent[0]['day']}" if len(recent) > 1 else ""))
        if len(recent) < 2:
            return text
        image = charts.render("line", [r["day"][5:] for r in recent], {"kg": [r["kg"] for r in recent]},
                              title="Weight", size=(900, 420))
        path = kit.output_dir("documents") / f"weight_{kit.stamp()}.png"
        image.save(path)
        return JarvisResponse(text=f"{text}\n{path}", image_path=path)

    @command("hiit", "tabata", group=HEALTH, usage="/hiit", help="a workout interval timer: Tabata, HIIT, EMOM",
             title="Workout timer", icon="⏱", page="health")
    def hiit_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="⏱ The interval timer is on the Health page.", open_page="health:timer")

    @command("breathe", "breathing", group=HEALTH, usage="/breathe", help="guided breathing: box, 4-7-8, calm",
             title="Breathing exercises", icon="🌬", page="health")
    def breathe_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="🌬 Breathing exercises are on the Health page.", open_page="health:breathe")

    @command("uv", group=HEALTH, usage="/uv [city] · /uv alert on|off", help="today's UV index and what it means",
             title="UV index", icon="🕶", page="health", fields=(field("city", "text", "City", optional=True),))
    def uv_cmd(self, args: str, routed: bool = False):
        from .. import weather

        text = args.strip()
        if text.lower().startswith("alert"):
            settings = daily.HEALTH.load()
            settings["uv_alert"] = "off" not in text.lower()
            daily.HEALTH.save(settings)
            return "🕶 Morning UV alerts " + ("on." if settings["uv_alert"] else "off.")
        city = text or weather.home_city()
        if not city:
            return "Which city? /uv Antalya (or set your city in Settings)."
        try:
            day = daily.day_forecast(city)
        except weather.WeatherError as exc:
            return str(exc)
        uv = day["uv"]
        advice = ("No protection needed." if uv < 3 else "Sunglasses; sunscreen if you're out for long." if uv < 6
                  else "Sunscreen SPF 30+, a hat, and shade around noon." if uv < 8
                  else "Avoid the midday sun; SPF 50, hat and sunglasses.")
        return f"🕶 {day['place']}: UV {uv:.0f} today ({daily.uv_words(uv)}), {day['uv_tomorrow']:.0f} tomorrow. {advice}"

    # --- money ------------------------------------------------------------------------------------
    @command("budget", "budgets", group=HEALTH, usage="/budget · /budget <category> <amount> · /budget <category> off",
             help="a monthly budget for each spending category, with alerts at 80% and 100%",
             title="Monthly budget by category", icon="💰", page="money",
             fields=(field("category", "choice", "Category", "food", tuple(spending.CATEGORIES) + ("other",)),
                     field("amount", "number", "Monthly budget")), template="{category} {amount}")
    def budget_cmd(self, args: str, routed: bool = False):
        parts = args.strip().split()
        if len(parts) >= 2:
            category, value = parts[0].lower(), parts[1].lower()
            if value in {"off", "0", "none"}:
                money.set_budget(category, 0)
                return f"💰 No budget for {category}."
            try:
                money.set_budget(category, spending._number(re.sub(r"[^\d.,]", "", value)))
            except ValueError:
                return "Usage: /budget food 3000"
        rows = money.budget_status()
        if not rows:
            return "💰 No category budgets yet. /budget food 3000 · /budget fun 1000"
        lines = ["💰 This month:"]
        for r in rows:
            bar = "█" * min(10, int(r["share"] * 10)) + "░" * max(0, 10 - int(r["share"] * 10))
            lines.append(f"  {r['category']:<10} {bar} {_money(r['spent'])} of {_money(r['budget'])}"
                         + (" ⚠" if r["share"] >= 1 else ""))
        return "\n".join(lines)

    @command("importcsv", "bankcsv", group=HEALTH, usage="/importcsv <bank statement .csv>",
             help="adds a bank or card statement's spending to your log (no duplicates)",
             title="Bank statement import", icon="🏦", page="money",
             fields=(field("file", "file", "Statement (CSV)", types=(("CSV", "*.csv *.txt"),)),))
    def importcsv_cmd(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        if path is None:
            return "Usage: /importcsv C:/Downloads/hesap-hareketleri.csv (your bank's CSV export)"
        try:
            added, skipped = money.import_statement(path)
        except (ValueError, OSError) as exc:
            return f"🏦 {exc}"
        return (f"🏦 Added {added} spending entr{'y' if added == 1 else 'ies'} from {path.name}"
                + (f" ({skipped} already there)" if skipped else "") + ". /spent shows the month.")

    @command("owe", "owes", group=HEALTH, usage="/owe <who> paid <amount> for <names> [| what] · /owe · "
                                                  "/owe settle · /owe clear",
             help="who owes who in a group: shared costs, and the fewest payments to square up",
             title="Who owes who", icon="🤝", page="money",
             fields=(field("payer", "text", "Who paid"), field("amount", "number", "How much"),
                     field("people", "text", "For whom (comma-separated, payer too if they share)"),
                     field("what", "text", "What for", optional=True)),
             template="{payer} paid {amount} for {people} | {what}")
    def owe_cmd(self, args: str, routed: bool = False):
        text, what = split(args, 2)
        low = text.strip().lower()
        if low == "clear":
            money.OWES.save([])
            return "🤝 Cleared — everyone's square."
        m = re.match(r"(.+?)\s+(?:paid|ödedi|odedi)\s+([\d.,]+)\s*(?:tl|₺|try)?\s+(?:for|için|icin)\s+(.+)", text.strip(),
                     re.I)
        if m:
            people = [p for p in re.split(r",|\band\b|\bve\b", m.group(3)) if p.strip()]
            entry = money.owe_add(m.group(1), spending._number(m.group(2)), people, what)
            share = entry["amount"] / max(1, len(entry["for"]))
            return (f"🤝 {entry['payer']} paid {_money(entry['amount'])} for {', '.join(entry['for'])} — "
                    f"{_money(share)} each.\n" + self.owe_cmd("settle"))
        net = money.balances()
        if not net:
            return "🤝 Nothing owed. /owe Ali paid 600 for Ali, Ayşe, Mehmet | dinner"
        lines = ["🤝 To square up:"] + [f"  {a} pays {b} {_money(v)}" for a, b, v in money.settle(net)]
        return "\n".join(lines)

    @command("nospend", group=HEALTH, usage="/nospend start [days] [| allowed: bills, groceries] · /nospend · "
                                            "/nospend stop",
             help="a no-spend challenge, checked against your spending log", title="No-spend challenge",
             icon="🚫", page="money", fields=(field("days", "number", "Days", "7"),
                                             field("allowed", "text", "Allowed categories", "bills, groceries")),
             template="start {days} | {allowed}")
    def nospend_cmd(self, args: str, routed: bool = False):
        text, allowed = split(args, 2)
        low = text.strip().lower()
        if low.startswith("start"):
            m = re.search(r"\d+", low)
            state = money.nospend_start(int(m.group(0)) if m else 7,
                                        (allowed or "bills, groceries").split(","))
            return (f"🚫 No-spend challenge: {state['days']} days from today. Allowed: "
                    f"{', '.join(state['allowed']) or 'nothing'}. Keep logging with /spent — I'll check it.")
        if low == "stop":
            money.NOSPEND.save({})
            return "🚫 Challenge stopped."
        status = money.nospend_status()
        if status is None:
            return "🚫 No challenge running. /nospend start 7 | bills, groceries"
        lines = [f"🚫 Day {status['elapsed']} of {status['days']}: {status['clean']} clean day(s)."]
        for day, things in sorted(status["slips"].items()):
            lines.append(f"  {day}: {', '.join(things[:3])}")
        if status["finished"]:
            lines.append("Finished! " + ("A perfect run 🎉" if not status["slips"] else "Try again any time."))
        return "\n".join(lines)

    # --- Türkiye ----------------------------------------------------------------------------------
    @command("kdv", group=TR, usage="/kdv <tutar> [oran] [dahil]", help="KDV ekle ya da KDV dahil fiyattan ayır",
             title="KDV hesaplama", icon="🧮", page="turkey",
             fields=(field("amount", "number", "Tutar"), field("rate", "choice", "Oran (%)", "20", ("20", "10", "1")),
                     field("mode", "choice", "Fiyat", "hariç", ("hariç", "dahil"))),
             template="{amount} {rate} {mode}")
    def kdv_cmd(self, args: str, routed: bool = False):
        text = args.strip().lower()
        numbers = re.findall(r"\d+(?:[.,]\d+)*", text)
        if not numbers:
            return "Kullanım: /kdv 1000 · /kdv 1200 20 dahil"
        amount = spending._number(numbers[0])
        rate = float(numbers[1].replace(",", ".")) if len(numbers) > 1 else 20.0
        included = "dahil" in text or "incl" in text
        r = turkey.kdv(amount, rate, included)
        return (f"🧮 %{rate:g} KDV {'dahil fiyattan' if included else 'ekleyince'}:\n"
                f"  KDV hariç: {turkey.tl(r['net'])}\n  KDV:       {turkey.tl(r['kdv'])}\n"
                f"  KDV dahil: {turkey.tl(r['gross'])}")

    @command("traffic", "trafik", group=TR, usage="/traffic", help="Istanbul's traffic index right now (İBB)",
             title="Istanbul traffic index", icon="🚦", page="turkey")
    def traffic_cmd(self, args: str, routed: bool = False):
        try:
            now = turkey.traffic_now()
        except kit.KitError as exc:
            return f"🚦 İBB's traffic centre didn't answer: {exc}"
        compare = ""
        if now["usual"]:
            diff = now["now"] - now["usual"]
            compare = (f", about usual for this time" if abs(diff) < 5 else
                       f", {abs(diff)} points {'worse' if diff > 0 else 'better'} than usual")
        return (f"🚦 Istanbul traffic index: {now['now']}% — {turkey.traffic_words(now['now'])}{compare}.\n"
                "Live map: https://uym.ibb.gov.tr/")

    @command("tarif", group=TR, usage="/tarif <yemek> [| kişi sayısı]",
             help="Türk mutfağından tarif: su bardağı ölçüleriyle, adım adım", title="Türk mutfağı tarifleri",
             icon="🍲", page="turkey", fields=(field("dish", "text", "Yemek", hint="Karnıyarık"),
                                              field("people", "number", "Kişi", "4")))
    def tarif_cmd(self, args: str, routed: bool = False):
        dish, people = split(args, 2)
        if not dish.strip():
            return "Kullanım: /tarif mercimek çorbası | 4"
        with kit.more_room(self.brain, 2500):
            return "🍲 " + self.brain.ask_once(
                f"Türk ev mutfağından '{dish.strip()}' tarifi, {people.strip() or '4'} kişilik. Türkçe yaz. "
                "Malzemeleri su bardağı, yemek kaşığı, çay kaşığı ve gram ile ver; sonra numaralı adımlar; "
                "pişirme süresi ve fırın derecesi gerekiyorsa belirt; sonunda kısa bir püf noktası.").strip()

    @command("bayram", group=TR, usage="/bayram", help="yaklaşan bayramlar ve resmî tatiller",
             title="Milli bayram hatırlatmaları", icon="🎊", page="turkey")
    def bayram_cmd(self, args: str, routed: bool = False):
        try:
            items = turkey.upcoming()
        except kit.KitError as exc:
            return f"Tatil takvimine ulaşılamadı: {exc}"
        lines = ["🇹🇷 Yaklaşan bayram ve tatiller:"]
        for item in items:
            when = f"{item['first']:%d.%m.%Y}" + (f" – {item['last']:%d.%m}" if item["days"] > 1 else "")
            soon = "bugün" if item["in_days"] == 0 else "yarın" if item["in_days"] == 1 else f"{item['in_days']} gün sonra"
            lines.append(f"  {item['base']} — {when}" + (f" ({item['days']} gün)" if item["days"] > 1 else "")
                         + f" · {soon}")
        lines.append("Bir gün önce hatırlatırım (JARVIS açıkken).")
        return "\n".join(lines)

    @command("edevlet", group=TR, usage="/edevlet [aradığın hizmet]", help="e-Devlet ve resmî sitelere kısayollar",
             title="e-Devlet quick links", icon="🏛", page="turkey",
             fields=(field("service", "text", "Hizmet", optional=True, hint="hizmet dökümü"),))
    def edevlet_cmd(self, args: str, routed: bool = False):
        query = args.strip()
        if query:
            words = query.lower()
            hits = [(name, url) for name, url, _ in turkey.EDEVLET if all(w in name.lower() for w in words.split())]
            if hits:
                return "\n".join(f"🏛 {name}: {url}" for name, url in hits)
            return f"🏛 e-Devlet'te ara: {turkey.edevlet_search(query)}"
        return "🏛 e-Devlet kısayolları:\n" + "\n".join(f"  {icon} {name}: {url}" for name, url, icon in turkey.EDEVLET)


# --- background checks ------------------------------------------------------------------------------

def _once(key: str) -> bool:
    """True the first time a reminder key is seen (so each nudge comes once)."""
    seen = REMINDED.load()
    if key in seen:
        return False
    seen[key] = time.time()
    REMINDED.save({k: v for k, v in seen.items() if time.time() - v < 90 * 86400})
    return True


def register_watchers(jarvis, watchers) -> None:
    def warranties():
        for row in daily.warranties():
            if not 0 <= row["days_left"] <= 30:
                continue
            # One nudge a month before and one a week before — only the nearest that applies.
            window = 7 if row["days_left"] <= 7 else 30
            if _once(f"warranty:{row['item']}:{row['until']}:{window}"):
                alerts.post(f"🧾 {row['item']}: warranty ends in {row['days_left']} day(s)",
                            row.get("note") or "Anything to claim before it runs out?", page="everyday", kind="warn")

    def water():
        settings = daily.HEALTH.load()
        if settings.get("water_reminders") and daily.water_behind():
            stamp = datetime.now().strftime("%Y-%m-%d-%H")
            if int(stamp[-2:]) % 2 == 0 and _once(f"water:{stamp}"):
                alerts.post("💧 Time for some water", f"{daily.water_today()} of {settings.get('water_goal', 2000)} "
                                                     "ml so far today.", page="health")

    def uv():
        from .. import weather

        now = datetime.now()
        if not (8 <= now.hour <= 11) or not daily.HEALTH.load().get("uv_alert", True) or not weather.home_city():
            return
        if not _once(f"uv-check:{now.date()}"):
            return
        try:
            day = daily.day_forecast(weather.home_city())
        except Exception:
            return
        if day["uv"] >= 6:
            alerts.post(f"🕶 Strong sun today: UV {day['uv']:.0f} ({daily.uv_words(day['uv'])})",
                        "Sunscreen and a hat if you're out around noon.", page="health", kind="warn")

    def bayram():
        try:
            items = turkey.upcoming(count=3)
        except Exception:
            return
        for item in items:
            if item["in_days"] == 1 and _once(f"bayram:{item['first']}"):
                alerts.post(f"🇹🇷 Yarın {item['base']}", "İyi bayramlar!" if "Bayram" in item["base"] else
                            "Resmî tatil.", page="turkey")

    watchers.add("warranties", 6 * 3600, warranties, first_after=90)
    watchers.add("water", 15 * 60, water, first_after=300)
    watchers.add("uv", 30 * 60, uv, first_after=180)
    watchers.add("bayram", 6 * 3600, bayram, first_after=150)
