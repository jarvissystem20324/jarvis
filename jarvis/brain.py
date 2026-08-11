"""LLM integration for JARVIS.

Requests walk the provider chain until one answers. That is what lets the app
survive a missing key or an empty balance: OpenAI going quiet demotes it for
the session and the next backend takes over, rather than the user seeing an
error and losing the conversation.
"""

from __future__ import annotations

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from . import providers
from .personality import JARVIS_SYSTEM_PROMPT
from .providers import Provider

# Conversation turns (user + assistant messages) kept in context. The system
# prompt is prepended separately and never counted against this.
MAX_HISTORY_MESSAGES = 40


class Brain:
    def __init__(self, model: str | None = None):
        self.history: list[dict[str, str]] = []
        self._model_override = model
        self._active: Provider | None = None
        # Providers that failed in a way retrying won't fix (bad key, no
        # credit). Skipped for the rest of the session.
        self._dead: set[str] = set()
        # gpt-5 series rejects `max_tokens`; others reject
        # `max_completion_tokens`. Learned per provider on first failure.
        self._token_param: dict[str, str] = {}
        self._no_temperature: set[str] = set()

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
        if not self._active:
            return "not connected"
        return f"{self._active.label} · {self._model_override or providers.model_for(self._active)}"

    def chat(self, user_message: str, extra_context: str | None = None) -> str:
        """Send a message. `extra_context` is prepended for this request only.

        Addons use it to inject what they know without that scaffolding piling
        up in the history the user sees.
        """
        sent = f"{extra_context}\n\n{user_message}" if extra_context else user_message
        messages = [
            {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
            *self.history,
            {"role": "user", "content": sent},
        ]

        reply, error = self._chat_over_chain(messages)
        if reply is None:
            return error or "No AI provider is configured."

        # Only record the exchange once we actually have a reply, so a failed
        # call can't leave a dangling user turn poisoning the next request.
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()
        return reply

    def ask_once(self, prompt: str, image_b64: str | None = None) -> str:
        """One-off question that never touches conversation history.

        Addons use this so a document summary or a screen description doesn't
        pollute the chat the user is actually having.
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

        reply, error = self._chat_over_chain(messages, vision=bool(image_b64))
        return reply if reply is not None else (error or "No AI provider is configured.")

    # --- provider walking -------------------------------------------------

    def _chain(self) -> list[Provider]:
        return [p for p in providers.chat_chain() if p.name not in self._dead]

    def _chat_over_chain(
        self, messages: list[dict], vision: bool = False
    ) -> tuple[str | None, str | None]:
        chain = self._chain()
        if not chain:
            return None, self._no_provider_message()

        # Whatever answered last time goes first — no point re-probing.
        if self._active and self._active in chain:
            chain = [self._active, *[p for p in chain if p is not self._active]]

        problems: list[str] = []
        for provider in chain:
            try:
                reply = self._complete(provider, messages)
            except (AuthenticationError, RateLimitError) as exc:
                # A bad key or an empty balance won't resolve mid-session.
                self._dead.add(provider.name)
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue
            except NotFoundError:
                names = providers.list_models(provider)
                hint = f" Available: {', '.join(names[:8])}" if names else ""
                problems.append(
                    f"{provider.label}: model "
                    f"'{self._model_override or providers.model_for(provider)}' not found."
                    f"{hint}"
                )
                self._dead.add(provider.name)
                continue
            except providers.HttpChatError as exc:
                problems.append(f"{provider.label}: {exc}")
                continue
            except (APIConnectionError, APIStatusError, APIError) as exc:
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue
            except Exception as exc:  # a provider returning junk shouldn't crash us
                problems.append(f"{provider.label}: {self._short(exc)}")
                continue

            if reply:
                self._active = provider
                return reply, None
            problems.append(f"{provider.label}: empty response")

        detail = "\n".join(f"  - {p}" for p in problems)
        return None, (
            f"I couldn't reach any AI provider.\n{detail}\n\n"
            "Add a free key to your .env — no card, no payment:\n"
            "  GEMINI_API_KEY=...  (https://aistudio.google.com/apikey)\n"
            "  GROQ_API_KEY=...    (https://console.groq.com/keys)"
        )

    def _complete(self, provider: Provider, messages: list[dict]) -> str:
        model = self._model_override or providers.model_for(provider)
        if provider.transport == "http":
            return providers.pollinations_chat(model, messages)

        token_param = self._token_param.get(provider.name, "max_completion_tokens")

        kwargs: dict = {"model": model, "messages": messages, token_param: 2048}
        if provider.name not in self._no_temperature:
            kwargs["temperature"] = 0.7

        client = providers.get_client(provider)
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
            if not changed:
                raise
            response = client.chat.completions.create(**retry)

        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        content = choices[0].message.content
        if not content:
            if getattr(choices[0], "finish_reason", "") == "length":
                return "My response was cut short. Try asking for something shorter."
            return ""
        return content.strip()

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _mentions(exc: Exception, *needles: str) -> bool:
        text = str(getattr(exc, "message", None) or exc).lower()
        if not any(n in text for n in needles):
            return False
        return any(
            word in text
            for word in ("unsupported", "not supported", "unrecognized", "invalid", "does not support")
        )

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
        if len(self.history) > MAX_HISTORY_MESSAGES:
            # Drop oldest turns in pairs so the log always starts on a user message.
            excess = len(self.history) - MAX_HISTORY_MESSAGES
            self.history = self.history[excess + (excess % 2) :]

    def clear_history(self) -> None:
        self.history.clear()
