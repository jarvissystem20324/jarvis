"""Addon system for JARVIS.

An addon is a single .py file in the `addons/` folder next to the app. Each one
declares commands, and may hook into the conversation to add context before a
message is sent or observe the reply after it comes back.

Addons are ordinary Python and run with the same privileges as JARVIS itself,
so treat one you didn't write exactly like any other program you're about to
run. The loader only reads the local folder — it never fetches anything.

Writing one::

    from jarvis.addons import Addon, Command

    class Hello(Addon):
        name = "hello"
        version = "1.0"
        description = "Says hello."

        def commands(self):
            return [Command("hello", self.hello, "Say hello", usage="/hello [name]")]

        def hello(self, ctx, args):
            return f"Hello, {args or 'sir'}."

    ADDON = Hello()
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import get_addons_dir, get_bundled_dir, get_data_dir


# Commands an addon may never claim. /run and /open in particular enforce a
# whitelist, and an addon quietly taking those over would defeat it — which
# matters as soon as addons are shared between people.
RESERVED_COMMANDS = frozenset({
    "quit", "exit", "clear", "voice", "image", "addons",
    "help", "run", "open", "search", "time", "date", "system",
})


@dataclass
class Command:
    """One slash command contributed by an addon."""

    name: str
    handler: Callable[["Context", str], Any]
    help: str = ""
    usage: str = ""


@dataclass
class Context:
    """What an addon is handed when its command runs."""

    jarvis: Any                       # the Jarvis orchestrator
    data_dir: Path                    # writable, shared by all addons

    def ask(self, prompt: str, image_b64: str | None = None) -> str:
        """Ask the model a one-off question, outside the chat history.

        Returns a message rather than raising when there's no assistant
        attached — the self-test loads addons with no orchestrator, and an
        addon calling this from on_load must not be able to fail the build.
        """
        if self.jarvis is None:
            return "No assistant is attached, so I can't answer that right now."
        return self.jarvis.brain.ask_once(prompt, image_b64=image_b64)

    def store(self, filename: str) -> Path:
        """A private file for this addon's state."""
        return self.data_dir / filename

    def say(self, text: str) -> None:
        """Speak, if voice is currently on. A no-op outside the running app."""
        if self.jarvis is None:
            return
        self.jarvis._maybe_speak(text)


class Addon:
    """Base class. Subclass, set the metadata, override what you need."""

    name: str = "unnamed"
    version: str = "1.0"
    description: str = ""
    # Set False to have JARVIS skip this addon without deleting the file.
    enabled: bool = True

    def commands(self) -> list[Command]:
        return []

    def on_load(self, ctx: Context) -> None:
        """Called once at startup, after the addon is accepted."""

    def enrich_prompt(self, ctx: Context, text: str) -> str | None:
        """Extra context to prepend to the user's message, or None."""
        return None

    def on_reply(self, ctx: Context, user_text: str, reply: str) -> None:
        """Observe a completed exchange (used by the memory addon)."""


@dataclass
class LoadedAddon:
    addon: Addon
    source: Path
    commands: dict[str, Command] = field(default_factory=dict)


class AddonManager:
    """Finds, loads, and dispatches to addons. Never lets one take the app down."""

    def __init__(self, jarvis: Any):
        self.ctx = Context(jarvis=jarvis, data_dir=get_data_dir())
        self.loaded: list[LoadedAddon] = []
        self.errors: list[str] = []

    # --- loading ----------------------------------------------------------

    def load_all(self) -> None:
        self.loaded.clear()
        self.errors.clear()

        folder = get_addons_dir()
        self._seed_bundled(folder)
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                self._load_one(path)
            except Exception:
                # A broken addon is a broken addon — the app keeps running.
                self.errors.append(f"{path.name}: {self._last_line()}")

    def _seed_bundled(self, folder: Path) -> None:
        """Copy the built-in addons out of a frozen build, once.

        They travel inside the EXE but have to live on disk beside it, both so
        the loader can see them and so users can open one up to see how an
        addon is written. Existing files are never overwritten — an edited or
        deleted addon stays edited or deleted across updates.
        """
        if not getattr(sys, "frozen", False):
            return
        source = get_bundled_dir() / "addons"
        if not source.is_dir():
            return

        marker = folder / ".seeded"
        already = set()
        if marker.exists():
            try:
                already = set(marker.read_text(encoding="utf-8").split())
            except OSError:
                already = set()

        seeded = set(already)
        for item in sorted(source.glob("*.py")):
            target = folder / item.name
            # Only place an addon we've never placed before, so one the user
            # deleted on purpose doesn't reappear at every update.
            if item.name in already or target.exists():
                seeded.add(item.name)
                continue
            try:
                shutil.copy2(item, target)
                seeded.add(item.name)
            except OSError as exc:
                self.errors.append(f"{item.name}: could not be installed — {exc}")

        if seeded != already:
            try:
                marker.write_text("\n".join(sorted(seeded)), encoding="utf-8")
            except OSError:
                pass

    def _load_one(self, path: Path) -> None:
        module_name = f"jarvis_addon_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError("could not be read")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        addon = self._find_addon(module)
        if addon is None:
            raise ImportError("no ADDON found")
        if not addon.enabled:
            return

        entry = LoadedAddon(addon=addon, source=path)
        for command in addon.commands():
            key = command.name.lstrip("/").lower()
            if not key:
                continue
            if key in RESERVED_COMMANDS:
                self.errors.append(
                    f"{path.name}: /{key} is a built-in command and cannot be "
                    f"overridden, skipped"
                )
                continue
            if any(key in other.commands for other in self.loaded):
                self.errors.append(f"{path.name}: /{key} already taken, skipped")
                continue
            entry.commands[key] = command

        try:
            addon.on_load(self.ctx)
        except Exception:
            self.errors.append(f"{addon.name}: on_load failed — {self._last_line()}")

        self.loaded.append(entry)

    @staticmethod
    def _find_addon(module) -> Addon | None:
        candidate = getattr(module, "ADDON", None)
        if isinstance(candidate, Addon):
            return candidate
        factory = getattr(module, "get_addon", None)
        if callable(factory):
            made = factory()
            if isinstance(made, Addon):
                return made
        # Fall back to a single Addon subclass defined in the file.
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, Addon) and value is not Addon:
                return value()
        return None

    @staticmethod
    def _last_line() -> str:
        lines = traceback.format_exc().strip().splitlines()
        return lines[-1] if lines else "unknown error"

    # --- dispatch ---------------------------------------------------------

    def has_command(self, name: str) -> bool:
        key = name.lstrip("/").lower()
        return any(key in entry.commands for entry in self.loaded)

    def handle(self, name: str, args: str) -> Any | None:
        """Run an addon command. Returns None if no addon owns `name`."""
        key = name.lstrip("/").lower()
        for entry in self.loaded:
            command = entry.commands.get(key)
            if command is None:
                continue
            try:
                return command.handler(self.ctx, args)
            except Exception:
                return (
                    f"Addon '{entry.addon.name}' failed running /{key}:\n"
                    f"  {self._last_line()}"
                )
        return None

    def context_for(self, text: str) -> str:
        """Context addons want prepended to `text`, or '' if they have none.

        Returns only the addition — the caller keeps the user's own words
        separate so history stays readable.
        """
        extras: list[str] = []
        for entry in self.loaded:
            try:
                extra = entry.addon.enrich_prompt(self.ctx, text)
            except Exception:
                continue
            if extra:
                extras.append(extra.strip())
        return "\n\n".join(extras)

    def notify_reply(self, user_text: str, reply: str) -> None:
        for entry in self.loaded:
            try:
                entry.addon.on_reply(self.ctx, user_text, reply)
            except Exception:
                continue

    # --- introspection ----------------------------------------------------

    def help_lines(self) -> list[str]:
        lines: list[str] = []
        for entry in self.loaded:
            for key, command in sorted(entry.commands.items()):
                usage = command.usage or f"/{key}"
                lines.append(f"  {usage:<28} {command.help}")
        return lines

    def summary(self) -> str:
        if not self.loaded and not self.errors:
            return (
                "No addons installed.\n"
                f"Drop .py files into {get_addons_dir()} to add commands."
            )
        parts: list[str] = []
        for entry in self.loaded:
            names = ", ".join(f"/{k}" for k in sorted(entry.commands)) or "no commands"
            parts.append(
                f"  {entry.addon.name} v{entry.addon.version} — "
                f"{entry.addon.description or 'no description'}\n"
                f"      {names}"
            )
        text = "Loaded addons:\n" + "\n".join(parts) if parts else "No addons loaded."
        if self.errors:
            text += "\n\nProblems:\n" + "\n".join(f"  {e}" for e in self.errors)
        return text
