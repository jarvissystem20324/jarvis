"""10.0 AI helpers: ask three AIs at once, regenerate an answer with another
provider, a debate between two AIs with a judge, picture styles, and the
rewrite / ask-about-it actions the selection assistant uses in any app.

Answers that compare providers are fetched from each provider directly, never
through the fallback chain — otherwise a slow provider's column could quietly
be filled by another one and labelled wrong.
"""

from __future__ import annotations

import concurrent.futures as futures
import re

from .. import providers, security, shield
from ..registry import command, field, split

G = "Chat and AI"

IMAGE_STYLES = {
    "photo": "a realistic photograph, natural light, sharp focus, 35mm",
    "cinematic": "a cinematic film still, dramatic lighting, shallow depth of field, color graded",
    "anime": "anime illustration, clean line art, cel shading, vibrant colors",
    "pixel": "pixel art, 32-bit retro game style, limited palette, crisp pixels",
    "watercolor": "a watercolor painting, soft washes, paper texture",
    "oil": "an oil painting, visible brush strokes, rich colors",
    "sketch": "a pencil sketch, graphite shading, white paper",
    "3d": "a 3D render, soft studio lighting, glossy materials, octane style",
    "comic": "comic book art, bold ink outlines, halftone shading",
    "cyberpunk": "cyberpunk style, neon lights, rain, futuristic city mood",
    "flat": "flat vector illustration, simple shapes, solid colors, minimal",
    "logo": "a clean minimalist logo mark, flat vector, centered, plain background",
    "isometric": "isometric 3D illustration, clean edges, pastel colors",
    "fantasy": "epic fantasy art, painterly, detailed, atmospheric",
    "lowpoly": "low poly 3D art, faceted geometry, soft gradients",
    "claymation": "claymation style, plasticine figures, handmade look",
    "minecraft": "voxel blocky style, cube-based world",
    "neon": "glowing neon line art on a dark background",
}

REWRITES = {
    "fix": "Fix spelling, grammar and punctuation. Keep the meaning, tone and language.",
    "shorter": "Make it about half as long. Keep the key points and the language.",
    "longer": "Expand it a little with useful detail. Keep the tone and language.",
    "formal": "Rewrite it in a polite, formal tone. Same language.",
    "friendly": "Rewrite it in a warm, friendly tone. Same language.",
    "simple": "Rewrite it in plain, simple words a 12-year-old understands. Same language.",
    "bullets": "Turn it into clear bullet points.",
    "english": "Translate it into natural English.",
    "turkish": "Translate it into natural Turkish.",
    "summary": "Summarise it in 2-3 sentences.",
    "reply": "Write a short, polite reply to this message, in its language.",
}


def configured_providers(limit: int = 3, exclude: set[str] | None = None) -> list:
    """Up to `limit` different providers that have keys, best first."""
    seen = set(exclude or ())
    out = []
    for provider in providers.chat_chain():
        if provider.name in seen:
            continue
        seen.add(provider.name)
        out.append(provider)
        if len(out) >= limit:
            break
    return out


def ask_each(jarvis, prompt: str, chosen: list, timeout: int = 60) -> list[dict]:
    def run(provider):
        model = providers.model_for(provider)
        ok, secs, text = jarvis._probe(provider, model, prompt, timeout=timeout)
        return {"provider": provider.label, "name": provider.name, "model": model, "ok": ok, "seconds": secs,
                "text": text.strip()}

    with futures.ThreadPoolExecutor(max_workers=max(1, len(chosen))) as pool:
        return list(pool.map(run, chosen))


def context_prompt(history: list[dict], question: str, turns: int = 6) -> str:
    recent = [m for m in history if m.get("role") in {"user", "assistant"}][-turns:]
    if recent and recent[-1].get("role") == "user" and recent[-1].get("content") == question:
        recent = recent[:-1]
    lines = [f"{m['role'].upper()}: {str(m.get('content'))[:1500]}" for m in recent]
    head = ("The conversation so far:\n" + "\n".join(lines) + "\n\n") if lines else ""
    return f"{head}Answer the user's latest message:\n{question}"


class AIHelp:
    @command("ask3", "askthree", group=G, usage="/ask3 <question>", help="three different AIs answer side by side",
             title="Ask 3 AIs at once", icon="⚖", page="memory",
             fields=(field("question", "long", "Question"),), keywords="compare providers models")
    def ask3_cmd(self, args: str, routed: bool = False):
        question = args.strip()
        if not question:
            return "Usage: /ask3 <question>"
        chosen = configured_providers(3)
        if len(chosen) < 2:
            return "That needs at least two AI providers with keys (Settings → API keys)."
        security.audit.record("ask3", ", ".join(p.label for p in chosen))
        rows = ask_each(self, question, chosen)
        self._last_ask3 = rows
        blocks = [f"⚖ {len(rows)} AIs, same question:"]
        for r in rows:
            head = f"── {r['provider']} · {r['model']} · {r['seconds']:.1f}s"
            blocks.append(f"{head}\n{r['text'] if r['ok'] else '[no answer: ' + r['text'][:120] + ']'}")
        return "\n\n".join(blocks)

    @command("regenerate", "another", group=G, usage="/regenerate [provider]",
             help="the last question answered again by a different AI", title="Regenerate with another AI", icon="↻",
             page="memory", fields=(field("provider", "text", "Provider (blank: the next one)", optional=True),))
    def regenerate_cmd(self, args: str, routed: bool = False):
        history = self.brain.history
        question = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
        if not question:
            return "Ask something first, then /regenerate gets a second answer from another AI."
        wanted = args.strip().lower()
        active = getattr(getattr(self.brain, "_active", None), "name", "")
        options = configured_providers(10, exclude={active} if not wanted else set())
        if wanted:
            options = [p for p in options if wanted in p.name.lower() or wanted in p.label.lower()]
        if not options:
            return "No other provider with a key to ask." if not wanted else f"No configured provider called {wanted}."
        provider = options[0]
        rows = ask_each(self, context_prompt(history, question), [provider], timeout=90)
        r = rows[0]
        if not r["ok"]:
            return f"{r['provider']} didn't answer ({r['text'][:150]})."
        security.audit.record("regenerate", r["provider"])
        return f"↻ {r['provider']} ({r['model']}):\n\n{r['text']}"

    @command("debate", group=G, usage="/debate <topic or statement> | [rounds 1-4]",
             help="two AIs argue for and against, then a judge sums up", title="Debate mode", icon="🎙",
             page="memory", fields=(field("topic", "text", "Statement", "Homework should be banned"),
                                    field("rounds", "choice", "Rounds", "2", ("1", "2", "3", "4"))))
    def debate_cmd(self, args: str, routed: bool = False):
        topic, rounds = split(args, 2)
        if not topic:
            return "Usage: /debate <statement> | 2"
        rounds = max(1, min(4, int(rounds or 2)))
        sides = configured_providers(2)
        transcript: list[tuple[str, str]] = []

        def speak(side: str, provider) -> str:
            so_far = "\n\n".join(f"{who}: {text}" for who, text in transcript[-4:])
            stance = "FOR" if side == "For" else "AGAINST"
            prompt = (f"You are debating {stance} the motion: “{topic}”. "
                      + (f"The debate so far:\n{so_far}\n\nRespond to the other side's last points and add a new one."
                         if so_far else "Give your opening argument.")
                      + " Max 110 words, persuasive, honest, no insults. Answer in the motion's language.")
            if provider is not None:
                ok, _secs, text = self._probe(provider, providers.model_for(provider), prompt, timeout=60)
                if ok:
                    return text.strip()
            return self.brain.ask_once(prompt).strip()

        for _ in range(rounds):
            for side, provider in (("For", sides[0] if sides else None),
                                   ("Against", sides[1] if len(sides) > 1 else (sides[0] if sides else None))):
                transcript.append((side, speak(side, provider)))
        judge = self.brain.ask_once(
            f"You are a fair debate judge. Motion: “{topic}”.\n\n" +
            "\n\n".join(f"{who}: {text}" for who, text in transcript) +
            "\n\nIn 4 short lines: the strongest point on each side, the weakest moment, and who argued better and "
            "why (judge the arguments, not your own opinion).")
        names = [p.label for p in sides] or ["JARVIS"]
        lines = [f"🎙 Debate: “{topic}”  (For: {names[0]} · Against: {names[-1]})", ""]
        for who, text in transcript:
            lines += [f"{'🟢 For' if who == 'For' else '🔴 Against'}:", text, ""]
        lines += ["⚖ Judge:", judge.strip()]
        return "\n".join(lines)

    @command("imagestyle", "styled", group=G, usage="/imagestyle <style> | <prompt>",
             help="a picture in a style: anime, pixel, watercolor, 3d, cinematic, sketch…", title="Image styles",
             icon="🖼", page="memory",
             fields=(field("style", "choice", "Style", "anime", tuple(IMAGE_STYLES)),
                     field("prompt", "long", "What to draw")), keywords="picture art generate")
    def imagestyle_cmd(self, args: str, routed: bool = False):
        style, prompt = split(args, 2)
        style = style.lower().strip()
        if style not in IMAGE_STYLES:
            return "Styles: " + ", ".join(IMAGE_STYLES)
        if not prompt:
            return "Usage: /imagestyle anime | a fox in a rainy Istanbul street"
        return self.generate_image(f"{prompt.strip()}, {IMAGE_STYLES[style]}")

    @command("rewrite", group=G, usage="/rewrite <fix|shorter|longer|formal|friendly|simple|bullets|english|turkish|summary|reply> | <text>",
             help="rewrite any text (Ctrl+Alt+R does it on selected text in any app)", title="Rewrite text",
             icon="✏", page="memory",
             fields=(field("how", "choice", "How", "fix", tuple(REWRITES)), field("text", "long", "Text")))
    def rewrite_cmd(self, args: str, routed: bool = False):
        how, text = split(args, 2)
        how = how.lower().strip()
        instruction = REWRITES.get(how, how)
        if not text.strip():
            return "Usage: /rewrite formal | <text>"
        return self.rewrite_text(text, instruction)

    def rewrite_text(self, text: str, instruction: str) -> str:
        wrapped, _ = shield.wrap(text[:12000], "the text")
        out = self.brain.ask_once(f"{shield.RULE}\n{instruction}\nReturn only the result, no quotes, no comments.\n\n"
                                  f"{wrapped}")
        return re.sub(r"^```\w*\n|\n```$", "", out.strip())

    def ask_about(self, text: str, question: str) -> str:
        wrapped, _ = shield.wrap(text[:12000], "the selected text")
        return self.brain.ask_once(f"{shield.RULE}\nThe user selected this text in another app:\n{wrapped}\n\n"
                                   f"Their question: {question or 'Explain this briefly.'}\nAnswer briefly.").strip()
