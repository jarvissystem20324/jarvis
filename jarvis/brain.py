"""LLM integration for JARVIS.

Requests walk the provider chain until one answers. That is what lets the app
survive a missing key or an empty balance: OpenAI going quiet demotes it for
the session and the next backend takes over, rather than the user seeing an
error and losing the conversation.
"""

from __future__ import annotations

import time
from typing import Callable

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from . import modes, providers, redact, security
from .personality import JARVIS_IDENTITY, JARVIS_SYSTEM_PROMPT
from .providers import Provider

# Conversation turns (user + assistant messages) kept in context. The system
# prompt is prepended separately and never counted against this.
MAX_HISTORY_MESSAGES = 40
# Past the limit the oldest turns are summarised, and the history is cut
# back to this many so the summarising call is not made on every message.
KEEP_AFTER_SUMMARY = 24
SUMMARY_WORDS = 250
MAX_SUMMARY_CHARS = 2400

# How long a throttled provider is skipped before it's tried again. Long
# enough to clear a per-minute limit, short enough that the user's preferred
# backend comes back on its own within a conversation.
COOLDOWN_SECONDS = 75.0

# Shorter pause for one-off errors (a dropped connection, a 5xx), which are
# far more likely to clear immediately than a rate limit is.
ERROR_COOLDOWN_SECONDS = 20.0


class _NeedsMoreRoom(Exception):
    """The model used its whole budget thinking and never answered.

    Reasoning models spend tokens before they write a word, so a budget
    that suits an ordinary model can produce a completely empty reply.
    Raised internally so the request can be retried with more room.
    """


class Cancelled(Exception):
    """Raised by an on_chunk callback to abandon a stream in progress.

    Distinct from a provider failing: the chain must not try the next
    backend, because the user asked for the whole thing to stop.
    """


class Brain:
    def __init__(self, model: str | None = None):
        self.history: list[dict[str, str]] = []
        self._model_override = model
        self._active: Provider | None = None
        # Which model actually answered, for the status line. Set on every
        # successful call; initialised here so reading it before the first
        # request cannot raise.
        self._last_model: str = ""
        self.mode = modes.DEFAULT
        # Set by code mode; replaces the butler persona entirely.
        self.persona_override: str | None = None
        self.code_mode = False
        # Providers that failed in a way retrying won't fix (bad key, no
        # credit). Skipped for the rest of the session.
        self._dead: set[str] = set()
        # Provider name -> monotonic time it may be tried again.
        self._cooldown: dict[str, float] = {}
        # gpt-5 series rejects `max_tokens`; others reject
        # `max_completion_tokens`. Learned per provider on first failure.
        self._token_param: dict[str, str] = {}
        self._no_temperature: set[str] = set()
        # (provider, model) pairs a mode asked for that never answered. Tried
        # once per session and then skipped: kimi-k3 is listed in NVIDIA's
        # catalogue but does not reply on the free tier, so without this
        # Hyperdrive pays its full 200-second leash on every single message.
        self._slow_targets: set[tuple[str, str]] = set()
        # What earlier, trimmed turns said. Travels in the system prompt.
        self.summary: str = ""

    # --- public ----------------------------------------------------------

    @property
    def model(self) -> str:
        provider = self._active
        if provider is None:
            chain = self._chain()
            if not chain:
                return "none"
            provider = chain[0]
        return self._model_override or providers.model_for(provider)

    def active_label(self) -> str:
        """Which backend is answering — shown in the UI status line."""
        suffix = f" · {self.mode.label}" + (" · Code" if self.code_mode else "")
        if not self._active:
            return "not connected" + suffix
        model = self._last_model or self._model_override or providers.model_for(self._active)
        return f"{self._active.label} · {model}{suffix}"

    def system_prompt(self) -> str:
        """Who JARVIS is, how this mode thinks, and code mode on top.

        The identity block is never dropped. Code mode replaces the *butler*
        persona, not the assistant's sense of self: without this, asking
        "who created you?" in code mode got "I am Mercury, trained by
        Inception" — the model's own identity, leaking straight through.
        """
        if self.persona_override:
            parts = [JARVIS_IDENTITY, self.persona_override]
        else:
            parts = [JARVIS_SYSTEM_PROMPT]
        parts.append(f"## Response mode: {self.mode.label}\n{self.mode.style}")

        if self.summary:
            parts.append(
                "## Earlier in this conversation\n"
                "These turns were condensed to save space. Treat them as what "
                f"was already said:\n{self.summary}"
            )

        # Keep answers in the same language as the window. 4.0 claimed this
        # and did not do it — the edit that was meant to add these lines never
        # landed, and nothing tested for it — so the buttons turned Turkish
        # while the replies stayed English.
        from . import i18n

        instruction = i18n.answer_instruction()
        if instruction:
            parts.append(instruction)
        return "\n\n".join(parts)

    def set_mode(self, name: str):
        """Switch thinking mode. Clears cooldowns so the new mode gets a clean go."""
        self.mode = modes.get(name)
        self._cooldown.clear()
        return self.mode

    # Models trained to be agreeable open with an acknowledgement even when the
    # system prompt forbids it by name — gpt-oss-120b still said "Certainly."
    # every time. Prompting is unreliable here, so code mode trims it.
    _PLEASANTRIES = (
        "certainly", "sure", "of course", "absolutely", "great question",
        "happy to help", "i'd be happy to", "here you go", "no problem",
    )

    @classmethod
    def _strip_pleasantry(cls, text: str) -> str:
        """Drop a leading acknowledgement, keeping everything that follows."""
        stripped = text.lstrip()
        for _ in range(2):  # e.g. "Sure. Certainly, here's..."
            lowered = stripped.lower()
            for word in cls._PLEASANTRIES:
                if not lowered.startswith(word):
                    continue
                rest = stripped[len(word):]
                # Only a real sentence opener, not "Sure enough, the bug was..."
                if rest[:1] not in {".", ",", "!", ":", ""}:
                    continue
                rest = rest[1:].lstrip()
                if not rest:
                    return stripped
                # Re-capitalise whatever now starts the reply.
                stripped = rest[0].upper() + rest[1:] if rest[0].isalpha() else rest
                break
            else:
                break
        return stripped

    def chat(
        self,
        user_message: str,
        extra_context: str | None = None,
        should_commit: Callable[[], bool] | None = None,
        on_chunk: Callable[[str | None], None] | None = None,
    ) -> str:
        """Send a message. `extra_context` is prepended for this request only.

        Addons use it to inject what they know without that scaffolding piling
        up in the history the user sees.

        `should_commit` is asked, once, whether the finished exchange is still
        wanted. Pressing Stop makes it return False: the HTTP call cannot be
        torn down mid-flight, but the answer nobody saw must not end up in the
        history, where it would be saved to disk and quietly sent as context
        with the next question.

        `on_chunk` receives the answer as it arrives. It is called with None
        when a provider fails partway through and the next one is about to
        start, which tells the caller to throw away what it has shown — the
        alternative is two half-answers stitched together on screen. Raising
        Cancelled from it stops the stream.
        """
        sent = f"{extra_context}\n\n{user_message}" if extra_context else user_message
        messages = [
            {"role": "system", "content": self.system_prompt()},
            *self.history,
            {"role": "user", "content": sent},
        ]

        reply, error = self._chat_over_chain(messages, on_chunk=on_chunk)
        if reply is None:
            return error or "No AI provider is configured."

        if should_commit is not None and not should_commit():
            return reply

        # Only record the exchange once we actually have a reply, so a failed
        # call can't leave a dangling user turn poisoning the next request.
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()
        return reply

    def ask_once(
        self,
        prompt: str,
        image_b64: str | None = None,
        targets: tuple[tuple[str, str], ...] = (),
        target_timeout: float | None = None,
    ) -> str:
        """One-off question that never touches conversation history.

        Addons use this so a document summary or a screen description doesn't
        pollute the chat the user is actually having.

        `targets` are (provider, model) pairs to try before the mode's own —
        the coding agent passes its model here. They are tried the way a
        mode's preferred model is: a refusal or a silence skips that model
        for the session and the ordinary chain answers instead.
        """
        if image_b64:
            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
            ]
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": prompt}]

        reply, error = self._chat_over_chain(
            messages, vision=bool(image_b64),
            targets=targets, target_timeout=target_timeout,
        )
        return reply if reply is not None else (error or "No AI provider is configured.")

    def last_answered(self) -> str:
        """'Provider · model' that produced the most recent reply, or ''."""
        if self._active is None or not self._last_model:
            return ""
        return f"{self._active.label} · {self._last_model}"

    # --- provider walking -------------------------------------------------

    def _chain(self, vision: bool = False) -> list[Provider]:
        now = time.monotonic()
        chain = [
            p
            for p in providers.chat_chain()
            if p.name not in self._dead and self._cooldown.get(p.name, 0.0) <= now
        ]
        if vision:
            # A text-only model answers an image with an opaque 400. Skipping
            # is both faster and produces an error the user can act on.
            chain = [p for p in chain if p.vision]
        return chain

    def _chat_over_chain(
        self,
        messages: list[dict],
        vision: bool = False,
        on_chunk: Callable[[str | None], None] | None = None,
        targets: tuple[tuple[str, str], ...] = (),
        target_timeout: float | None = None,
    ) -> tuple[str | None, str | None]:
        # Keys, passwords, emails and phone numbers leave as placeholders and
        # come back filled in. The caller's `messages` — the saved history —
        # is never modified; only the copy that is sent is masked.
        redactor = None
        if redact.enabled():
            redactor = redact.Redactor()
            messages = redactor.mask_messages(messages)
            if redactor.total:
                messages = self._with_note(messages, redact.NOTE)
                security.audit.record("redacted", redactor.describe())
                if on_chunk is not None:
                    raw_chunk = on_chunk

                    def on_chunk(piece, _raw=raw_chunk, _r=redactor):
                        _raw(_r.restore(piece) if piece else piece)
        self.last_redaction = redactor

        chain = self._chain(vision=vision)
        if not chain:
            if vision and self._chain():
                return None, (
                    "None of your configured providers can see images.\n"
                    "Add a free Gemini key for vision: "
                    "https://aistudio.google.com/apikey"
                )
            return None, self._no_provider_message()

        # Deliberately not reordered around whatever answered last. The chain
        # is preference order, and backing off failures is already handled by
        # _dead and _cooldown — so a provider that was briefly throttled comes
        # back to the front on its own instead of the session being stuck on
        # the fallback for good.
        attempts = self._attempts(
            chain, vision=vision, extra=targets, extra_timeout=target_timeout
        )
        problems: list[str] = []
        shown = False
        for provider, model, timeout, is_preferred in attempts:
            # A previous provider may have streamed part of an answer before
            # failing. Clear it before this one starts, or the two get stitched
            # together on screen into something neither model said. Done here,
            # once, rather than in each of the eight failure branches below.
            if shown and on_chunk is not None:
                on_chunk(None)
                shown = False

            # Say what is happening, so a 40-second wait is a visible one.
            # The previous attempt's failure is the last entry in `problems`,
            # so reporting it here covers every failure branch below at once.
            if problems:
                self._status(f"{problems[-1][:80]} — trying {provider.label}…")
            else:
                self._status(f"Asking {provider.label} · {model}"
                             + (f" (up to {int(timeout)}s)" if timeout else "") + "…")

            started = time.monotonic()
            try:
                def chunk(text: str) -> None:
                    nonlocal shown
                    shown = True
                    if on_chunk is not None:
                        on_chunk(text)

                reply = self._complete(
                    provider, messages, model, timeout,
                    on_chunk=chunk if on_chunk is not None else None,
                )
            except Cancelled:
                raise
            except AuthenticationError as exc:
                # A rejected key won't start working mid-session.
                self._dead.add(provider.name)
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue
            except RateLimitError as exc:
                # 429 means two very different things. An exhausted balance is
                # permanent; ordinary throttling clears in seconds, and free
                # tiers throttle routinely — retiring the provider over one
                # would silently push the whole session onto a paid backend.
                if self._is_out_of_credit(exc):
                    self._dead.add(provider.name)
                else:
                    self._cooldown[provider.name] = time.monotonic() + COOLDOWN_SECONDS
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue
            except NotFoundError:
                if is_preferred:
                    # Only this mode's preferred model is missing; the provider
                    # itself is fine and still serves its own default.
                    problems.append(
                        f"{provider.label}: '{model}' is not available to "
                        "this account"
                    )
                    self._slow_targets.add((provider.name, model))
                    continue
                names = providers.list_models(provider)
                hint = f" Available: {', '.join(names[:8])}" if names else ""
                problems.append(
                    f"{provider.label}: model '{model}' not found.{hint}"
                )
                self._dead.add(provider.name)
                continue
            except providers.HttpChatError as exc:
                self._back_off(provider)
                problems.append(f"{provider.label}: {exc}")
                continue
            except (APIConnectionError, APIStatusError, APIError) as exc:
                if is_preferred:
                    # Hyperdrive's model going quiet says nothing about the
                    # provider's ordinary model, which is tried next. Don't
                    # wait on this one again though — one 200-second lesson
                    # per session is enough.
                    self._slow_targets.add((provider.name, model))
                    problems.append(
                        f"{provider.label}: '{model}' did not answer "
                        f"({self._short(exc)})"
                    )
                    continue
                self._back_off(provider)
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue
            except Exception as exc:  # a provider returning junk shouldn't crash us
                self._back_off(provider)
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue

            if reply:
                self._active = provider
                self._last_model = model
                # What failed on the way, so a caller can say why its own
                # choice of model did not answer.
                self.last_problems = list(problems)
                security.audit.record(
                    "answered", f"{provider.label} / {model}",
                    f"{time.monotonic() - started:.1f}s, {self.mode.label}",
                )
                if self.code_mode:
                    reply = self._strip_pleasantry(reply)
                if redactor is not None:
                    reply = redactor.restore(reply)
                return reply, None
            problems.append(f"{provider.label}: empty response")

        detail = "\n".join(f"  - {p}" for p in problems)
        if self.mode.only_providers:
            only = ", ".join(self.mode.only_providers)
            return None, (
                f"{self.mode.label} only uses {only}, and it did not answer.\n"
                f"{detail}\n\n"
                "Switch to Max to let the other providers answer instead."
            )
        return None, (
            f"I couldn't reach any AI provider.\n{detail}\n\n"
            "Add a free key to your .env — no card, no payment:\n"
            "  GEMINI_API_KEY=...  (https://aistudio.google.com/apikey)\n"
            "  GROQ_API_KEY=...    (https://console.groq.com/keys)"
        )

    def _attempts(
        self,
        chain: list[Provider],
        vision: bool = False,
        extra: tuple[tuple[str, str], ...] = (),
        extra_timeout: float | None = None,
    ) -> list[tuple[Provider, str, float | None, bool]]:
        """What to try, in order: the mode's preferred models, then the chain.

        Each entry is (provider, model, timeout, is_preferred). Preferred
        entries are the mode's own choices and are treated more gently on
        failure — a model that never answers should not retire the provider
        that hosts it.
        """
        out: list[tuple[Provider, str, float | None, bool]] = []
        seen: set[tuple[str, str]] = set()

        # A caller's own choice (the coding agent's model) goes first. An
        # opt-in provider is allowed here even though it is not in the
        # chain: naming it for this one job is the opt-in.
        for name, model in extra:
            provider = providers.BY_NAME.get(name)
            if provider is None or not providers.has_key(provider):
                continue
            if provider.name in self._dead or (provider.name, model) in self._slow_targets:
                continue
            if vision and not provider.vision:
                continue
            out.append((provider, model, extra_timeout or self.mode.fallback_timeout, True))
            seen.add((provider.name, model))

        for index, (name, model) in enumerate(modes.targets_for(self.mode)):
            provider = providers.BY_NAME.get(name)
            if provider is None or not providers.has_key(provider):
                continue
            if provider.name in self._dead:
                continue
            if (provider.name, model) in self._slow_targets or (provider.name, model) in seen:
                continue
            if vision and not provider.vision:
                continue
            # The long leash belongs to the first target alone. Giving it to
            # every preferred model turned Hyperdrive's one slow attempt into
            # as many slow attempts as it has targets.
            if index == 0 and self.mode.first_target_timeout:
                timeout = self.mode.first_target_timeout
            else:
                timeout = min(self.mode.timeout, self.mode.fallback_timeout)
            out.append((provider, model, timeout, True))
            seen.add((provider.name, model))

        # Fallbacks get the ordinary timeout, not the mode's headline one.
        fallback = min(self.mode.timeout, self.mode.fallback_timeout)
        if self.mode.only_providers:
            chain = [p for p in chain if p.name in self.mode.only_providers]
        for provider in chain:
            model = self._model_override or providers.model_for(provider)
            if (provider.name, model) in seen:
                continue
            out.append((provider, model, fallback, False))
        return out

    def _complete(
        self,
        provider: Provider,
        messages: list[dict],
        model: str | None = None,
        timeout: float | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        model = model or self._model_override or providers.model_for(provider)
        if provider.transport == "http":
            # Hand-rolled transport, no streaming. The answer arrives whole;
            # hand it over as one chunk so the caller's display path is the
            # same either way.
            text = providers.pollinations_chat(model, messages)
            if on_chunk is not None and text:
                on_chunk(text)
            return text

        token_param = self._token_param.get(provider.name, "max_completion_tokens")

        kwargs: dict = {
            "model": model,
            "messages": messages,
            token_param: self.mode.max_tokens,
        }
        if provider.name not in self._no_temperature:
            kwargs["temperature"] = self.mode.temperature

        # Streaming is decided before the request, not after: asking once and
        # then asking again to stream would send every message twice.
        if on_chunk is not None:
            kwargs["stream"] = True

        client = providers.get_client(provider)
        if timeout is not None:
            # max_retries=0 matters as much as the timeout here. The cached
            # client retries twice, so a model that simply never answers burns
            # three full timeouts — Hyperdrive's 200s budget became 600s.
            client = client.with_options(timeout=timeout, max_retries=0)
        try:
            response = client.chat.completions.create(**kwargs)
        except (APIStatusError, APIError, TypeError) as exc:
            retry = dict(kwargs)
            changed = False
            if self._mentions(exc, "max_tokens", "max_completion_tokens"):
                retry.pop(token_param, None)
                token_param = (
                    "max_tokens"
                    if token_param == "max_completion_tokens"
                    else "max_completion_tokens"
                )
                retry[token_param] = 2048
                self._token_param[provider.name] = token_param
                changed = True
            if self._mentions(exc, "temperature"):
                retry.pop("temperature", None)
                self._no_temperature.add(provider.name)
                changed = True
            if self._mentions(exc, "stream"):
                # A provider that will not stream should still answer.
                retry.pop("stream", None)
                on_chunk = None
                changed = True
            if not changed:
                raise
            response = client.chat.completions.create(**retry)

        # Nothing has been sent to the caller yet, so a retry above could not
        # have left half an answer on screen.
        try:
            return self._read_reply(response, on_chunk)
        except _NeedsMoreRoom:
            pass

        # The model spent its entire budget thinking. Nothing was emitted, so
        # asking again with more room is safe and is usually all it needs.
        roomier = dict(kwargs)
        roomier[token_param] = max(self.mode.max_tokens * 3, 3072)
        try:
            return self._read_reply(
                client.chat.completions.create(**roomier), on_chunk
            )
        except _NeedsMoreRoom:
            return (
                f"{model} used its whole budget reasoning and never got to an "
                "answer. Try a shorter question, or a heavier mode."
            )

    def _read_reply(self, response, on_chunk: Callable[[str], None] | None) -> str:
        """Turn a response — streamed or not — into text."""
        if on_chunk is not None:
            return self._read_stream(response, on_chunk)

        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        content = choices[0].message.content
        if not content:
            if getattr(choices[0], "finish_reason", "") == "length":
                raise _NeedsMoreRoom()
            return ""
        return content.strip()

    @staticmethod
    def _read_stream(response, on_chunk: Callable[[str], None]) -> str:
        """Drain a streaming response, handing each piece to `on_chunk`.

        Cancelled is allowed straight out: the user pressed Stop, and the
        chain must not treat that as this provider failing and try another.
        """
        parts: list[str] = []
        cut_short = False
        for event in response:
            choices = getattr(event, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            piece = getattr(delta, "content", None) if delta else None
            if getattr(choices[0], "finish_reason", "") == "length":
                cut_short = True
            if not piece:
                continue
            parts.append(piece)
            on_chunk(piece)

        text = "".join(parts).strip()
        if not text and cut_short:
            raise _NeedsMoreRoom()
        return text

    # --- helpers ----------------------------------------------------------

    last_redaction = None
    last_problems: list = []

    @staticmethod
    def _with_note(messages: list[dict], note: str) -> list[dict]:
        """Add an instruction to the system message, or to the first turn."""
        out = [dict(m) for m in messages]
        for message in out:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                message["content"] = f"{message['content']}\n\n{note}"
                return out
        for message in out:
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                message["content"] = f"{note}\n\n{message['content']}"
                return out
        return out

    @staticmethod
    def _mentions(exc: Exception, *needles: str) -> bool:
        text = str(getattr(exc, "message", None) or exc).lower()
        if not any(n in text for n in needles):
            return False
        return any(
            word in text
            for word in ("unsupported", "not supported", "unrecognized", "invalid", "does not support")
        )

    def _back_off(self, provider: Provider) -> None:
        """Skip a misbehaving provider briefly, without retiring it.

        Short enough that a blip doesn't cost the user their preferred
        backend, long enough not to re-probe it on every single message.
        """
        self._cooldown[provider.name] = time.monotonic() + ERROR_COOLDOWN_SECONDS

    @staticmethod
    def _is_out_of_credit(exc: Exception) -> bool:
        """Tell an exhausted balance apart from ordinary throttling."""
        text = str(getattr(exc, "message", None) or exc).lower()
        return any(
            marker in text
            for marker in ("insufficient_quota", "billing", "credit", "exceeded your current quota")
        )

    # --- visibility -------------------------------------------------------

    status_callback: Callable[[str], None] | None = None

    def _status(self, text: str) -> None:
        """Tell whoever is listening what the chain is doing. Never raises."""
        callback = self.status_callback
        if callback is None:
            return
        try:
            callback(text)
        except Exception:
            pass

    def health(self) -> list[tuple[str, str]]:
        """(provider label, state) for every configured provider.

        state is 'ok' (answered last), 'ready', 'cooling' (throttled, will be
        retried shortly) or 'dead' (bad key or no credit — skipped this
        session). Read from what the chain has already learned; nothing is
        sent to find out.
        """
        now = time.monotonic()
        out: list[tuple[str, str]] = []
        # The chain, not every keyed provider: an opt-in one that has a key
        # but was never promoted is not something this brain will call, and
        # listing it here as "ready" alongside its "opt-in" line said both.
        for provider in providers.chat_chain():
            if provider.transport == "http":
                continue
            if provider.name in self._dead:
                state = "dead"
            elif self._cooldown.get(provider.name, 0.0) > now:
                state = "cooling"
            elif self._active is provider:
                state = "ok"
            else:
                state = "ready"
            out.append((provider.label, state))
        return out

    def reset_failures(self) -> None:
        """Forget which providers failed — call after keys change.

        A key fixed in Settings is worthless if the provider it belongs to is
        still marked dead from before the fix, so everything learned the hard
        way is dropped here, including models that timed out.
        """
        self._dead.clear()
        self._cooldown.clear()
        self._slow_targets.clear()
        self._active = None

    @staticmethod
    def _short(exc: Exception) -> str:
        text = str(getattr(exc, "message", None) or exc).strip()
        low = text.lower()
        if "insufficient_quota" in low or "credit" in low or "billing" in low:
            return "out of credit"
        if "api key" in low or "unauthorized" in low or "invalid_api_key" in low:
            return "key rejected"
        if "rate" in low and "limit" in low:
            return "rate limited"
        if "has not been priced" in low or "model_price_error" in low:
            # Blueminds' wording for a model it lists but has not switched on.
            return "not switched on by the provider yet"
        return text[:110] or exc.__class__.__name__

    @staticmethod
    def _no_provider_message() -> str:
        return (
            "No AI provider is reachable.\n\n"
            "JARVIS works with no account at all via Pollinations, so this "
            "usually means the connection failed. For a faster, more reliable "
            "brain add one free key to your .env:\n"
            "  GEMINI_API_KEY=...  (https://aistudio.google.com/apikey)\n"
            "  GROQ_API_KEY=...    (https://console.groq.com/keys)"
        )

    def _trim(self) -> None:
        """Keep the history bounded without forgetting how it started.

        Turns used to be dropped outright past the limit, so a long session
        quietly lost its own beginning — the decision made in the first ten
        minutes simply stopped existing. Now the oldest turns are folded into
        a running summary that travels in the system prompt.

        It trims down to KEEP_AFTER_SUMMARY rather than to the limit, so the
        summarising call happens once every eight exchanges instead of on
        every single message.
        """
        if len(self.history) <= MAX_HISTORY_MESSAGES:
            return
        cut = len(self.history) - KEEP_AFTER_SUMMARY
        cut += cut % 2          # stay aligned: the log must start on a user turn
        dropped, self.history = self.history[:cut], self.history[cut:]
        self._fold_into_summary(dropped)

    def _fold_into_summary(self, dropped: list[dict]) -> None:
        transcript = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'JARVIS'}: {m.get('content', '')[:1500]}"
            for m in dropped
        )
        request = [{
            "role": "user",
            "content": (
                "Update the running summary of a conversation. Keep decisions, "
                "facts about the user, names, file names, numbers and anything "
                "still unresolved. Drop pleasantries and anything superseded. "
                f"Under {SUMMARY_WORDS} words, plain prose, no heading.\n\n"
                f"Summary so far:\n{self.summary or '(none yet)'}\n\n"
                f"Earlier exchanges to fold in:\n{transcript}"
            ),
        }]
        try:
            reply, _error = self._chat_over_chain(request)
        except Exception:
            reply = None
        if reply:
            self.summary = reply.strip()[:MAX_SUMMARY_CHARS]
        elif not self.summary.endswith("could not be summarised.)"):
            # Say so rather than pretend: an honest gap beats a fabricated one.
            self.summary = (
                self.summary + "\n(Some earlier turns could not be summarised.)"
            ).strip()

    def clear_history(self) -> None:
        self.history.clear()
        self.summary = ""
