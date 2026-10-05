"""Spell checking with Windows' own spell checker — the one Edge, Mail and
the touch keyboard use, in every language Windows has installed (Turkish
and English on most PCs here). No key, no network, nothing to download.

It is a COM API (ISpellCheckerFactory, Windows 8 and later) with no type
library, so its interfaces are declared here by hand with comtypes. COM
objects belong to the thread that made them, so each thread gets its own
checkers.

    check("Ths is a tset") -> [{"start": 0, "length": 3, "word": "Ths", "suggestions": ["This", ...]}, ...]
"""

from __future__ import annotations

import ctypes
import re
import sys
import threading

TURKISH = re.compile("[çğışöüÇĞİŞÖÜ]")
_local = threading.local()
_types = None


class SpellError(Exception):
    pass


def _interfaces():
    global _types
    if _types is not None:
        return _types
    from ctypes import POINTER, c_int, c_ulong, c_void_p, c_wchar_p

    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class ISpellingError(IUnknown):
        _iid_ = GUID("{B7C82D61-FBE8-4B47-9B27-6C0D2E0DE0A3}")
        _methods_ = [
            COMMETHOD([], HRESULT, "get_StartIndex", (["out"], POINTER(c_ulong), "value")),
            COMMETHOD([], HRESULT, "get_Length", (["out"], POINTER(c_ulong), "value")),
            COMMETHOD([], HRESULT, "get_CorrectiveAction", (["out"], POINTER(c_int), "value")),
            COMMETHOD([], HRESULT, "get_Replacement", (["out"], POINTER(c_void_p), "value")),
        ]

    class IEnumSpellingError(IUnknown):
        _iid_ = GUID("{803E3BD4-2828-4410-8290-418D1D73C762}")
        _methods_ = [COMMETHOD([], HRESULT, "Next", (["out"], POINTER(POINTER(ISpellingError)), "value"))]

    class IEnumString(IUnknown):
        _iid_ = GUID("{00000101-0000-0000-C000-000000000046}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Next", (["in"], c_ulong, "celt"), (["out"], POINTER(c_void_p), "value"),
                      (["out"], POINTER(c_ulong), "fetched")),
        ]

    class ISpellChecker(IUnknown):
        _iid_ = GUID("{B6FD0B71-E2BC-4653-8D05-F197E412770B}")
        _methods_ = [
            COMMETHOD([], HRESULT, "get_LanguageTag", (["out"], POINTER(c_void_p), "value")),
            COMMETHOD([], HRESULT, "Check", (["in"], c_wchar_p, "text"),
                      (["out"], POINTER(POINTER(IEnumSpellingError)), "value")),
            COMMETHOD([], HRESULT, "Suggest", (["in"], c_wchar_p, "word"),
                      (["out"], POINTER(POINTER(IEnumString)), "value")),
            COMMETHOD([], HRESULT, "Add", (["in"], c_wchar_p, "word")),
            COMMETHOD([], HRESULT, "Ignore", (["in"], c_wchar_p, "word")),
        ]

    class ISpellCheckerFactory(IUnknown):
        _iid_ = GUID("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
        _methods_ = [
            COMMETHOD([], HRESULT, "get_SupportedLanguages", (["out"], POINTER(POINTER(IEnumString)), "value")),
            COMMETHOD([], HRESULT, "IsSupported", (["in"], c_wchar_p, "tag"), (["out"], POINTER(c_int), "value")),
            COMMETHOD([], HRESULT, "CreateSpellChecker", (["in"], c_wchar_p, "tag"),
                      (["out"], POINTER(POINTER(ISpellChecker)), "value")),
        ]

    _types = {"factory": ISpellCheckerFactory, "clsid": GUID("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")}
    return _types


def _string(pointer) -> str:
    """A COM-allocated string, read and freed."""
    if not pointer:
        return ""
    try:
        return ctypes.wstring_at(pointer)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pointer))


def _factory():
    factory = getattr(_local, "factory", None)
    if factory is not None:
        return factory
    if sys.platform != "win32":
        raise SpellError("Spell checking uses Windows' spell checker.")
    try:
        import comtypes

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except OSError:
            pass                              # COM is already set up on this thread
        types = _interfaces()
        factory = comtypes.CoCreateInstance(types["clsid"], interface=types["factory"],
                                            clsctx=comtypes.CLSCTX_INPROC_SERVER)
    except Exception as exc:
        raise SpellError(f"Windows' spell checker isn't available: {exc}") from None
    _local.factory = factory
    _local.checkers = {}
    return factory


def languages() -> list[str]:
    try:
        enum = _factory().get_SupportedLanguages()
    except (SpellError, OSError):
        return []
    out = []
    while True:
        pointer, fetched = enum.Next(1)
        if not fetched:
            break
        out.append(_string(pointer))
    return out


def supported(tag: str) -> bool:
    try:
        return bool(_factory().IsSupported(tag))
    except (SpellError, OSError):
        return False


def available() -> bool:
    return bool(languages())


def _checker(tag: str):
    factory = _factory()
    checkers = _local.checkers
    if tag not in checkers:
        checkers[tag] = factory.CreateSpellChecker(tag) if factory.IsSupported(tag) else None
    return checkers[tag]


def default_language(text: str = "") -> str:
    if TURKISH.search(text or ""):
        return "tr-TR"
    try:
        from . import i18n

        if i18n.current() == "tr":
            return "tr-TR"
    except Exception:
        pass
    return "en-US"


def _raw(checker, text: str) -> list[tuple[int, int, int, str]]:
    found = []
    errors = checker.Check(text)
    while True:
        error = errors.Next()
        if not error:
            break
        found.append((error.get_StartIndex(), error.get_Length(), error.get_CorrectiveAction(),
                      _string(error.get_Replacement())))
    return found


def suggest(word: str, tag: str | None = None, limit: int = 5) -> list[str]:
    checker = _checker(tag or default_language(word))
    if checker is None:
        return []
    enum = checker.Suggest(word)
    out = []
    while len(out) < limit:
        pointer, fetched = enum.Next(1)
        if not fetched:
            break
        out.append(_string(pointer))
    return out


def check(text: str, tag: str | None = None) -> list[dict]:
    """Misspellings in text. A word the other language knows (an English word in a Turkish
    sentence, a Turkish name in an English one) isn't flagged."""
    if not (text or "").strip():
        return []
    tag = tag or default_language(text)
    checker = _checker(tag)
    if checker is None:
        tag = "en-US" if tag != "en-US" else "tr-TR"
        checker = _checker(tag)
        if checker is None:
            raise SpellError("No spell checker for this language is installed in Windows.")
    other = _checker("en-US" if tag.startswith("tr") else "tr-TR")
    out = []
    for start, length, action, replacement in _raw(checker, text):
        word = text[start:start + length]
        if other is not None and action != 3 and not _raw(other, word):
            continue
        if action == 2:
            suggestions = [replacement]
        elif action == 3:
            suggestions = [""]               # a repeated word: the fix is to delete it
        else:
            suggestions = suggest(word, tag)
        out.append({"start": start, "length": length, "word": word, "suggestions": suggestions})
    return out
