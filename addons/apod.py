"""NASA's Astronomy Picture of the Day, explained.

    /apod             today's picture, saved and shown, with NASA's explanation
    /apod 2026-01-15  the picture from that day

NASA's public API with its shared demo key (a free NASA_API_KEY from
api.nasa.gov lifts the demo limit).
"""

from __future__ import annotations

import os
import re
import urllib.request

from jarvis import kit, net
from jarvis.addons import Addon, Command

API = "https://api.nasa.gov/planetary/apod"


class Apod(Addon):
    name = "apod"
    version = "1.0"
    description = "NASA's Astronomy Picture of the Day."

    def commands(self):
        return [Command("apod", self.apod, "NASA's astronomy picture of the day", "/apod [YYYY-MM-DD]")]

    def apod(self, ctx, args: str):
        params = {"api_key": os.getenv("NASA_API_KEY", "").strip() or "DEMO_KEY"}
        day = args.strip()
        if day:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                return "Usage: /apod or /apod 2026-01-15"
            params["date"] = day
        try:
            data = kit.get_json(API, params, timeout=20)
        except kit.KitError as exc:
            return f"{exc} (NASA's demo key allows a few calls an hour; a free NASA_API_KEY lifts that.)"
        title, text = data.get("title", "Astronomy picture"), data.get("explanation", "")
        url = data.get("hdurl") or data.get("url", "")
        header = f"🔭 {title} — {data.get('date', '')}\n\n{text}"
        if data.get("media_type") != "image" or not url:
            return f"{header}\n\nToday it's a video: {data.get('url', '')}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": net.DEFAULT_USER_AGENT})
            with net.urlopen(request, timeout=40) as response:
                image = response.read(25_000_000)
            path = kit.output_dir("images") / f"apod_{data.get('date', kit.stamp())}{os.path.splitext(url)[1] or '.jpg'}"
            path.write_bytes(image)
        except Exception:
            return f"{header}\n\n{url}"
        from jarvis.assistant import JarvisResponse

        if ctx.jarvis is not None:
            ctx.jarvis.current_image = path
        return JarvisResponse(text=f"{header}\n\nSaved: {path}", image_path=path, image_paths=[path])


ADDON = Apod()
