"""Hacker News: the top stories in tech right now, with a short AI digest.

    /hn          the top 10 stories
    /hn digest   the same, summarised into what matters this morning

Uses the public Hacker News API (no account, no key).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from jarvis import kit
from jarvis.addons import Addon, Command

API = "https://hacker-news.firebaseio.com/v0"


class HackerNews(Addon):
    name = "hackernews"
    version = "1.0"
    description = "Top Hacker News stories, with an optional AI digest."

    def commands(self):
        return [Command("hn", self.hn, "Top Hacker News stories", "/hn [digest]")]

    def stories(self, count: int = 10) -> list[dict]:
        ids = kit.get_json(f"{API}/topstories.json")[:count]
        with ThreadPoolExecutor(max_workers=8) as pool:
            items = list(pool.map(lambda i: kit.get_json(f"{API}/item/{i}.json"), ids))
        return [i for i in items if isinstance(i, dict) and i.get("title")]

    def hn(self, ctx, args: str) -> str:
        try:
            stories = self.stories()
        except kit.KitError as exc:
            return str(exc)
        lines = [f"  {n}. {s['title']}  ({s.get('score', 0)} points)\n     "
                 f"{s.get('url') or 'https://news.ycombinator.com/item?id=' + str(s['id'])}"
                 for n, s in enumerate(stories, 1)]
        text = "🟧 Hacker News — top stories\n" + "\n".join(lines)
        if args.strip().lower() == "digest":
            digest = ctx.ask("In 4 short bullet points, what do these tech headlines say is happening today? "
                             "Plain language.\n\n" + "\n".join(s["title"] for s in stories))
            text = f"{digest.strip()}\n\n{text}"
        return text


ADDON = HackerNews()
