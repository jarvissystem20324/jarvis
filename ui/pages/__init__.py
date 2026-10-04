"""The 10.0 pages, as the sidebar lists them.

Each entry names the module and class that draws the page, so nothing is
imported until a page is first opened. "chat", "image" and "design" are the
window's own older tabs and are drawn by app.py itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageInfo:
    key: str
    icon: str
    label: str
    section: str
    target: str = ""          # "module:Class"; empty for the window's built-in tabs
    keywords: str = ""


SECTIONS = ("Main", "Work", "PC", "Media and fun", "Life", "Me")

PAGES: tuple[PageInfo, ...] = (
    PageInfo("home", "🏠", "Home", "Main", "ui.pages.home:HomePage", "dashboard widgets start"),
    PageInfo("chat", "💬", "Chat", "Main", "", "talk ask conversation"),
    PageInfo("tools", "🧰", "Tools", "Main", "ui.pages.tools:ToolsPage", "every command all tools"),
    PageInfo("image", "🎨", "Image Gen", "Main", "", "picture generate"),
    PageInfo("design", "🖌", "Design", "Main", "", "slides poster logo"),
    PageInfo("code", "⌨", "Coding", "Main", "ui.pages.coding:CodingPage", "ide editor code project"),
    PageInfo("documents", "📄", "Documents", "Work", "ui.pages.documents:DocumentsPage", "pdf word excel office"),
    PageInfo("study", "🎓", "Study", "Work", "ui.pages.study:StudyPage", "school exam homework"),
    PageInfo("today", "✅", "Today", "Work", "ui.pages.productivity:TodayPage", "tasks goals plan"),
    PageInfo("calendar", "📅", "Calendar", "Work", "ui.pages.productivity:CalendarPage", "month week events"),
    PageInfo("notes", "🗒", "Notes", "Work", "ui.pages.productivity:NotesPage", "notes folders links"),
    PageInfo("inbox", "📥", "Inbox", "Work", "ui.pages.productivity:InboxPage", "email mail"),
    PageInfo("pc", "🖥", "PC", "PC", "ui.pages.pc:PCPage", "cpu ram gpu disk battery"),
    PageInfo("security", "🛡", "Security", "PC", "ui.pages.security:SecurityPage", "firewall privacy wifi"),
    PageInfo("antivirus", "🦠", "Antivirus", "PC", "ui.pages.security:AntivirusPage", "virus scan defender"),
    PageInfo("automations", "⚙", "Automations", "PC", "ui.pages.automations:AutomationsPage",
             "routines triggers macros"),
    PageInfo("phone", "📱", "Phone", "PC", "ui.pages.phone:PhonePage", "phone tv plug cast"),
    PageInfo("media", "🎬", "Media", "Media and fun", "ui.pages.media:MediaPage", "photo video audio gallery"),
    PageInfo("music", "🎵", "Music", "Media and fun", "ui.pages.music:MusicPage", "player radio playlist"),
    PageInfo("creator", "📹", "Creator", "Media and fun", "ui.pages.creator:CreatorPage", "youtube script"),
    PageInfo("gaming", "🎮", "Gaming", "Media and fun", "ui.pages.gaming:GamingPage", "games steam fps"),
    PageInfo("arcade", "🕹", "Arcade", "Media and fun", "ui.pages.arcade:ArcadePage", "chess snake 2048"),
    PageInfo("everyday", "☀", "Everyday", "Life", "ui.pages.life:EverydayPage", "recipes clock moon"),
    PageInfo("health", "💚", "Health", "Life", "ui.pages.life:HealthPage", "water habits bmi"),
    PageInfo("money", "💰", "Money", "Life", "ui.pages.life:MoneyPage", "budget expenses"),
    PageInfo("travel", "🧭", "Travel", "Life", "ui.pages.travel:TravelPage", "trip itinerary"),
    PageInfo("map", "🗺", "Map", "Life", "ui.pages.travel:MapPage", "map nearby places"),
    PageInfo("turkey", "🧿", "Türkiye", "Life", "ui.pages.life:TurkeyPage", "türkiye kdv istanbul"),
    PageInfo("memory", "🧠", "Memory", "Me", "ui.pages.me:MemoryPage", "remember facts"),
    PageInfo("voice", "🎧", "Voice", "Me", "ui.pages.me:VoicePage", "voice speak listen"),
)

BY_KEY = {p.key: p for p in PAGES}

# Pages whose module is not written yet. Only these get the "still being
# built" placeholder; any other page that fails to open says why. (The 10.0
# EXE once shipped without its page modules, and Home quietly showed
# "still being built" instead of the import error.)
STILL_BUILDING = {"phone", "media", "music", "creator", "gaming", "arcade", "everyday", "health", "money",
                  "travel", "map", "turkey"}


def page_class(key: str):
    """The class that draws page `key`; raises if it cannot be imported."""
    import importlib

    module_name, _, class_name = BY_KEY[key].target.partition(":")
    return getattr(importlib.import_module(module_name), class_name)


def make(key: str, master, app):
    """Create the page for `key` (not for the window's built-in tabs)."""
    info = BY_KEY[key]
    try:
        cls = page_class(key)
    except Exception as exc:
        from ui.pages.base import Hub

        class Placeholder(Hub):
            pass

        Placeholder.key, Placeholder.title, Placeholder.icon = info.key, info.label, info.icon
        if key in STILL_BUILDING:
            Placeholder.subtitle = "This page is still being built — its tools are on the Tools page."
        else:
            Placeholder.subtitle = (f"This page couldn't open: {type(exc).__name__}: {exc}\n"
                                    "Everything on it is still on the Tools page (Ctrl+K).")
        return Placeholder(master, app)
    return cls(master, app)
