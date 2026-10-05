"""10.0 travel and maps: the map, what's nearby, saved places, trip budgets,
itineraries into the calendar, a documents checklist and a jet lag plan.
The logic is in jarvis/travel.py."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from .. import kit, travel
from ..registry import command, field, split

G = "Travel"


class Travel10:
    @command("map", group=G, usage="/map [place]", help="opens the map at a place", title="Map", icon="🗺",
             page="map", fields=(field("place", "text", "Place", optional=True, hint="Galata Kulesi"),))
    def map_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        place = args.strip()
        return JarvisResponse(text=f"🗺 Opening the map{' at ' + place if place else ''}.",
                              open_page="map" + (f":{place}" if place else ""))

    @command("nearby", group=G, usage="/nearby <pharmacy|cafe|atm|fuel|…> [near <place>]",
             help="the nearest pharmacies, cafés, ATMs and more, with distances", title="Nearby places", icon="📍",
             page="map", fields=(field("what", "choice", "What", "pharmacy", tuple(travel.NEARBY)),
                                 field("near", "text", "Near (blank: home)", optional=True)),
             template="{what} near {near}")
    def nearby_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        m = re.search(r"\s+(?:near|in|at|yakınında|yakını)\s+(.+)$", text, re.I)
        what, near = (text[:m.start()], m.group(1)) if m else (text, "")
        kind = travel.nearby_kind(what)
        if kind is None:
            return "📍 Nearby what? " + ", ".join(travel.NEARBY) + " — e.g. /nearby pharmacy near Kadıköy"
        try:
            if near.strip():
                found = travel.search(near.strip(), limit=1)
                if not found:
                    return f"📍 I can't find {near.strip()!r}."
                where = (found[0]["name"], found[0]["lat"], found[0]["lon"])
            else:
                where = travel.where_am_i()
                if where is None:
                    return "📍 Near where? /nearby pharmacy near Beşiktaş — or save a place called Home."
            rows = travel.nearby(where[1], where[2], kind)
        except travel.TravelError as exc:
            return f"📍 {exc}"
        if not rows:
            return f"📍 No {travel.NEARBY[kind][1]} found within about a kilometre of {where[0]}."
        lines = [f"📍 {travel.NEARBY[kind][2]} Nearest {travel.PLURAL[kind]} to {where[0]}:"]
        for r in rows[:8]:
            extra = " · ".join(x for x in (r["address"], r["hours"]) if x)
            lines.append(f"  {travel.show_distance(r['distance']):>7}  {r['name']}" + (f" — {extra}" if extra else ""))
        lines.append("The Map page shows them. Map data © OpenStreetMap contributors.")
        return "\n".join(lines)

    @command("places", "place", group=G, usage="/places · /places add <name> | <address or place> [| note] · "
                                               "/places remove <name>",
             help="places you want to keep: home, work, that café", title="Saved places", icon="⭐", page="map",
             fields=(field("name", "text", "Name", hint="Home"), field("where", "text", "Address or place"),
                     field("note", "text", "Note", optional=True)), template="add {name} | {where} | {note}")
    def places_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        if verb.lower() in {"add", "save", "ekle"}:
            name, where, note = split(rest, 3)
            if not name.strip() or not where.strip():
                return "Usage: /places add Home | Moda Caddesi 12, Kadıköy"
            m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", where)
            try:
                if m:
                    lat, lon = float(m.group(1)), float(m.group(2))
                else:
                    found = travel.search(where.strip(), limit=1)
                    if not found:
                        return f"⭐ I can't find {where.strip()!r} on the map."
                    lat, lon = found[0]["lat"], found[0]["lon"]
            except travel.TravelError as exc:
                return f"⭐ {exc}"
            travel.save_place(name, lat, lon, note)
            return f"⭐ Saved {name.strip()} ({lat:.5f}, {lon:.5f})."
        if verb.lower() in {"remove", "delete", "sil"} and rest.strip():
            rows = travel.PLACES.load()
            gone = [r for r in rows if r["name"].lower() == rest.strip().lower()]
            if not gone:
                return f"⭐ No saved place called {rest.strip()}."
            travel.PLACES.save([r for r in rows if r not in gone])
            return f"⭐ Removed {gone[0]['name']}."
        rows = travel.PLACES.load()
        if not rows:
            return "⭐ No saved places. /places add Home | <your address>"
        return "⭐ Saved places:\n" + "\n".join(f"  {r['name']} — {r['lat']:.4f}, {r['lon']:.4f}" +
                                               (f" · {r['note']}" if r.get("note") else "") for r in rows)

    @command("tripbudget", group=G, usage="/tripbudget <destination> | <days> | <people> | [budget|mid|comfort]",
             help="what a trip is likely to cost, by category, in lira too (an estimate)", title="Trip budget",
             icon="💶", page="travel",
             fields=(field("where", "text", "Destination", hint="Rome"), field("days", "number", "Days", "5"),
                     field("people", "number", "People", "2"),
                     field("style", "choice", "Style", "mid", ("budget", "mid", "comfort"))))
    def tripbudget_cmd(self, args: str, routed: bool = False):
        from .. import calc

        where, days, people, style = split(args, 4)
        if not where.strip():
            return "Usage: /tripbudget Rome | 5 | 2 | mid"
        days_n, people_n = kit.whole(days, 5, 1, 365), kit.whole(people, 2, 1, 500)
        try:
            data = kit.ask_json(self.brain, (
                f"Estimate a {style.strip() or 'mid'}-range trip to {where.strip()} for {people_n} people, {days_n} "
                "days, not counting flights. JSON: {\"currency\": \"local ISO code\", \"per_day_per_person\": "
                "{\"stay\": n, \"food\": n, \"transport\": n, \"activities\": n, \"other\": n}, \"tips\": [\"…\"]}. "
                "Stay is per person (sharing a room). Typical recent prices; round numbers."), room=1500)
            costs = {k: float(v) for k, v in (data.get("per_day_per_person") or {}).items()}
            currency = str(data.get("currency") or "EUR").upper()[:3]
        except Exception:
            return "💶 I couldn't put an estimate together. Try again."
        if not costs:
            return "💶 I couldn't put an estimate together."
        total = sum(costs.values()) * days_n * people_n
        lines = [f"💶 {where.strip()}, {days_n} days, {people_n} people ({style.strip() or 'mid'}) — an estimate:"]
        for name, per_day in costs.items():
            lines.append(f"  {name:<11} {per_day:>8,.0f} {currency} a day each → {per_day * days_n * people_n:>10,.0f}")
        lines.append(f"  {'Total':<11} {'':>8}                 {total:>10,.0f} {currency}")
        if currency != "TRY":
            try:
                lira, source = calc.convert_currency(total, currency, "TRY")
                lines.append(f"  ≈ {lira:,.0f} TRY ({source})")
            except Exception:
                pass
        tips = data.get("tips") or []
        lines += [f"  • {t}" for t in tips[:4]]
        lines.append("Flights aren't included; prices are typical, not quotes.")
        return "\n".join(lines)

    @command("itinerary", group=G, usage="/itinerary <the trip> [| first day] [| add]",
             help="a day-by-day plan, saved as a calendar file and (if you ask) added to your calendar",
             title="Itinerary to calendar", icon="🗓", page="travel",
             fields=(field("trip", "long", "The trip", hint="3 days in Kapadokya, balloons, hiking, good food"),
                     field("start", "date", "First day"), field("add", "bool", "Add to my calendar", "")),
             template="{trip} | {start} | {add}")
    def itinerary_cmd(self, args: str, routed: bool = False):
        from .. import life
        from ..daily import parse_date

        trip, start, add = split(args, 3)
        if not trip.strip():
            return "Usage: /itinerary 3 days in Rome, art and food | 14.11.2026 | add"
        try:
            first = parse_date(start) if start.strip() else (datetime.now() + timedelta(days=7)).date()
        except ValueError as exc:
            return str(exc)
        try:
            data = kit.ask_json(self.brain, (
                f"Plan this trip day by day: {trip.strip()}. JSON: {{\"title\": \"…\", \"days\": [{{\"day\": 1, "
                "\"items\": [{\"time\": \"09:00\", \"minutes\": 90, \"title\": \"…\", \"where\": \"…\"}]}]}. "
                "Realistic travel times between places, a lunch and dinner each day, 4-6 items a day. Use the "
                "trip's language for titles."), room=4000)
        except Exception:
            return "🗓 I couldn't plan that. Try describing the trip a little more."
        events, lines = [], [f"🗓 {data.get('title') or trip.strip()[:60]}"]
        for day in data.get("days") or []:
            date_ = first + timedelta(days=int(day.get("day", 1)) - 1)
            lines.append(f"  {date_:%a %d %b}")
            for item in day.get("items") or []:
                try:
                    hour, minute = (int(x) for x in str(item.get("time", "09:00")).split(":")[:2])
                except ValueError:
                    hour, minute = 9, 0
                begin = datetime.combine(date_, datetime.min.time()).replace(hour=hour % 24, minute=minute % 60)
                length = int(item.get("minutes") or 60) * 60
                events.append({"title": item.get("title", "Plan"), "start": begin.timestamp(),
                               "end": begin.timestamp() + length, "where": item.get("where", ""),
                               "uid": f"trip{int(begin.timestamp())}{len(events)}"})
                lines.append(f"    {begin:%H:%M}  {item.get('title', '')}" + (f" — {item['where']}" if item.get("where")
                                                                              else ""))
        if not events:
            return "🗓 That came back empty — try again."
        path = kit.output_dir("documents") / f"itinerary_{kit.slug(data.get('title') or 'trip')}_{kit.stamp()}.ics"
        path.write_text(life.ics(events), encoding="utf-8")
        if add.strip().lower() in {"add", "on", "yes", "true", "ekle"}:
            calendar = life.CALENDAR.load()
            calendar += events
            life.CALENDAR.save(calendar)
            lines.append(f"Added {len(events)} event(s) to your calendar (/cal).")
        lines.append(f"Calendar file for Google or Outlook: {path}")
        return "\n".join(lines)

    @command("traveldocs", group=G, usage="/traveldocs [trip] · /traveldocs <trip> | done <n>",
             help="a checklist of documents and essentials for a trip, ticked off as you go",
             title="Travel documents checklist", icon="🛂", page="travel",
             fields=(field("trip", "text", "Trip", "My trip"),))
    def traveldocs_cmd(self, args: str, routed: bool = False):
        trip, action = split(args, 2)
        trip = trip.strip() or "My trip"
        state = travel.TRAVEL_DOCS.load()
        items = [item for group in travel.DOCS.values() for item in group]
        m = re.search(r"done\s+(\d+)", action)
        if m and 0 < int(m.group(1)) <= len(items):
            state[trip] = sorted(set(state.get(trip, [])) | {int(m.group(1)) - 1})
            travel.TRAVEL_DOCS.save(state)
        done = set(state.get(trip, []))
        lines = [f"🛂 {trip} — {len(done)}/{len(items)} ready:"]
        n = 0
        for group, things in travel.DOCS.items():
            lines.append(f"  {group}")
            for thing in things:
                lines.append(f"    {'☑' if n in done else '☐'} {n + 1}. {thing}")
                n += 1
        lines.append(f"Tick one: /traveldocs {trip} | done 3. Visa rules change — check the official site.")
        return "\n".join(lines)

    @command("jetlag", group=G, usage="/jetlag <from city> | <to city> | <departure date and time>",
             help="a plan to beat jet lag: shifting sleep before, light and naps after", title="Jet lag planner",
             icon="🌍", page="travel", fields=(field("origin", "text", "From", "Istanbul"),
                                              field("dest", "text", "To", hint="Tokyo"),
                                              field("when", "text", "Leaving", hint="14.11.2026 21:30")))
    def jetlag_cmd(self, args: str, routed: bool = False):
        from .. import clock
        from ..daily import parse_date

        origin, dest, when = split(args, 3)
        if not origin.strip() or not dest.strip():
            return "Usage: /jetlag Istanbul | Tokyo | 14.11.2026 21:30"
        try:
            o_name, o_zone = clock.zone_for(origin)
            d_name, d_zone = clock.zone_for(dest)
            m = re.search(r"(\d{1,2}):(\d{2})", when)
            day = parse_date(when[:m.start()].strip() if m else when.strip() or "today")
            depart = datetime.combine(day, datetime.min.time()).replace(hour=int(m.group(1)) if m else 12,
                                                                        minute=int(m.group(2)) if m else 0)
        except (clock.ClockError, ValueError) as exc:
            return str(exc)
        plan = travel.jetlag_plan(o_zone, d_zone, depart)
        hours = plan["hours"]
        if abs(hours) < 2:
            return f"🌍 {o_name} → {d_name}: {abs(hours):g} h difference — little or no jet lag to plan for."
        lines = [f"🌍 {o_name} → {d_name}: {abs(hours):g} h {'ahead (flying east)' if plan['east'] else 'behind (flying west)'}"
                 f" — about {plan['days']} day(s) to adjust fully."]
        if plan["before"]:
            lines.append("  Before you go:")
            lines += [f"    {step}" for step in plan["before"]]
        lines.append("  When you land:")
        lines += [f"    {step}" for step in plan["arrival"]]
        lines.append("(General advice. Ask a doctor before taking anything to sleep.)")
        return "\n".join(lines)
