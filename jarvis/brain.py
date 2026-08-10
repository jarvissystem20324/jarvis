"""LLM integration for JARVIS."""

from __future__ import annotations

from openai import APIError, APIConnectionError, AuthenticationError, RateLimitError

from .client import get_client, rate_limit_message
from .config import get_chat_model
from .personality import JARVIS_SYSTEM_PROMPT

# Conversation turns (user + assistant messages) kept in context. The system
# prompt is prepended separately and never counted against this.
MAX_HISTORY_MESSAGES = 40


class Brain:
    def __init__(self, model: str | None = None):
        self.model = model or get_chat_model()
        self.history: list[dict[str, str]] = []
        # gpt-5 series rejects `max_tokens`; older models reject
        # `max_completion_tokens`. Detected on first failure, then remembered.
        self._token_param = "max_completion_tokens"

    def chat(self, user_message: str) -> str:
        """Send a message and return the reply. History is only committed on success."""
        messages = [
            {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
            *self.history,
            {"role": "user", "content": user_message},
        ]

        try:
            reply = self._complete(messages)
        except AuthenticationError:
            return "Authentication failed. Check OPENAI_API_KEY in your .env file."
        except RateLimitError as exc:
            return rate_limit_message(exc)
        except APIConnectionError:
            return "I can't reach OpenAI. Check your internet connection."
        except APIError as exc:
            return f"API error: {getattr(exc, 'message', None) or exc}"

        # Only record the exchange once we actually have a reply, so a failed
        # call can't leave a dangling user turn poisoning the next request.
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()
        return reply

    def _complete(self, messages: list[dict[str, str]]) -> str:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            self._token_param: 2048,
        }

        try:
            response = get_client().chat.completions.create(**kwargs)
        except (APIError, TypeError) as exc:
            if not self._is_bad_token_param(exc):
                raise
            # Swap to the other spelling and retry once.
            kwargs.pop(self._token_param)
            self._token_param = (
                "max_tokens"
                if self._token_param == "max_completion_tokens"
                else "max_completion_tokens"
            )
            kwargs[self._token_param] = 2048
            response = get_client().chat.completions.create(**kwargs)

        if not response.choices:
            return "I received an empty response. Please try again."
        content = response.choices[0].message.content
        if not content:
            # Hit the token ceiling before producing visible text.
            if response.choices[0].finish_reason == "length":
                return "My response was cut short. Try asking for something shorter."
            return "I received an empty response. Please try again."
        return content.strip()

    @staticmethod
    def _is_bad_token_param(exc: Exception) -> bool:
        text = str(getattr(exc, "message", None) or exc).lower()
        return ("max_tokens" in text or "max_completion_tokens" in text) and (
            "unsupported" in text or "not supported" in text or "unrecognized" in text
        )

    def _trim(self) -> None:
        if len(self.history) > MAX_HISTORY_MESSAGES:
            # Drop oldest turns in pairs so the log always starts on a user message.
            excess = len(self.history) - MAX_HISTORY_MESSAGES
            self.history = self.history[excess + (excess % 2) :]

    def clear_history(self) -> None:
        self.history.clear()
