# JARVIS 2.6

Just A Rather Very Intelligent System — a desktop AI assistant with chat, image
generation, voice, and an addon system.

**Runs without paying for anything.** Images generate with no account at all.
Chat and speech-to-text need one free API key — a free account, no card.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then put **one** free key in `.env`:

| Provider | Get a key | Free? |
| --- | --- | --- |
| Google Gemini | <https://aistudio.google.com/apikey> | Yes — best quality, sees images |
| Groq | <https://console.groq.com/keys> | Yes — fastest, also does speech-to-text |

```bash
python app.py
```

For the terminal version:

```bash
python main.py
```

## What each part costs

| Capability | Free option | Needs a key? |
| --- | --- | --- |
| **Images** | Pollinations (Flux) | No — works out of the box |
| **Chat** | Gemini or Groq free tier | A free key |
| **Speech out** | Built-in Windows voices | No |
| **Speech in** | Groq Whisper, or local faster-whisper | A free key, or nothing if local |

Set `JARVIS_PROVIDER` to pin one backend, or leave it `auto` to try each in
turn — Gemini, then Groq, then OpenAI. A key that gets rejected or runs out of
credit is dropped for the session and the next provider takes over, so one dead
key doesn't take the app down.

OpenAI still works and is still the best quality, but it is now strictly
optional. `JARVIS_IMAGE_PROVIDER=auto` deliberately means *free*: having an
OpenAI key on file isn't consent to bill it for every image. Set it to `openai`
to opt in.

### A note on Pollinations

Its image API is genuinely free and needs no account. Its free **text** tier,
as of August 2026, returns `402 Payment Required` for anything longer than a
trivial prompt, so it can't drive the chat — which is why chat needs one of the
free keys above. `JARVIS_PROVIDER=pollinations` still pins it if you want it.

## Commands

| Command | Description |
| --- | --- |
| `/image <prompt>` | Generate an image |
| `/time`, `/date` | Current time / date |
| `/system` | System information |
| `/open <url>` | Open a URL |
| `/search <query>` | Web search |
| `/run <cmd>` | Run a whitelisted read-only command |
| `/voice` | Toggle voice mode |
| `/clear` | Clear conversation history |
| `/addons` | List installed addons |
| `/help` | List commands, including addon ones |
| `/quit` | Exit |

### From the bundled addons

| Command | Description |
| --- | --- |
| `/doc <path>` | Open a PDF, DOCX, or text file and ask questions about it |
| `/summary` | Summarise the open document |
| `/docclose` | Close it |
| `/see [question]` | Screenshot the screen and describe it |
| `/read` | Transcribe the text currently on screen |
| `/remember <fact>` | Store a fact permanently |
| `/memories`, `/forget <n\|all>` | List / delete stored facts |
| `/hotkey` | Show the global summon shortcut |

`/see` and `/read` need a provider that accepts images — Gemini or OpenAI.
Groq's text models don't.

## Addons

Addons are single `.py` files in the `addons/` folder next to the app. They're
loaded at startup; a broken one is reported and skipped rather than taking the
app down. The four that ship are ordinary addons with no special privileges —
read them as worked examples.

```python
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
```

Drop that in `addons/hello.py`, restart, and `/hello` works.

An addon can also shape the conversation itself:

- `enrich_prompt(ctx, text)` — return context to prepend to the user's next
  message. This is how `/remember` makes JARVIS recall things and how an open
  document gets consulted.
- `on_reply(ctx, user_text, reply)` — observe a completed exchange.
- `ctx.ask(prompt, image_b64=...)` — ask the model a one-off question that never
  enters the chat history.
- `ctx.store("name.json")` — a file to keep your addon's state in.

**Addons are ordinary Python and run with JARVIS's full privileges.** Treat one
you didn't write exactly as you'd treat any other program you're about to run.
The loader only ever reads the local folder — it never downloads anything.

## Voice

Speech output uses OpenAI TTS when a paid key is present and otherwise the
built-in Windows voices, so it always works offline. Speech input records until
you stop talking (automatic endpointing) rather than for a fixed window, then
transcribes through Groq's Whisper — or entirely on your machine if you install
faster-whisper:

```bash
pip install faster-whisper
```

Set `JARVIS_STT_PROVIDER=local` to force offline transcription. The model
(~145 MB for `base`) downloads once on first use.

## macOS

JARVIS runs on macOS with the same features. The `.app` is built by CI on real
Mac hardware, because PyInstaller cannot cross-compile — a Windows machine
cannot produce a Mac app.

```bash
git tag -a v2.6 -m "JARVIS 2.6" && git push origin v2.6
```

That builds `JARVIS-macos-arm64` (Apple Silicon) and `JARVIS-macos-x86_64`
(Intel) and attaches both to the release.

**On first launch, right-click the app and choose Open**, then confirm. macOS
warns about apps it cannot verify, and double-clicking will not get past it.
This stops entirely once the app is signed and notarised with a paid Apple
Developer account — see [PUBLISHING-MAC.md](PUBLISHING-MAC.md), which covers
what that costs and how to set it up.

Differences from Windows:

| | Windows | macOS |
| --- | --- | --- |
| Settings, addons, images | beside the EXE | `~/Library/Application Support/JARVIS/` |
| Speech output | pyttsx3 (SAPI) | the system `say` command |
| Global hotkey | on by default | off unless you set `JARVIS_HOTKEY` |
| Updates | replaces itself | downloads, then you drag it to Applications |

The hotkey is off by default on macOS because monitoring keys system-wide needs
Accessibility permission — the one a keylogger asks for — and a fresh install
should not be demanding it. Updates are manual there because rewriting anything
inside a signed `.app` invalidates its signature, after which macOS refuses to
open it at all.

## Building the EXE and installer

```bash
python build.py
```

| Output | What it is |
| --- | --- |
| `dist/JARVIS.exe` | The app itself (~45 MB, standalone) |
| `release/JARVIS-Setup.exe` | Installer with the app bundled inside (~63 MB) |

`python build.py --app` or `--setup` builds just one. The build **runs the
packaged app's self-test and refuses to produce a release if it fails** — a
windowed build reports nothing when it dies, so without that gate a broken EXE
sails straight into `release/` and out to users.

The bundled addons travel inside the EXE and are copied out beside it on first
run, so they're editable. An addon you delete stays deleted across updates.

### What the installer does

Per-user install — **no administrator rights required**:

- copies the app to `%LOCALAPPDATA%\JARVIS` (changeable)
- prompts for an API key and writes `.env` beside the app
- creates Desktop and Start Menu shortcuts
- registers in Add or Remove Programs with a working uninstaller
- runs the app's self-test and reports whether every component loaded

**The installer contains no API key.** The key is typed in at install time and
written only to the local machine, so `JARVIS-Setup.exe` is safe to share.

## Updating without reinstalling

The app updates itself in place. Users keep their `.env`, their settings, their
addons, and their generated images — nothing is reinstalled.

**How it works.** JARVIS reads a JSON manifest at `JARVIS_UPDATE_URL`, compares
versions, and if a newer one exists offers it in a dialog with release notes.
On accept it downloads the new EXE, verifies its SHA-256, renames the running
EXE aside, moves the new one into place, and relaunches. The leftover is
deleted on next start. A failed swap rolls back to the original.

**Safety rules the updater enforces:** manifest and download URLs must be
`https`; a valid 64-character SHA-256 is mandatory (a manifest without one is
refused outright); and a checksum mismatch aborts the update and deletes the
download. This is what stops a tampered or corrupted binary from replacing the
app.

Full publishing walkthrough — repo setup, tagging, releases:
[PUBLISHING.md](PUBLISHING.md)

### Troubleshooting an install

```bash
JARVIS.exe --selftest
```

Writes `jarvis-selftest.txt` next to the EXE listing which subsystems loaded
(audio devices, providers, addons, models). Any line starting `[FAIL]` is the
problem. Useful because the app is a windowed build with no console.

## Layout

```
jarvis/
  assistant.py    orchestrator, command routing
  providers.py    chat/image/speech backends and fallback order
  brain.py        chat completions across providers
  images.py       image generation (free and paid)
  voice.py        TTS + STT
  addons.py       addon loader and the addon API
  tools.py        offline built-in commands
  personality.py  system prompt
  config.py       paths, .env, model settings
  client.py       OpenAI-specific client shim
addons/
  document_qa.py  PDF/DOCX/text Q&A
  screen_vision.py  screenshot and describe
  memory.py       facts that persist across restarts
  hotkey.py       global summon shortcut
ui/app.py         CustomTkinter desktop UI
app.py            GUI entry point
main.py           CLI entry point
```
