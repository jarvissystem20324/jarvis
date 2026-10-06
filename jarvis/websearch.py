"""Web search and page reading.

`/search` used to open your browser, which is not the same thing as JARVIS
knowing something. This actually fetches results and pages, strips them to
readable text, and hands that to the model — with the URLs shown, so you can
check where an answer came from rather than taking its word for it.

DuckDuckGo's HTML endpoint is used because it needs no key and no account,
which matches the rest of this project. It is scraping, so it will break one
day; when it does, the failure says so plainly instead of silently returning
nothing.

With FIRECRAWL_API_KEY set (10.0.2), searches go to Firecrawl first: a real
API, so no anti-bot page and no layout to break. DuckDuckGo stays as the
backup for when Firecrawl is down, out of credit or the key is wrong. A page
too bare to read directly (one drawn by JavaScript, or one that turns away
scripts) is read through Firecrawl as well.

Nothing here executes what it downloads. Pages are stripped to text, scripts
and styles are removed outright, and the result is treated as untrusted text
that happens to be about a topic — a page telling JARVIS to ignore its
instructions is just words on a page.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
from dataclasses import dataclass

from . import net

SEARCH_URL = "https://html.duckduckgo.com/html/"
MAX_PAGE_BYTES = 800_000
MAX_TEXT_CHARS = 12_000
TIMEOUT = 25

FIRECRAWL_URL = "https://api.firecrawl.dev/v2"
FIRECRAWL_ENV = "FIRECRAWL_API_KEY"
FIRECRAWL_TIMEOUT = 20
# After a failure Firecrawl is left alone this long, so a wrong key or an
# outage does not add a wasted request to every search.
FIRECRAWL_REST = 300
# A page with less readable text than this was most likely drawn by
# JavaScript, or turned the download away.
THIN_PAGE = 400
_firecrawl_off_until = 0.0
_FIRECRAWL_HTTP = {
    401: "Firecrawl refused the key (FIRECRAWL_API_KEY).",
    402: "Firecrawl is out of credits.",
    429: "Firecrawl is rate limiting this key.",
}

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n\s*\n\s*\n+")
_RESULT = re.compile(
    r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
)
_SNIPPET = re.compile(r'(?is)<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<text>.*?)</a>')
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)?")
# Wikipedia's footnote markers, "[[9]](…#cite_note-9)".
_MD_CITE = re.compile(r"\[\[?\d+\]?\]\([^)]*\)?")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)?")
_MD_MARKS = re.compile(r"\*\*|__|`|^#+\s*", re.M)


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""

    def line(self) -> str:
        return f"{self.title}\n  {self.url}" + (f"\n  {self.snippet}" if self.snippet else "")


class SearchError(Exception):
    """Something the user should read, not a traceback."""


def _clean(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def _real_url(href: str) -> str:
    """DuckDuckGo wraps results in a redirect; unwrap it."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def _plain(text: str) -> str:
    """Firecrawl's titles and descriptions are markdown; callers want text."""
    text = _MD_IMAGE.sub("", text)
    text = _MD_CITE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_MARKS.sub("", text)
    return " ".join(text.split())


# --- Firecrawl -----------------------------------------------------------------

def firecrawl_key() -> str:
    from .config import get_setting

    return get_setting(FIRECRAWL_ENV, "")


def engine() -> str:
    """The engine a search tries first, for the words around one."""
    return "Firecrawl" if firecrawl_key() else "DuckDuckGo"


def _firecrawl_ready() -> bool:
    return bool(firecrawl_key()) and time.time() >= _firecrawl_off_until


def _rest_firecrawl() -> None:
    global _firecrawl_off_until
    _firecrawl_off_until = time.time() + FIRECRAWL_REST


def reset() -> None:
    """Try Firecrawl again straight away (a new key was just saved)."""
    global _firecrawl_off_until
    _firecrawl_off_until = 0.0


def _firecrawl(path: str, body: dict | None = None, key: str = "") -> dict:
    """One Firecrawl API call; a SearchError with a readable reason if it fails.

    A refused key, no credit or no answer rests Firecrawl for a while; a
    key being tried out in Settings (`key`) never does.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{FIRECRAWL_URL}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {key or firecrawl_key()}",
            "Content-Type": "application/json",
            "User-Agent": net.DEFAULT_USER_AGENT,
        },
    )
    try:
        with net.urlopen(request, timeout=FIRECRAWL_TIMEOUT) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if not key:
            _rest_firecrawl()
        raise SearchError(_FIRECRAWL_HTTP.get(exc.code, f"Firecrawl answered HTTP {exc.code}.")) from None
    except Exception as exc:
        if not key:
            _rest_firecrawl()
        raise SearchError(f"Firecrawl could not be reached ({net.describe_ssl_error(exc) or exc}).") from None
    if not isinstance(payload, dict) or payload.get("success") is False:
        said = payload.get("error") if isinstance(payload, dict) else payload
        raise SearchError(f"Firecrawl said: {str(said)[:160]}")
    return payload


def _firecrawl_search(query: str, limit: int) -> list[Result]:
    payload = _firecrawl("search", {"query": query[:500], "limit": limit})
    data = payload.get("data")
    # v2 groups results by source ({"web": [...]}); v1 answered a bare list.
    items = data.get("web", []) if isinstance(data, dict) else data or []
    results: list[Result] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if url.startswith("http"):
            title = _plain(str(item.get("title") or "")) or url
            snippet = _plain(str(item.get("description") or ""))[:400]
            results.append(Result(title, url, snippet, "Firecrawl"))
    return results[:limit]


def _firecrawl_page(url: str) -> tuple[str, str]:
    payload = _firecrawl("scrape", {"url": url, "formats": ["markdown"], "onlyMainContent": True})
    data = payload.get("data") or {}
    text = _BLANK.sub("\n\n", str(data.get("markdown") or "")).strip()
    if not text:
        raise SearchError("Firecrawl opened the page but found no text on it.")
    title = _plain(str((data.get("metadata") or {}).get("title") or "")) or url
    return title, text[:MAX_TEXT_CHARS]


def firecrawl_status(key: str = "") -> str:
    """'works — N credits left', for the Settings window's Test button.

    Asks for the credit balance, which costs no credits itself.
    """
    payload = _firecrawl("team/credit-usage", key=key)
    left = (payload.get("data") or {}).get("remainingCredits")
    return f"works — {left:,} credits left" if isinstance(left, int) else "works"


# --- searching -------------------------------------------------------------------

def search(query: str, limit: int = 6) -> list[Result]:
    """Search the web. Raises SearchError with something readable.

    Firecrawl first when there is a key, DuckDuckGo when there isn't or
    Firecrawl fails.
    """
    query = query.strip()
    if not query:
        raise SearchError("Nothing to search for.")
    problem = ""
    if _firecrawl_ready():
        try:
            results = _firecrawl_search(query, limit)
        except SearchError as exc:
            problem = str(exc)
        else:
            if results:
                return results
            problem = "Firecrawl found nothing."
    try:
        return _duckduckgo(query, limit)
    except SearchError as exc:
        if problem:
            raise SearchError(f"{problem} {exc}") from None
        raise


def _duckduckgo(query: str, limit: int) -> list[Result]:
    # POST, not GET. The same endpoint answers a GET with HTTP 202 and an
    # anti-bot page containing no results at all, which looks exactly like
    # "nothing matched" unless you check the status.
    import urllib.request

    # kp=1: DuckDuckGo's strict safe search (10.0.2, see safety.py).
    payload = urllib.parse.urlencode({"q": query, "kl": "us-en", "kp": "1"}).encode()
    request = urllib.request.Request(
        SEARCH_URL,
        data=payload,
        headers={
            "User-Agent": net.DEFAULT_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=TIMEOUT, context=net.ssl_context()
        ) as response:
            if response.status != 200:
                raise SearchError(
                    f"The search engine answered {response.status} instead of "
                    "results. It may be rate limiting this machine."
                )
            body = response.read(MAX_PAGE_BYTES).decode("utf-8", errors="replace")
    except SearchError:
        raise
    except Exception as exc:
        raise SearchError(f"The search request failed: {exc}")

    titles = list(_RESULT.finditer(body))
    snippets = [_clean(m.group("text")) for m in _SNIPPET.finditer(body)]
    results: list[Result] = []
    for index, match in enumerate(titles[:limit]):
        title = _clean(match.group("title"))
        url = _real_url(html.unescape(match.group("href")))
        if not title or not url.startswith("http"):
            continue
        results.append(Result(title, url, snippets[index] if index < len(snippets) else "", "DuckDuckGo"))

    if not results:
        raise SearchError(
            "No results came back. DuckDuckGo may have changed its page layout, "
            "or the query returned nothing."
        )
    return results


def fetch(url: str, deep: bool = True) -> tuple[str, str]:
    """Download a page and return (title, readable text).

    When the download fails or comes back nearly empty, and `deep` allows,
    Firecrawl reads the page instead. Page watches pass deep=False: they
    run on a timer and would spend a credit on every check.
    """
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    if not url.lower().startswith("https://"):
        # Plain HTTP can be rewritten in transit. Say so rather than quietly
        # treating whatever came back as fact.
        raise SearchError(
            f"{url} is not HTTPS, so what comes back cannot be trusted. "
            "Use an https:// address."
        )
    try:
        title, text = _download(url)
    except SearchError as exc:
        failure, title, text = str(exc), url, ""
    else:
        failure = ""
    if len(text) >= THIN_PAGE or not deep or not _firecrawl_ready():
        if failure:
            raise SearchError(failure)
        return title, text
    try:
        return _firecrawl_page(url)
    except SearchError as exc:
        if failure:
            raise SearchError(f"{failure}\n{exc}") from None
        return title, text


def _download(url: str) -> tuple[str, str]:
    try:
        with net.urlopen(url, timeout=TIMEOUT) as response:
            raw = response.read(MAX_PAGE_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        raise SearchError(f"Could not fetch {url}: {exc}")

    body = raw.decode(charset, errors="replace")
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    title = _clean(title_match.group(1)) if title_match else url

    body = _SCRIPT.sub(" ", body)
    body = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", body)
    text = _clean(body)
    text = _SPACE.sub(" ", text)
    text = _BLANK.sub("\n\n", text)
    return title, text[:MAX_TEXT_CHARS]
