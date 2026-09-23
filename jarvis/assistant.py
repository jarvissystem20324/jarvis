"""Core JARVIS assistant orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import history, modes, personality, providers, scanner, security, tools
from .addons import AddonManager
from .brain import Brain
from .config import voice_enabled_by_default
from .images import DEFAULT_QUALITY, ImageGenerationError, ImageGenerator
from .voice import Voice


@dataclass
class JarvisResponse:
    text: str
    image_path: Path | None = None
    should_quit: bool = False


class Jarvis:
    def __init__(self, voice_enabled: bool | None = None):
        self.brain = Brain()
        self.images = ImageGenerator()
        self.voice = Voice()
        if voice_enabled is None:
            voice_enabled = voice_enabled_by_default()
        self.voice_enabled = bool(voice_enabled) and self.voice.available()
        self.addons = AddonManager(self)
        self.addons.load_all()

    def greet(self) -> str:
        text = personality.greeting()
        self._maybe_speak(text)
        return text

    def farewell(self) -> str:
        text = personality.FAREWELL
        if self.voice_enabled:
            self.voice.speak(text, block=True)
        return text

    def toggle_voice(self) -> str:
        if not self.voice.available():
            return "Voice module unavailable."

        self.voice_enabled = not self.voice_enabled
        if not self.voice_enabled:
            self.voice.stop()

        parts = []
        if self.voice.tts_available():
            parts.append("speech output")
        if self.voice.mic_available():
            parts.append("microphone input")
        state = "enabled" if self.voice_enabled else "disabled"
        return f"Voice mode {state} ({' and '.join(parts) or 'voice'})."

    def generate_image(
        self, prompt: str, size: str = "1024x1024", quality: str = DEFAULT_QUALITY
    ) -> JarvisResponse:
        try:
            path = self.images.generate(prompt, size=size, quality=quality)
        except ImageGenerationError as exc:
            return JarvisResponse(text=str(exc))

        self._maybe_speak("Image generated, sir.")
        return JarvisResponse(
            text=f"Image generated successfully.\nSaved to: {path}",
            image_path=path,
        )

    def process(
        self,
        user_input: str,
        should_commit: Callable[[], bool] | None = None,
        on_chunk: Callable[[str | None], None] | None = None,
    ) -> JarvisResponse:
        """Handle one input.

        `should_commit` lets the caller disown a finished exchange and
        `on_chunk` receives the answer as it streams — both are passed
        straight through to Brain.chat. Commands never stream: they are
        answered here, whole, without reaching a provider.
        """
        text = (user_input or "").strip()
        if not text:
            return JarvisResponse(text="I didn't catch that. Could you repeat?")

        if text.startswith("/"):
            name, _, args = text[1:].strip().partition(" ")
            name = name.lower()

            if name in {"quit", "exit"}:
                return JarvisResponse(text=self.farewell(), should_quit=True)

            if name == "clear":
                self.brain.clear_history()
                history.clear()
                return JarvisResponse(text="Conversation history cleared.")

            if name == "export":
                if not self.brain.history:
                    return JarvisResponse(text="Nothing to export yet.")
                path = history.export_markdown(self.brain.history)
                return JarvisResponse(
                    text=f"Conversation saved to:\n  {path}"
                )

            if name == "retry":
                return self.retry(args)

            if name == "voice":
                return JarvisResponse(text=self.toggle_voice())

            if name == "image":
                if not args.strip():
                    return JarvisResponse(
                        text="Usage: /image <prompt>\n"
                        "Example: /image a futuristic AI lab at night"
                    )
                return self.generate_image(args)

            if name == "addons":
                return JarvisResponse(text=self.addons.summary())

            if name == "mode":
                return JarvisResponse(text=self.set_mode(args))

            if name == "code":
                return JarvisResponse(text=self.toggle_code_mode())

            if name == "privacy":
                # Log the switch-on *before* flipping it, or the audit trail
                # just stops with no explanation — and a gap you cannot
                # account for is the one thing an audit log must not have.
                if not security.privacy.on:
                    security.audit.record(
                        "privacy", "enabled", "recording stops here"
                    )
                text_out = security.privacy.toggle()
                if not security.privacy.on:
                    security.audit.record("privacy", "disabled", "recording resumed")
                return JarvisResponse(text=text_out)

            if name == "security":
                return JarvisResponse(text=security.summary())

            if name == "audit":
                return JarvisResponse(text=self.show_audit(args))

            if name == "scan":
                return JarvisResponse(text=self.scan(args))

            if name == "sandbox":
                return JarvisResponse(text=self.sandbox(args))

            if name == "bench":
                return JarvisResponse(text=self.bench(args))

            if name == "compare":
                return JarvisResponse(text=self.compare(args))

            if name in {"chat", "chats"}:
                return JarvisResponse(text=self.chats(args if name == "chat" else ""))

            # Addons are dispatched before the offline tools so they can add
            # new commands. They cannot capture a built-in: the loader refuses
            # to register anything in RESERVED_COMMANDS.
            handled = self.addons.handle(name, args)
            if handled is not None:
                if isinstance(handled, JarvisResponse):
                    return handled
                text_out = str(handled)
                self._maybe_speak(text_out)
                return JarvisResponse(text=text_out)

            builtin = tools.try_handle_command(text)
            if builtin is not None:
                if name == "help":
                    builtin = self._with_addon_help(builtin)
                self._maybe_speak(builtin)
                return JarvisResponse(text=builtin)

        reply = self.brain.chat(
            text,
            extra_context=self.addons.context_for(text) or None,
            should_commit=should_commit,
            on_chunk=on_chunk,
        )
        self.addons.notify_reply(text, reply)
        self._maybe_speak(reply)
        return JarvisResponse(text=reply)

    # --- measuring and comparing ------------------------------------------

    # Generous on purpose. Several of these models think before they write,
    # and at 400 tokens mercury-2.5 returned nothing at all while
    # gemini-3.6-flash was cut off mid-sentence — which makes a comparison
    # actively misleading rather than merely short.
    PROBE_TOKENS = 2048

    def _probe(self, provider, model: str, prompt: str, timeout: float):
        """One timed request. Returns (ok, seconds, text_or_reason)."""
        import time

        started = time.time()
        try:
            if provider.transport == "http":
                text = providers.pollinations_chat(model, [
                    {"role": "user", "content": prompt}
                ])
                return True, time.time() - started, text

            client = providers.get_client(provider).with_options(
                timeout=timeout, max_retries=0
            )
            messages = [{"role": "user", "content": prompt}]
            last: Exception | None = None
            # Providers disagree about which of these they accept, and Gemini
            # honours them differently, so try both rather than guess.
            for param in ("max_tokens", "max_completion_tokens"):
                try:
                    reply = client.chat.completions.create(
                        model=model, messages=messages, **{param: self.PROBE_TOKENS}
                    )
                except Exception as exc:
                    last = exc
                    continue
                choice = reply.choices[0]
                text = (choice.message.content or "").strip()
                if text:
                    return True, time.time() - started, text
                if getattr(choice, "finish_reason", "") != "length":
                    return True, time.time() - started, ""
            if last is not None:
                raise last
            return False, time.time() - started, "answered with nothing"
        except Exception as exc:
            return False, time.time() - started, self.brain._short(exc)

    def bench(self, args: str) -> str:
        """Time every provider, so a dead one is obvious before it matters.

        Three separate failures this project hit — a retired model, a revoked
        key, a model that accepts requests and never answers — all looked
        identical from inside a conversation: JARVIS just got slower or
        quieter. This asks every backend the same trivial question and says
        plainly which ones are alive and how fast.
        """
        import concurrent.futures as futures

        prompt = args.strip() or "Reply with exactly: OK"
        targets: list[tuple] = []
        seen: set[tuple[str, str]] = set()

        # Whatever the modes reach for, plus each provider's own default.
        for mode in modes.ALL:
            for pname, model in modes.targets_for(mode):
                provider = providers.BY_NAME.get(pname)
                if provider and providers.has_key(provider) and (pname, model) not in seen:
                    targets.append((mode.label, provider, model))
                    seen.add((pname, model))
        for provider in providers.chat_chain():
            model = providers.model_for(provider)
            if (provider.name, model) not in seen:
                targets.append(("—", provider, model))
                seen.add((provider.name, model))

        if not targets:
            return "No providers are configured, so there is nothing to measure."

        security.audit.record("bench", f"{len(targets)} models")

        def run(entry):
            label, provider, model = entry
            ok, secs, text = self._probe(provider, model, prompt, timeout=45)
            return label, provider, model, ok, secs, text

        with futures.ThreadPoolExecutor(max_workers=5) as pool:
            rows = list(pool.map(run, targets))

        alive = [r for r in rows if r[3]]
        alive.sort(key=lambda r: r[5])
        dead = [r for r in rows if not r[3]]

        lines = [f"Benchmark — {len(alive)} of {len(rows)} answered"]
        if alive:
            lines.append("")
            lines.append(f"  {'MODE':11} {'MODEL':38} {'TIME':>7}")
            for label, provider, model, _ok, secs, _t in alive:
                lines.append(f"  {label:11} {model[:38]:38} {secs:6.1f}s")
        if dead:
            lines.append("")
            lines.append("  Did not answer:")
            for label, provider, model, _ok, secs, why in dead:
                lines.append(f"    {model[:38]:38} {why[:40]}  ({secs:.0f}s)")
            lines.append("")
            lines.append(
                "  A mode whose model is listed here still works — it falls "
                "through to the provider chain."
            )
        return "\n".join(lines)

    def compare(self, args: str) -> str:
        """Ask several models the same question and show the answers together.

        Useful for deciding what a tier should use, and for showing someone
        why the failover chain is not just redundancy — the models genuinely
        differ.
        """
        import concurrent.futures as futures

        question = args.strip()
        if not question:
            return (
                "Usage: /compare <question>\n"
                "Asks Low, Mid, High and Max's models the same thing and puts "
                "the answers side by side."
            )

        targets: list[tuple[str, object, str]] = []
        seen: set[tuple[str, str]] = set()
        for mode in (modes.LOW, modes.MID, modes.HIGH, modes.MAX):
            for pname, model in modes.targets_for(mode):
                provider = providers.BY_NAME.get(pname)
                if provider and providers.has_key(provider) and (pname, model) not in seen:
                    targets.append((mode.label, provider, model))
                    seen.add((pname, model))
                break  # one model per tier is enough to compare
        if not targets:
            return "No configured models to compare."

        security.audit.record("compare", f"{len(targets)} models")

        def run(entry):
            label, provider, model = entry
            ok, secs, text = self._probe(provider, model, question, timeout=60)
            return label, provider, model, ok, secs, text

        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(run, targets))

        blocks = [f"Same question, {len(rows)} models:\n"]
        for label, provider, model, ok, secs, text in rows:
            head = f"── {label}  ·  {provider.label} {model}  ·  {secs:.1f}s"
            body = text.strip() if ok else f"[failed: {text}]"
            blocks.append(f"{head}\n{body}")
        return "\n\n".join(blocks)

    # --- conversations ----------------------------------------------------

    def chats(self, args: str) -> str:
        """List, switch, create or delete named conversations."""
        parts = args.strip().split(maxsplit=1)
        verb = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if not verb or verb == "list":
            saved = history.list_chats()
            here = history.current_name()
            # A conversation you have just started has nothing on disk yet.
            # Leaving it out of its own list reads like it does not exist.
            if here not in {c["name"] for c in saved}:
                saved.insert(0, {
                    "name": here,
                    "saved": "",
                    "exchanges": len(self.brain.history) // 2,
                })
            if not saved:
                return "Only this conversation so far. /chat new <name> starts another."
            lines = [f"Conversations ({len(saved)}):"]
            for item in saved:
                mark = ">" if item["name"] == here else " "
                when = item["saved"][:16].replace("T", " ") or "never saved"
                lines.append(
                    f"  {mark} {item['name']:<24} {item['exchanges']:>3} exchanges   {when}"
                )
            lines.append("")
            lines.append("/chat <name> to switch, /chat new <name>, /chat delete <name>")
            return "\n".join(lines)

        if verb == "new":
            name = rest or f"chat-{len(history.list_chats()) + 1}"
            self.save_history()
            history.set_current(name)
            self.brain.clear_history()
            return f"Started '{name}'. The previous conversation is saved and /chat lists them."

        if verb == "delete":
            if not rest:
                return "Usage: /chat delete <name>"
            if rest == history.current_name():
                return (
                    f"'{rest}' is the conversation you are in. Switch to another "
                    "one first, then delete it."
                )
            if history.delete_chat(rest):
                return f"Deleted '{rest}'."
            return f"There is no conversation called '{rest}'."

        # Anything else is a name to switch to.
        target = args.strip()
        known = {c["name"] for c in history.list_chats()}
        if target not in known:
            return (
                f"No conversation called '{target}'.\n"
                f"Known: {', '.join(sorted(known)) or 'none'}\n"
                f"Start it with /chat new {target}"
            )
        self.save_history()
        history.set_current(target)
        note = self.restore_history()
        return f"Switched to '{target}'. {note or 'It is empty.'}"

    # --- security ---------------------------------------------------------

    def show_audit(self, args: str) -> str:
        """What JARVIS has actually done, newest last."""
        if args.strip().lower() == "clear":
            return security.audit.clear()

        entries = security.audit.read(limit=40)
        if not entries:
            if security.privacy.on:
                return "Privacy mode is on, so nothing is being recorded."
            return f"Nothing recorded yet. The log lives at {security.audit.path()}"

        lines = []
        for item in entries:
            when = str(item.get("at", ""))[11:19]
            row = f"  {when}  {item.get('action', '?')}"
            if item.get("detail"):
                row += f": {item['detail']}"
            if item.get("outcome"):
                row += f"  [{item['outcome']}]"
            lines.append(row)
        return (
            f"Last {len(entries)} actions (no message content is recorded):\n"
            + "\n".join(lines)
            + f"\n\nFull log: {security.audit.path()}   /audit clear to wipe it."
        )

    def _project_root(self):
        """The folder code mode has open, if any."""
        for entry in self.addons.loaded:
            root = getattr(entry.addon, "root", None)
            if root is not None:
                return root
        return None

    def scan(self, args: str) -> str:
        """Look for security problems — in a path, or in JARVIS itself."""
        target = args.strip().strip('"').strip("'")
        security.audit.record("scan", target or "self + open project")

        sections: list[str] = []
        findings: list[scanner.Finding] = []

        if not target or target.lower() == "self":
            own = security.env_file_findings()
            if own:
                sections.append(
                    "JARVIS's own install:\n"
                    + "\n".join(
                        f"  [{level.upper():4}] {title}\n         {detail}"
                        for level, title, detail in own
                    )
                )
            else:
                sections.append("JARVIS's own install:\n  Nothing wrong found.")

        if target and target.lower() != "self":
            path = Path(target).expanduser()
            if not path.exists():
                return f"No such file or folder:\n  {path}"
            if path.is_dir():
                findings, seen = scanner.scan_project(path)
                sections.append(
                    f"{path} — {seen} files read\n" + scanner.format_report(findings)
                )
            else:
                findings = scanner.scan_file(path)
                sections.append(f"{path}\n" + scanner.format_report(findings))
        elif not target:
            root = self._project_root()
            if root is not None:
                findings, seen = scanner.scan_project(root)
                sections.append(
                    f"Open project {root} — {seen} files read\n"
                    + scanner.format_report(findings)
                )
            else:
                sections.append(
                    "No project open, so I only checked JARVIS itself.\n"
                    "  /project <folder> first, or /scan <path> for a one-off."
                )

        report = "\n\n".join(sections)
        high = sum(1 for f in findings if f.level == "high")
        warn = sum(1 for f in findings if f.level == "warn")
        headline = (
            f"{high} high, {warn} worth a look"
            if findings else "Nothing flagged"
        )

        verdict = ""
        if findings:
            worst = scanner.format_report(findings, limit=12)
            verdict = self.brain.ask_once(
                "You are reviewing the output of a static security scan. Say "
                "which of these actually matter and in what order, and which "
                "are noise. Be brief and concrete. Do not repeat the list.\n\n"
                + worst
            )
            verdict = f"\n\nWhat I make of it:\n{verdict}"

        return f"Security scan — {headline}\n\n{report}{verdict}"

    def sandbox(self, args: str) -> str:
        """Say what a piece of code would do. Never runs it.

        Sandbox mode here is analysis, not containment: this machine is
        Windows Home, which has no Windows Sandbox and no Hyper-V, and a
        subprocess under the same user account is not isolation. Reading the
        code and reporting its capabilities is a promise that can actually be
        kept — nothing ever executes, so nothing can escape.
        """
        target = args.strip().strip('"').strip("'")
        if not target:
            return (
                "Usage: /sandbox <file>\n"
                "I read the file and tell you what it would do — network, files, "
                "processes, persistence, obfuscation — without ever running it."
            )
        path = Path(target).expanduser()
        if not path.exists():
            return f"No such file:\n  {path}"
        if path.is_dir():
            return f"That's a folder. Point me at one file, or use /scan {path}"

        try:
            if path.stat().st_size > scanner.MAX_SCAN_BYTES:
                return f"{path.name} is too large to analyse in one go."
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Couldn't read it: {exc}"

        security.audit.record("sandbox", path.name, "analysed, not executed")

        caps = scanner.capabilities(text)
        findings = scanner.scan_text(text, path.name, path.suffix.lower())
        level = scanner.risk_level(findings, caps)

        parts = [
            f"Sandbox analysis — {path.name}  ({len(text.splitlines())} lines)",
            f"Risk: {level}     Nothing was executed.",
        ]
        if caps:
            block = []
            for title, meaning, hits in caps:
                block.append(f"  - {title} — {meaning}")
                block.extend(f"      {h}" for h in hits)
            parts.append("What it can do:\n" + "\n".join(block))
        else:
            parts.append(
                "What it can do:\n  Nothing that reaches outside itself — no "
                "network, files, or other processes."
            )
        if findings:
            parts.append("Problems in the code:\n" + scanner.format_report(findings, 10))

        explanation = self.brain.ask_once(
            "This file was sent to the user and has NOT been run. From the "
            "source alone, say what the program is for, whether its behaviour "
            "matches what it claims, and whether you would run it. If anything "
            "is disguised, say exactly where. Be brief.\n\n"
            f"--- {path.name} ---\n{text[:20000]}"
        )
        parts.append(f"Verdict:\n{explanation}")
        return "\n\n".join(parts)

    # --- modes ------------------------------------------------------------

    def set_mode(self, args: str) -> str:
        """Show or change the thinking mode."""
        wanted = (args or "").strip().lower()
        if not wanted:
            lines = [f"Mode: {self.brain.mode.label} — {self.brain.mode.blurb}", "", "Available:"]
            for mode in modes.ALL:
                mark = ">" if mode.name == self.brain.mode.name else " "
                lines.append(f"  {mark} {mode.label:<11} {mode.blurb}")
            lines.append("")
            lines.append("Switch with /mode <name>, e.g. /mode high")
            return "\n".join(lines)

        if wanted not in modes.BY_NAME:
            names = ", ".join(m.name for m in modes.ALL)
            return f"No such mode '{wanted}'. Choose one of: {names}"

        mode = self.brain.set_mode(wanted)
        note = ""
        if mode.name == "hyperdrive":
            note = (
                "\n\nHyperdrive reaches for kimi-k3 first and waits up to 200 "
                "seconds. That model often never answers on the free tier, in "
                "which case JARVIS drops back to Max automatically — so the "
                "first reply may take a while."
            )
        return f"Mode set to {mode.label}. {mode.blurb}{note}"

    def toggle_code_mode(self) -> str:
        """Turn the engineering persona on or off."""
        self.brain.code_mode = not self.brain.code_mode
        # system_prompt() reads persona_override, so flipping the flag alone
        # left code mode claiming to be on while the model never saw it.
        self.brain.persona_override = (
            personality.CODE_MODE_PROMPT if self.brain.code_mode else None
        )
        window = getattr(self, "window", None)
        if window is not None:
            try:
                window.after(0, window.refresh_code_mode)
            except Exception:
                pass
        if self.brain.code_mode:
            return (
                "Code mode on. I'll write complete, runnable code, choose an "
                "approach rather than offer a menu, and say what changed. "
                "Use /code again to switch back."
            )
        return "Code mode off. Back to normal conversation."

    def retry(self, args: str) -> JarvisResponse:
        """Ask the last question again, optionally on a different provider.

        A provider having an off moment is common enough — a throttled model,
        a truncated answer — that re-asking without retyping is worth a
        command. The failed answer is dropped so it cannot influence the new
        one.
        """
        last_user = next(
            (m["content"] for m in reversed(self.brain.history)
             if m.get("role") == "user"),
            None,
        )
        if last_user is None:
            return JarvisResponse(text="There's nothing to retry yet.")

        wanted = (args or "").strip().lower()
        if wanted and wanted not in providers.BY_NAME:
            names = ", ".join(p.name for p in providers.AUTO_CHAT_PROVIDERS)
            return JarvisResponse(
                text=f"No provider called '{wanted}'. Try one of: {names}"
            )

        # Drop the exchange being retried so the model isn't anchored to it.
        while self.brain.history and self.brain.history[-1].get("role") == "assistant":
            self.brain.history.pop()
        if self.brain.history and self.brain.history[-1].get("role") == "user":
            self.brain.history.pop()

        previous = None
        if wanted:
            import os

            previous = os.environ.get("JARVIS_PROVIDER")
            os.environ["JARVIS_PROVIDER"] = wanted
            self.brain._cooldown.clear()
            self.brain._dead.discard(wanted)
        try:
            reply = self.brain.chat(
                last_user, extra_context=self.addons.context_for(last_user) or None
            )
        finally:
            if wanted:
                import os

                if previous is None:
                    os.environ.pop("JARVIS_PROVIDER", None)
                else:
                    os.environ["JARVIS_PROVIDER"] = previous

        self._maybe_speak(reply)
        return JarvisResponse(text=reply)

    def save_history(self) -> None:
        """Persist the conversation so closing the window doesn't lose it.

        Privacy mode stops this entirely — what is already saved is left
        alone, but nothing new is written.
        """
        if security.privacy.on:
            return
        history.save(
            self.brain.history,
            mode=self.brain.mode.name,
            code_mode=self.brain.code_mode,
        )

    def restore_history(self) -> str:
        """Reload the previous conversation. Returns a note, or ''."""
        messages, mode, code_mode = history.load()
        if not messages:
            self.brain.clear_history()
            return ""
        self.brain.history = messages
        if mode:
            self.brain.set_mode(mode)
        if code_mode:
            self.brain.code_mode = True
            self.brain.persona_override = personality.CODE_MODE_PROMPT
        return history.describe_saved()

    def _with_addon_help(self, builtin: str) -> str:
        lines = self.addons.help_lines()
        if not lines:
            return builtin
        return builtin + "\n\nFrom addons:\n" + "\n".join(lines)

    def listen_and_respond(self) -> JarvisResponse | None:
        if not self.voice_enabled:
            return JarvisResponse(text="Voice mode is disabled. Use /voice to enable it.")
        if not self.voice.mic_available():
            return JarvisResponse(
                text="Microphone unavailable. You can still hear my responses."
            )

        # Don't record our own voice.
        self.voice.stop()
        try:
            heard = self.voice.listen()
        except RuntimeError as exc:
            return JarvisResponse(text=str(exc))

        if not heard:
            return JarvisResponse(text="I didn't hear anything. Please try again.")
        return self.process(heard)

    def _maybe_speak(self, text: str) -> None:
        if self.voice_enabled and self.voice.tts_available():
            self.voice.speak(text)
