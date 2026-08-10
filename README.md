# JARVIS 2.1

Just A Rather Very Intelligent System — a desktop AI assistant with chat, image
generation, and voice, built on the OpenAI API.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Put your OpenAI key in `.env`, then run:

```bash
python app.py
```

For the terminal version:

```bash
python main.py
```

## Models

Configured in `.env`; defaults live in `jarvis/config.py`.

| Purpose | Default | Setting |
| --- | --- | --- |
| Chat | `gpt-5.4-mini` | `JARVIS_MODEL` |
| Images | `gpt-image-2` | `JARVIS_IMAGE_MODEL` |
| Speech out | `gpt-4o-mini-tts` | `JARVIS_TTS_MODEL` |
| Speech in | `gpt-4o-mini-transcribe` | `JARVIS_STT_MODEL` |
| Voice | `onyx` | `JARVIS_TTS_VOICE` |

`dall-e-3` was retired on 2026-03-04 and is no longer usable.

Image quality defaults to **medium**. `gpt-image-2` runs a four-stage
understand/plan/generate/review pass at `high`, which takes roughly 30–50× as
long — fine for a final render, painful for iterating.

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
| `/help` | List commands |
| `/quit` | Exit |

## Voice

Speech output uses OpenAI TTS streamed as PCM straight to the sound device, with
an offline `pyttsx3` fallback if the API is unreachable. Speech input records
until you stop talking (automatic endpointing) rather than for a fixed window,
then transcribes via OpenAI. Both run off the UI thread.

## Building the EXE and installer

```bash
python build.py
```

Produces two things:

| Output | What it is |
| --- | --- |
| `dist/JARVIS.exe` | The app itself (~45 MB, standalone) |
| `release/JARVIS-Setup.exe` | Installer with the app bundled inside (~62 MB) |

`python build.py --app` or `--setup` builds just one. The installer bundles the
app EXE as a payload, so the app is always built first.

### What the installer does

Per-user install — **no administrator rights required**:

- copies the app to `%LOCALAPPDATA%\JARVIS` (changeable)
- prompts for an OpenAI key and writes `.env` beside the app
- creates Desktop and Start Menu shortcuts
- registers in Add or Remove Programs with a working uninstaller
- runs the app's self-test and reports whether every component loaded

**The installer contains no API key.** The key is typed in at install time and
written only to the local machine, so `JARVIS-Setup.exe` is safe to share.

## Updating without reinstalling

The app updates itself in place. Users keep their `.env`, their settings, and
their generated images — nothing is reinstalled.

**How it works.** JARVIS reads a JSON manifest at `JARVIS_UPDATE_URL`, compares
versions, and if a newer one exists offers it in a dialog with release notes.
On accept it downloads the new EXE, verifies its SHA-256, renames the running
EXE aside, moves the new one into place, and relaunches. The leftover is
deleted on next start. A failed swap rolls back to the original.

**To publish an update via GitHub Releases:**

1. Bump `__version__` in `jarvis/__init__.py`
2. Run `python build.py`. It refuses to produce a release unless the packaged
   app passes its self-test, then writes `release/update.json` with the new
   version and a fresh SHA-256
3. Edit `notes` in `release/update.json` (the `url` is kept between builds)
4. Create a GitHub release tagged `v<version>` and attach **both**
   `release/JARVIS.exe` and `release/update.json`

Full walkthrough, including repo setup and tagging: [PUBLISHING.md](PUBLISHING.md)

Because the URLs use `/releases/latest/download/`, every future release is
picked up automatically — you never touch the URL again.

Manifest format:

```json
{
  "version": "2.1",
  "url": "https://example.com/JARVIS.exe",
  "sha256": "<hex digest of that exact file>",
  "notes": "What changed"
}
```

Any static host works — GitHub Releases, S3, a plain web server. With GitHub,
`https://github.com/<user>/<repo>/releases/latest/download/update.json` always
points at the newest release.

**Safety rules the updater enforces:** manifest and download URLs must be
`https`; a valid 64-character SHA-256 is mandatory (a manifest without one is
refused outright); and a checksum mismatch aborts the update and deletes the
download. This is what stops a tampered or corrupted binary from replacing the
app.

To bake the update URL into installers you ship, set `JARVIS_UPDATE_URL` in
your environment before running `python build.py`.

### Troubleshooting an install

```bash
JARVIS.exe --selftest
```

Writes `jarvis-selftest.txt` next to the EXE listing which subsystems loaded
(audio devices, TTS, SDK, key, models). Any line starting `[FAIL]` is the
problem. Useful because the app is a windowed build with no console.

## Layout

```
jarvis/
  assistant.py    orchestrator, command routing
  brain.py        chat completions
  images.py       image generation
  voice.py        TTS + STT
  tools.py        offline built-in commands
  personality.py  system prompt
  config.py       paths, .env, model settings
  client.py       shared OpenAI client
ui/app.py         CustomTkinter desktop UI
app.py            GUI entry point
main.py           CLI entry point
```
