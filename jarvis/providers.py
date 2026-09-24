"""Backend registry for chat, images, and speech.

JARVIS talks the OpenAI wire format to every text backend, so Groq, Gemini and
Pollinations all work through the same SDK with nothing but a different base
URL. One code path covers four providers instead of four bespoke clients.

Ordering is deliberate: free-with-a-free-key first (best quality per zero
pounds), then paid, then the keyless service last. Pollinations needs no
account at all, which makes it the floor JARVIS can always fall back to — so
the app keeps working when a key is missing, wrong, or out of credit.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from openai import OpenAI

from . import net
from .config import get_setting, load_config


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    base_url: str | None          # None = the SDK's own default (OpenAI)
    key_env: str | None           # None = no account needed
    chat_model: str
    free: bool
    signup: str = ""
    stt_model: str | None = None
    notes: str = ""
    # "sdk" speaks through the OpenAI client; "http" is hand-rolled for
    # services the SDK cannot be made to satisfy.
    transport: str = "sdk"
    # Whether this provider's default model accepts images. Sending a picture
    # to one that can't produces an opaque API error, so we skip it instead.
    vision: bool = False
    # A separate model for images, when the chat model cannot see.
    vision_model: str | None = None


# --- chat -----------------------------------------------------------------
# Model names are defaults only; every one is overridable via .env, because
# providers rename and retire models far faster than this app ships releases.

GEMINI = Provider(
    name="gemini",
    label="Google Gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    key_env="GEMINI_API_KEY",
    # A moving alias, deliberately. Pinning a version here went stale between
    # two releases — gemini-2.5-flash was retired for new keys — and a dead
    # default silently demotes the provider on first use.
    chat_model="gemini-flash-latest",
    free=True,
    vision=True,
    signup="https://aistudio.google.com/apikey",
    notes="Free tier, generous daily limit, understands images.",
)

GROQ = Provider(
    name="groq",
    label="Groq",
    base_url="https://api.groq.com/openai/v1",
    key_env="GROQ_API_KEY",
    # Groq retired the llama-3.3 models, which left this 404ing for every
    # user. Ids here are namespaced and must be passed whole.
    chat_model="openai/gpt-oss-120b",
    stt_model="whisper-large-v3-turbo",
    free=True,
    signup="https://console.groq.com/keys",
    notes="Free tier, very fast, also does speech-to-text.",
)

OPENAI = Provider(
    name="openai",
    label="OpenAI",
    base_url=None,
    key_env="OPENAI_API_KEY",
    chat_model="gpt-5-mini",
    stt_model="gpt-4o-mini-transcribe",
    free=False,
    vision=True,
    signup="https://platform.openai.com/api-keys",
    notes="Paid. Highest quality, needs credit on the account.",
)

INCEPTION = Provider(
    name="inception",
    label="Inception Mercury",
    base_url="https://api.inceptionlabs.ai/v1",
    key_env="INCEPTION_API_KEY",
    # Mercury is a diffusion language model rather than an autoregressive one,
    # which is why it answers in about a second. mercury and mercury-coder
    # exist but are paid-tier only; the free tier serves this.
    chat_model="mercury-2.5",
    free=True,
    signup="https://platform.inceptionlabs.ai",
    notes="Free tier, 100M tokens, ~1s replies. Powers Mid mode.",
)

NVIDIA = Provider(
    name="nvidia",
    label="NVIDIA NIM",
    base_url="https://integrate.api.nvidia.com/v1",
    key_env="NVIDIA_API_KEY",
    # Most models NVIDIA lists never answer on the free tier — kimi-k3,
    # deepseek-v4-flash, glm-5.3 and gemma-4 were all still silent after 200
    # seconds. This one replies in about two seconds and keeps its
    # chain-of-thought in a separate field instead of the reply.
    chat_model="nvidia/nemotron-3-super-120b-a12b",
    # Images: the one NIM vision model that answered on the free tier on
    # 2026-09-24 (1.8s). The 90B timed out; three others were 410 Gone.
    # Without it, a busy Gemini left JARVIS unable to see at all.
    vision_model="meta/llama-3.2-11b-vision-instruct",
    free=True,
    signup="https://build.nvidia.com",
    notes="Free tier, fast. Most other NIM models time out.",
)

POLLINATIONS = Provider(
    name="pollinations",
    label="Pollinations",
    base_url="https://text.pollinations.ai/openai",
    key_env=None,
    chat_model="openai",
    free=True,
    transport="http",
    notes="Images only — its free text tier now refuses real prompts.",
)

OPENROUTER = Provider(
    name="openrouter",
    label="OpenRouter",
    base_url="https://openrouter.ai/api/v1",
    key_env="OPENROUTER_API_KEY",
    # Not a model: a router that picks whichever free model is available
    # right now. Every other provider here names a specific model, and this
    # project has lost three of those to retirement — this one cannot be
    # retired out from under it. Free tier: 200 requests a day, no card.
    chat_model="openrouter/free",
    free=True,
    signup="https://openrouter.ai/keys",
    notes="Free, 200/day, no card. Routes to whichever free model is up.",
)

BLUEMINDS = Provider(
    name="blueminds",
    label="Blueminds",
    base_url="https://api.bluesminds.com/v1",
    key_env="BLUEMINDS_API_KEY",
    # A third-party relay rather than a model vendor: it resells access to
    # other companies' models, so every prompt passes through its servers as
    # well as the upstream's. Measured on 2026-09-24: the key was accepted,
    # but gpt-5.5, kimi-k2.5, gemma-4-26b and gpt-oss-20b all timed out at the
    # relay's own gateway (504), and two listed models answered 410 "reached
    # its end of life on 2026-08-26" — its catalogue is a month stale.
    # GLM-5 Turbo, reached through Blueminds' OpenRouter channel, is the
    # user's choice for this key and the coding agent's default. Blueminds
    # has not enabled it yet ("has not been priced by the administrator"),
    # and refuses it instantly, so nothing waits on it in the meantime.
    chat_model="openrouter/z-ai/glm-5-turbo",
    free=False,
    signup="https://api.bluesminds.com/console/token",
    notes="Third-party relay. Runs the coding agent (GLM-5 Turbo) when enabled.",
)

# Every provider JARVIS knows how to talk to.
CHAT_PROVIDERS: tuple[Provider, ...] = (
    GEMINI, GROQ, INCEPTION, NVIDIA, OPENROUTER, OPENAI, POLLINATIONS, BLUEMINDS,
)

# Those tried automatically. Pollinations is excluded: as of August 2026 its
# keyless text tier answers 402 to anything longer than a trivial prompt, so
# leaving it in the chain would burn a request and confuse the error every
# time. It still works for images, and `JARVIS_PROVIDER=pollinations` will
# still pin it for anyone who wants it.
# OpenRouter before OpenAI: free before paid, always.
AUTO_CHAT_PROVIDERS: tuple[Provider, ...] = (
    GEMINI, GROQ, INCEPTION, NVIDIA, OPENROUTER, OPENAI,
)

# Known, keyed, but never tried unless asked for. A provider that takes 90
# seconds to fail would add those 90 seconds to every failover, so an
# unreliable one has to be promoted deliberately:
#     JARVIS_EXTRA_PROVIDERS=blueminds
OPT_IN_PROVIDERS: tuple[Provider, ...] = (BLUEMINDS,)

STT_PROVIDERS: tuple[Provider, ...] = (GROQ, OPENAI)

BY_NAME = {p.name: p for p in CHAT_PROVIDERS}

# Pollinations asks callers to identify themselves; doing so earns a higher
# rate limit than anonymous traffic.
REFERRER = "jarvis-desktop"

# Cloudflare in front of Pollinations blocks requests from clients that don't
# look like a browser, so a bare "Python-urllib" User-Agent gets error 1010.
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/2.2"


def has_key(provider: Provider) -> bool:
    """True when this provider is usable — keyless ones always are."""
    if provider.key_env is None:
        return True
    load_config()
    import os

    return bool(os.getenv(provider.key_env, "").strip())


def key_for(provider: Provider) -> str:
    if provider.key_env is None:
        return "none"  # the SDK insists on a non-empty key
    import os

    load_config()
    return os.getenv(provider.key_env, "").strip() or "none"


def chat_chain() -> list[Provider]:
    """Providers to try, in order, for a chat request.

    `JARVIS_PROVIDER` pins one explicitly; otherwise every configured provider
    is tried in preference order so a dead key falls through to a live one.
    """
    pinned = get_setting("JARVIS_PROVIDER", "auto").lower()
    ordered = list(AUTO_CHAT_PROVIDERS) + _extra_providers()
    if pinned != "auto" and pinned in BY_NAME:
        chosen = BY_NAME[pinned]
        rest = [p for p in ordered if p is not chosen and has_key(p)]
        return [chosen, *rest]
    return [p for p in ordered if has_key(p)]


def _extra_providers() -> list[Provider]:
    """Opt-in providers the user has promoted into the automatic chain.

    They go last: an extra provider is a backstop, and putting an
    unproven one ahead of the free tiers would make it the default.
    """
    from .config import get_setting

    wanted = {
        name.strip().lower()
        for name in get_setting("JARVIS_EXTRA_PROVIDERS", "").split(",")
        if name.strip()
    }
    return [p for p in OPT_IN_PROVIDERS if p.name in wanted]


def keyed_but_idle() -> list[Provider]:
    """Opt-in providers that have a key but are not in the chain.

    /bench measures these too, so you can see when one starts working
    without having to promote it first.
    """
    active = set(id(p) for p in chat_chain())
    return [p for p in OPT_IN_PROVIDERS if has_key(p) and id(p) not in active]


def stt_chain() -> list[Provider]:
    """Providers to try for transcription, honouring JARVIS_STT_PROVIDER.

    A pin that can't be satisfied returns nothing rather than quietly falling
    back: someone who names a free provider should not be billed by a paid one
    because of a typo in a key.
    """
    usable = [p for p in STT_PROVIDERS if has_key(p) and p.stt_model]
    pinned = get_setting("JARVIS_STT_PROVIDER", "auto").lower()
    if pinned in {"auto", "", "local"}:
        return usable
    return [p for p in usable if p.name == pinned]


def model_for(provider: Provider) -> str:
    """Per-provider model override, e.g. JARVIS_GROQ_MODEL."""
    return get_setting(f"JARVIS_{provider.name.upper()}_MODEL", provider.chat_model)


def stt_model_for(provider: Provider) -> str:
    return get_setting(
        f"JARVIS_{provider.name.upper()}_STT_MODEL", provider.stt_model or ""
    )


# --- clients --------------------------------------------------------------

_clients: dict[str, OpenAI] = {}
_lock = threading.Lock()


def get_client(provider: Provider) -> OpenAI:
    """Cached SDK client pointed at `provider`."""
    cached = _clients.get(provider.name)
    if cached is not None:
        return cached

    with _lock:
        if provider.name not in _clients:
            kwargs = {
                "api_key": key_for(provider),
                "timeout": 120.0,
                "max_retries": 1 if provider.key_env is None else 2,
            }
            if provider.base_url:
                kwargs["base_url"] = provider.base_url
            if provider.name == "pollinations":
                kwargs["default_headers"] = {"Referer": REFERRER}
            _clients[provider.name] = OpenAI(**kwargs)
    return _clients[provider.name]


def reset_clients() -> None:
    """Drop cached clients so newly-entered keys take effect."""
    with _lock:
        _clients.clear()


def list_models(provider: Provider, limit: int = 40) -> list[str]:
    """Model ids the provider will actually serve.

    Used to turn an unhelpful 404 into a list the user can pick from — model
    names change often enough that a stale default is the likeliest failure.
    """
    try:
        response = get_client(provider).models.list()
    except Exception:
        return []
    names = []
    for item in getattr(response, "data", []) or []:
        name = getattr(item, "id", "")
        if not name:
            continue
        # Only Gemini's "models/" wrapper is noise. Groq genuinely namespaces
        # its ids ("openai/gpt-oss-120b"), and stripping that produced names
        # that 404 — so this list, which is shown to the user when a model is
        # missing, was handing out ids that could not work.
        if name.startswith("models/"):
            name = name[len("models/"):]
        names.append(name)
    return sorted(set(names))[:limit]


class HttpChatError(RuntimeError):
    """Raised by the hand-rolled transport so Brain can fall through."""


def _fold_system(messages: list[dict]) -> list[dict]:
    """Merge system instructions into the first user turn.

    The anonymous Pollinations tier rejects any request carrying a system
    message, so JARVIS would lose its personality entirely without this.
    """
    system = [
        m["content"]
        for m in messages
        if m.get("role") == "system" and isinstance(m.get("content"), str)
    ]
    rest = [m for m in messages if m.get("role") != "system"]
    if not system:
        return rest

    preamble = "\n\n".join(system)
    if rest and isinstance(rest[0].get("content"), str):
        merged = dict(rest[0])
        merged["content"] = f"{preamble}\n\n{rest[0]['content']}"
        return [merged, *rest[1:]]
    return [{"role": "user", "content": preamble}, *rest]


def pollinations_chat(model: str, messages: list[dict], timeout: int = 90) -> str:
    """Chat through Pollinations without the OpenAI SDK.

    Three quirks force this. The service answers 402 Payment Required to any
    request carrying an Authorization header — which the SDK always sends and
    cannot be talked out of — Cloudflare rejects clients presenting no
    browser-like User-Agent with error 1010, and the anonymous tier also
    refuses any request containing a system message. Anonymous, browser-shaped,
    and system-free is the only combination that answers.
    """
    body = json.dumps(
        {"model": model, "messages": _fold_system(messages)}
    ).encode("utf-8")
    request = urllib.request.Request(
        POLLINATIONS.base_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
            "Referer": REFERRER,
        },
    )

    try:
        with net.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf-8", "replace")
        if exc.code == 429:
            raise HttpChatError("rate limited — wait a few seconds") from None
        if exc.code in (402, 403):
            raise HttpChatError(f"refused the request (HTTP {exc.code})") from None
        raise HttpChatError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise HttpChatError(net.describe_ssl_error(exc) or str(exc)[:120]) from None

    try:
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise HttpChatError("unexpected response shape") from None


def describe() -> list[tuple[str, bool, str]]:
    """(label, configured, note) for each provider — for the UI and self-test."""
    rows = []
    for provider in CHAT_PROVIDERS:
        rows.append((provider.label, has_key(provider), provider.notes))
    return rows
