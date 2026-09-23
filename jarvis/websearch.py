"""Web search and page reading.

`/search` used to open your browser, which is not the same thing as JARVIS
knowing something. This actually fetches results and pages, strips them to
readable text, and hands that to the model — with the URLs shown, so you can
check where an answer came from rather than taking its word for it.

DuckDuckGo's HTML endpoint is used because it needs no key and no account,
which matches the rest of this project. It is scraping, so it will break one
day; when it does, the failure says so plainly instead of silently returning
nothing.

Nothing here executes what it downloads. Pages are stripped to text, scripts
and styles are removed outright, and the result is treated as untrusted text
that happens to be about a topic — a page telling JARVIS to ignore its
instructions is just words on a page.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from . import net

SEARCH_URL = "https://html.duckduckgo.com/html/"
MAX_PAGE_BYTES = 800_000
MAX_TEXT_CHARS = 12_000
TIMEOUT = 25

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n\s*\n\s*\n+")
_RESULT = re.compile(
    r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
)
_SNIPPET = re.compile(r'(?is)<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<text>.*?)</a>')


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""

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


def search(query: str, limit: int = 6) -> list[Result]:
    """Search the web. Raises SearchError with something readable."""
    query = query.strip()
    if not query:
        raise SearchError("Nothing to search for.")
    # POST, not GET. The same endpoint answers a GET with HTTP 202 and an
    # anti-bot page containing no results at all, which looks exactly like
    # "nothing matched" unless you check the status.
    import urllib.request

    payload = urllib.parse.urlencode({"q": query, "kl": "us-en"}).encode()
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
        results.append(Result(title, url, snippets[index] if index < len(snippets) else ""))

    if not results:
        raise SearchError(
            "No results came back. DuckDuckGo may have changed its page layout, "
            "or the query returned nothing."
        )
    return results


def fetch(url: str) -> tuple[str, str]:
    """Download a page and return (title, readable text)."""
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
