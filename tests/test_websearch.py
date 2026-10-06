"""Web search through Firecrawl, with DuckDuckGo behind it (10.0.2).

Nothing here reaches the network: Firecrawl's API and the plain download
are replaced, and the conftest blanks the real key for the whole run.
"""

from __future__ import annotations

import time
import urllib.error

import pytest

from jarvis import net, websearch
from jarvis.websearch import Result, SearchError


@pytest.fixture
def keyed(monkeypatch):
    """A Firecrawl key, and Firecrawl not resting from an earlier test."""
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setattr(websearch, "_firecrawl_off_until", 0.0)
    return monkeypatch


def _no_duckduckgo(query, limit):
    raise AssertionError("DuckDuckGo should not have been asked")


def test_firecrawl_answers_first_and_its_markdown_becomes_text(keyed):
    calls = []

    def fake(path, body=None, key=""):
        calls.append((path, body))
        return {"success": True, "data": {"web": [
            {"url": "https://docs.python.org/3/whatsnew/3.14.html", "title": "**What's new** in Python 3.14",
             "description": "# What's new [¶](https://docs.python.org/3/whatsnew/3.14.html#wha"},
            {"url": "https://www.python.org/downloads/", "title": "",
             "description": "**Release date:** Oct. 7, 2025 [[9]](https://en.wikipedia.org/wiki/X#cite_note-9) "
                            "![logo](https://x.example/l.png)"},
            {"url": "ftp://not-a-page", "title": "skipped"},
        ]}}

    keyed.setattr(websearch, "_firecrawl", fake)
    keyed.setattr(websearch, "_duckduckgo", _no_duckduckgo)
    results = websearch.search("python 3.14 release", limit=5)
    assert calls == [("search", {"query": "python 3.14 release", "limit": 5})]
    assert [r.engine for r in results] == ["Firecrawl", "Firecrawl"]
    assert results[0].title == "What's new in Python 3.14"
    assert results[0].snippet == "What's new ¶"
    # No title: the address stands in for one.
    assert results[1].title == "https://www.python.org/downloads/"
    assert results[1].snippet == "Release date: Oct. 7, 2025"
    assert websearch.engine() == "Firecrawl"


def test_without_a_key_duckduckgo_answers(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "")

    def no_firecrawl(*a, **k):
        raise AssertionError("Firecrawl has no key")

    monkeypatch.setattr(websearch, "_firecrawl", no_firecrawl)
    monkeypatch.setattr(websearch, "_duckduckgo",
                        lambda q, n: [Result("Python", "https://python.org", "", "DuckDuckGo")])
    assert websearch.search("python")[0].engine == "DuckDuckGo"
    assert websearch.engine() == "DuckDuckGo"


def test_a_refused_firecrawl_falls_back_and_rests(keyed):
    """Out of credit: DuckDuckGo answers, and Firecrawl isn't asked again
    on every search for the next few minutes."""
    asked = []

    def payment_required(request, timeout=0, data=None):
        asked.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 402, "Payment Required", {}, None)

    keyed.setattr(net, "urlopen", payment_required)
    keyed.setattr(websearch, "_duckduckgo",
                  lambda q, n: [Result("Python", "https://python.org", "", "DuckDuckGo")])
    assert websearch.search("python")[0].engine == "DuckDuckGo"
    assert asked == ["https://api.firecrawl.dev/v2/search"]
    assert websearch._firecrawl_off_until > time.time() + 200
    websearch.search("python again")
    assert len(asked) == 1
    websearch.reset()            # a new key saved in Settings
    websearch.search("python")
    assert len(asked) == 2


def test_both_engines_failing_says_why_for_each(keyed):
    def refused(request, timeout=0, data=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    def nothing(query, limit):
        raise SearchError("No results came back.")

    keyed.setattr(net, "urlopen", refused)
    keyed.setattr(websearch, "_duckduckgo", nothing)
    with pytest.raises(SearchError) as caught:
        websearch.search("python")
    assert "refused the key" in str(caught.value) and "No results came back" in str(caught.value)


def test_firecrawl_finding_nothing_asks_duckduckgo_without_resting(keyed):
    keyed.setattr(websearch, "_firecrawl", lambda path, body=None, key="": {"success": True, "data": {"web": []}})
    keyed.setattr(websearch, "_duckduckgo",
                  lambda q, n: [Result("Rare", "https://rare.example", "", "DuckDuckGo")])
    assert websearch.search("a rare thing")[0].url == "https://rare.example"
    assert websearch._firecrawl_off_until == 0.0


def test_a_thin_page_is_read_through_firecrawl(keyed):
    """A page drawn by JavaScript downloads as little more than its title."""
    keyed.setattr(websearch, "_download", lambda url: ("App", "Loading…"))
    page = "# Results\n\n\n\n" + "The results are published. " * 30
    keyed.setattr(websearch, "_firecrawl", lambda path, body=None, key="": {
        "success": True, "data": {"markdown": page, "metadata": {"title": "Exam **results**"}}})
    title, text = websearch.fetch("https://exams.example/results")
    assert title == "Exam results" and text.startswith("# Results\n\nThe results")
    # Page watches run on a timer, so they never spend a credit.
    assert websearch.fetch("https://exams.example/results", deep=False) == ("App", "Loading…")


def test_a_full_page_is_not_sent_to_firecrawl(keyed):
    keyed.setattr(websearch, "_download", lambda url: ("Article", "words " * 200))

    def no_firecrawl(*a, **k):
        raise AssertionError("the page was readable already")

    keyed.setattr(websearch, "_firecrawl", no_firecrawl)
    assert websearch.fetch("https://news.example/a")[0] == "Article"


def test_a_blocked_page_is_read_through_firecrawl_or_says_both(keyed):
    def blocked(url):
        raise SearchError(f"Could not fetch {url}: HTTP Error 403: Forbidden")

    keyed.setattr(websearch, "_download", blocked)
    keyed.setattr(websearch, "_firecrawl", lambda path, body=None, key="": {
        "success": True, "data": {"markdown": "Real text", "metadata": {}}})
    assert websearch.fetch("https://shop.example/p") == ("https://shop.example/p", "Real text")

    def refused(path, body=None, key=""):
        raise SearchError("Firecrawl said: blocked")

    keyed.setattr(websearch, "_firecrawl", refused)
    with pytest.raises(SearchError) as caught:
        websearch.fetch("https://shop.example/p")
    assert "403" in str(caught.value) and "Firecrawl said: blocked" in str(caught.value)


def test_plain_http_is_still_refused_before_anything_is_fetched(keyed):
    def nothing_fetched(*a, **k):
        raise AssertionError("fetched")

    keyed.setattr(websearch, "_download", nothing_fetched)
    keyed.setattr(websearch, "_firecrawl", nothing_fetched)
    with pytest.raises(SearchError, match="not HTTPS"):
        websearch.fetch("http://example.com")


def test_the_settings_test_reports_credits_and_never_rests_firecrawl(keyed):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"success": true, "data": {"remainingCredits": 11012}}'

    def answer(request, timeout=0, data=None):
        seen["auth"] = request.get_header("Authorization")
        seen["url"] = request.full_url
        return Response()

    keyed.setattr(net, "urlopen", answer)
    assert websearch.firecrawl_status("fc-typed") == "works — 11,012 credits left"
    assert seen == {"auth": "Bearer fc-typed", "url": "https://api.firecrawl.dev/v2/team/credit-usage"}

    def refused(request, timeout=0, data=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    keyed.setattr(net, "urlopen", refused)
    with pytest.raises(SearchError, match="refused the key"):
        websearch.firecrawl_status("fc-wrong")
    assert websearch._firecrawl_off_until == 0.0      # the saved key may be fine
