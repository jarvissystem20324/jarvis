"""How fast is my internet — ping, download and upload, via Cloudflare.

speed.cloudflare.com serves exactly-sized downloads and accepts uploads for
this purpose, needs no key, and has servers close to almost everyone. Nothing
about you is sent: the upload is zeros. The whole test takes about ten
seconds and moves roughly 40 MB.
"""

from __future__ import annotations

import http.client
import statistics
import time
import urllib.request

from . import net

BASE = "https://speed.cloudflare.com"
DOWN_BYTES = (1_000_000, 10_000_000, 25_000_000)
UP_BYTES = (1_000_000, 5_000_000)
PINGS = 8


class SpeedError(Exception):
    pass


def _request(url: str, data: bytes | None = None) -> urllib.request.Request:
    headers = {"User-Agent": net.DEFAULT_USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    return urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")


def _ping() -> tuple[float, float]:
    """(median ms, jitter ms) over tiny requests on one kept-alive connection.

    A fresh connection per request would time the TCP and TLS handshakes
    too, which roughly triples the figure; the first request (which does the
    handshake) is thrown away.
    """
    connection = http.client.HTTPSConnection(BASE.split("//")[1], timeout=10, context=net.ssl_context())
    times = []
    try:
        for _ in range(PINGS + 1):
            start = time.perf_counter()
            connection.request("GET", "/__down?bytes=0", headers={"User-Agent": net.DEFAULT_USER_AGENT})
            connection.getresponse().read()
            times.append((time.perf_counter() - start) * 1000)
    finally:
        connection.close()
    times = times[1:]
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return statistics.median(times), jitter


def _download(size: int) -> float:
    start = time.perf_counter()
    got = 0
    with net.urlopen(_request(f"{BASE}/__down?bytes={size}"), timeout=60) as response:
        while chunk := response.read(262144):
            got += len(chunk)
    return got * 8 / max(time.perf_counter() - start, 1e-6) / 1e6


def _upload(size: int) -> float:
    payload = bytes(size)
    start = time.perf_counter()
    with net.urlopen(_request(f"{BASE}/__up", payload), timeout=60) as response:
        response.read()
    return size * 8 / max(time.perf_counter() - start, 1e-6) / 1e6


def _where() -> str:
    """The Cloudflare server used, by airport code (IST, FRA…). The trace also
    lists your IP address; that is read past, never shown or kept."""
    try:
        with net.urlopen(_request(f"{BASE}/cdn-cgi/trace"), timeout=10) as response:
            trace = dict(line.split("=", 1) for line in response.read().decode("utf-8").splitlines() if "=" in line)
        return f"server {trace['colo']}" if trace.get("colo") else ""
    except Exception:
        return ""


def run() -> dict:
    """Measure. Speeds in Mbps, the best of each size (the first warms up)."""
    try:
        ping, jitter = _ping()
        down = max(_download(size) for size in DOWN_BYTES)
        up = max(_upload(size) for size in UP_BYTES)
    except OSError as exc:
        raise SpeedError(f"The speed test could not reach Cloudflare: {exc}") from exc
    return {"down": down, "up": up, "ping": ping, "jitter": jitter, "where": _where(), "at": time.time()}


def verdict(down: float) -> str:
    if down >= 100:
        return "fast: 4K streaming and big downloads are fine"
    if down >= 25:
        return "good: HD video calls and streaming are fine"
    if down >= 8:
        return "OK for browsing and HD video, slow for big downloads"
    return "slow: video calls may stutter"


def describe(result: dict) -> str:
    lines = [
        f"⬇ {result['down']:.1f} Mbps   ⬆ {result['up']:.1f} Mbps   "
        f"ping {result['ping']:.0f} ms (jitter {result['jitter']:.0f} ms)",
        f"That's {verdict(result['down'])}.",
    ]
    if result.get("where"):
        lines.append(f"via Cloudflare: {result['where']}")
    return "\n".join(lines)
