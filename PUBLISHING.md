# Publishing JARVIS releases

How to get the project onto GitHub and ship updates that installed copies pick
up automatically.

---

## 1. Naming the repository

Name it **`jarvis`** — not `jarvis-2.0`.

The repo holds every future version (2.1, 2.2, 3.0...), so a version in the
name goes stale immediately. The local folder can stay `jarvis-2.0`; the repo
name is independent.

The name has to match the URL already configured in `.env`:

```
https://github.com/jarvissystem20324/jarvis/releases/latest/download/update.json
```

If you pick a different name, change it in three places: `.env`,
`.env.example`, and `release/update.json`.

**Owner + name must be exact** — GitHub URLs are case-insensitive for owners
but the repo path must otherwise match, and a typo means every update check
silently fails with a 404.

---

## 2. Put the project under git

From the project folder:

```bash
git init -b main
```

```bash
git add -A
```

### Before you commit, confirm your API key is not staged

This is the one step you must not skip. `.env` holds your OpenAI key.

```bash
git status --short
```

`.env` must **not** appear in that list. If it does, stop and fix `.gitignore`
before continuing. To be certain:

```bash
git check-ignore -v .env
```

That should print a line pointing at `.gitignore` — proof it is excluded.

Then commit:

```bash
git commit -m "JARVIS 2.1"
```

### What is deliberately not in the repo

`.gitignore` excludes `venv/`, `build/`, `dist/`, `release/`, `output/`, and
`.env`. The built EXEs are **release assets**, not repo files — you attach them
to a Release in step 4. Don't be surprised when `release/JARVIS.exe` isn't in
the repo; that's correct.

---

## 3. Create the repo on GitHub and push

Create an **empty** repo at <https://github.com/new> named `jarvis`. Do not let
GitHub add a README, .gitignore, or licence — that creates a commit that
conflicts with your first push.

Then:

```bash
git remote add origin https://github.com/jarvissystem20324/jarvis.git
```

```bash
git push -u origin main
```

---

## 4. Tag and publish version 2.1

### The tag

Tag format is **`v` + the version**, matching `__version__` in
`jarvis/__init__.py`:

| `__version__` | git tag | manifest `version` |
| --- | --- | --- |
| `2.1` | `v2.1` | `2.1` |
| `2.2` | `v2.2` | `2.2` |

```bash
git tag -a v2.1 -m "JARVIS 2.1"
```

```bash
git push origin v2.1
```

**The tag itself does not trigger updates.** The updater only reads
`update.json` and compares its `version` against the running app. The tag is a
label so you can find the source that produced a build. Keeping them identical
is what stops you shipping a manifest that claims 2.2 from code that says 2.1.

### The release

Go to **Releases → Draft a new release**, choose the existing tag `v2.1`, then
attach **both** files from your `release/` folder:

- `JARVIS.exe`
- `update.json`

Optionally also attach `JARVIS-Setup.exe` for new users.

Three things that will silently break updates if you get them wrong:

1. **Filenames must be exactly `JARVIS.exe` and `update.json`.** The URL
   hardcodes them. GitHub renames files with duplicate names by appending `.1`.
2. **Do not tick "Set as a pre-release".** The `/releases/latest/` path skips
   pre-releases, so the update would never be offered.
3. **Attach `update.json` itself.** It's easy to upload only the EXE and wonder
   why nothing updates.

Publish the release.

---

## 5. Point the app at it

Already done — `.env` is set to your account:

```
JARVIS_UPDATE_URL=https://github.com/jarvissystem20324/jarvis/releases/latest/download/update.json
```

To bake this into installers you hand out, set it in your environment before
building:

```bash
set JARVIS_UPDATE_URL=https://github.com/jarvissystem20324/jarvis/releases/latest/download/update.json
```

Then `python build.py`. The installer writes it into every install's `.env`.

Verify with **Check for Updates** in the sidebar. On 2.1 with 2.1 published you
should get "You're on the latest version."

---

## 6. Shipping every future update

Once the URL is set you never touch it again.

1. Make your changes
2. Bump `__version__` in `jarvis/__init__.py` (e.g. `2.2`)
3. `python build.py` — refuses to release unless the packaged app passes its
   self-test, then writes a fresh `release/update.json` with the new version
   and SHA-256
4. Edit `notes` in `release/update.json` (the `url` carries over between builds)
5. `git commit -am "JARVIS 2.2"` then `git tag -a v2.2 -m "JARVIS 2.2"` and
   `git push --follow-tags`
6. Draft a release on tag `v2.2`, attach `JARVIS.exe` and `update.json`, publish

Every installed copy offers the update on next launch.

---

## Optional: releases from the terminal

Installing the GitHub CLI turns step 4 into one command:

```bash
winget install --id GitHub.cli
```

Then, after `gh auth login`:

```bash
gh release create v2.2 release/JARVIS.exe release/update.json --title "JARVIS 2.2" --notes "What changed"
```

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| "Could not reach the update server" | Wrong username or repo name — the URL 404s |
| "The update manifest is not valid JSON" | You linked the GitHub *page* instead of the raw asset, and got HTML |
| Update never offered | Release marked pre-release, or manifest `version` isn't higher than the installed one |
| "Checksum mismatch" | `update.json` and `JARVIS.exe` came from different builds — rebuild and re-upload both together |
| Nothing happens on Check for Updates | `JARVIS_UPDATE_URL` is blank in that install's `.env` |
| Works for you, not for installed copies | You built the installer without `JARVIS_UPDATE_URL` set in your environment — see step 5 |
