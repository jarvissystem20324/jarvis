# Building and shipping the macOS app

## The short version on "macOS shouldn't flag it"

There is no trick for this. macOS decides whether to warn about a downloaded
app based on one thing: whether it is **signed with an Apple Developer ID and
notarised by Apple**. That requires a paid Apple Developer account.

| | What your users see |
| --- | --- |
| **Unsigned** (free) | *"JARVIS can't be opened because Apple cannot check it for malicious software."* They must right-click → Open, then confirm. |
| **Signed + notarised** ($99/yr) | It just opens. No warning. |

Anyone who tells you an unsigned app can avoid that warning is describing a
workaround the *user* performs, not something the developer can switch off.
Ad-hoc signing (`codesign -s -`), which the CI already does, does **not** help
here — it keeps the bundle internally valid, and is mandatory on Apple Silicon
for the app to run at all, but Gatekeeper still refuses an unsigned download.

Notarisation is not an App Store review. Apple does not judge your app; a
service scans the upload for malware and returns a ticket, usually in a few
minutes. There is no approval queue and no content policy to satisfy.

## Option A — ship unsigned (free, works today)

The CI workflow builds this with no setup. Tell your users, once:

> The first time you open JARVIS, **right-click the app and choose Open**, then
> click Open in the dialog. Double-clicking will not work the first time. This
> is macOS being cautious about apps from outside the App Store, and only
> happens once.

If they have already double-clicked and been refused, they can also allow it
under **System Settings → Privacy & Security**, where a button appears for a
few minutes after the attempt.

For a technical audience this is usually acceptable and honest. For a wider
audience it costs you a real fraction of installs.

## Option B — sign and notarise ($99/yr, no warning)

1. Join the [Apple Developer Program](https://developer.apple.com/programs/)
2. In Xcode or the developer portal, create a **Developer ID Application**
   certificate — *not* "Mac App Distribution", which is App-Store-only
3. Export it from Keychain Access as a `.p12` with a password
4. Create an [app-specific password](https://appleid.apple.com) for notarytool
5. Add these as GitHub repository secrets
   (**Settings → Secrets and variables → Actions**):

| Secret | What it is |
| --- | --- |
| `MACOS_CERTIFICATE` | The `.p12`, base64-encoded: `base64 -i cert.p12 \| pbcopy` |
| `MACOS_CERTIFICATE_PWD` | The password you set when exporting it |
| `MACOS_SIGNING_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAM123456)` |
| `APPLE_ID` | Your Apple ID email |
| `APPLE_APP_PASSWORD` | The app-specific password from step 4 |
| `APPLE_TEAM_ID` | Your 10-character Team ID |

The workflow detects these automatically. With them present it signs, notarises
and staples; without them it builds unsigned. Nothing else changes.

## Building

Pushing a tag starting with `v` builds both architectures and attaches them to
that release. You can also run it by hand from the **Actions** tab.

```bash
git tag -a v2.6 -m "JARVIS 2.6" && git push origin v2.6
```

Two builds are produced, because a PyInstaller app only targets the
architecture it was built on:

| File | For |
| --- | --- |
| `JARVIS-macos-arm64.zip` / `.dmg` | Apple Silicon (M1 and later) |
| `JARVIS-macos-x86_64.zip` / `.dmg` | Intel Macs |

Both must be attached, or half your Mac users get something that will not run.

## Wiring macOS into in-app updates

`update.json` carries a per-platform block so a Mac is never handed a `.exe`:

```json
{
  "version": "2.6",
  "url": "https://.../JARVIS.exe",
  "sha256": "<windows digest>",
  "platforms": {
    "windows":     { "url": "https://.../JARVIS.exe",              "sha256": "..." },
    "macos-arm64": { "url": "https://.../JARVIS-macos-arm64.zip",  "sha256": "..." },
    "macos-x86_64":{ "url": "https://.../JARVIS-macos-x86_64.zip", "sha256": "..." }
  }
}
```

The flat `url`/`sha256` stay at the top level so the 2.5 clients already out
there keep working — they only read those fields. Add the macOS entries after
the Mac build finishes; the checksums are in `checksums-<arch>.txt` in the CI
artifacts.

**macOS updates are deliberately not automatic.** On Windows JARVIS swaps its
own EXE. It will not do that on a Mac: an app there is a signed directory, and
rewriting anything inside it invalidates the signature — after which Gatekeeper
refuses to open the app at all, leaving the user worse off than before they
updated. So on macOS the app downloads the update, verifies the checksum,
reveals it in Finder, and asks the user to drag it into Applications. Their
settings, addons and images are untouched, because those live in Application
Support rather than inside the bundle.

## Where the app keeps things

| | Windows | macOS |
| --- | --- | --- |
| Settings | `.env` beside the EXE | `~/Library/Application Support/JARVIS/.env` |
| Addons | `addons\` beside the EXE | `~/Library/Application Support/JARVIS/addons/` |
| Images | `output\images\` | `~/Library/Application Support/JARVIS/output/images/` |

macOS has to differ. A `.app` in `/Applications` is often not user-writable,
and writing inside the bundle would break its signature.

## Permissions macOS will ask for

- **Microphone** — on first use of voice input. The reason string in the
  prompt comes from `Info.plist`.
- **Screen Recording** — the first time `/see` or `/read` runs. macOS shows
  this in System Settings rather than as a prompt, and JARVIS must be
  restarted after granting it.
- **Accessibility** — only if you opt into the global hotkey by setting
  `JARVIS_HOTKEY` in your `.env`. It is off by default on macOS precisely
  because that permission is the one a keylogger asks for, and a fresh install
  should not be requesting it.

## Known gaps

- The `.app` has not been run on real hardware yet — it is built and self-tested
  in CI, but nobody has clicked it. Treat the first build as a beta.
- The global hotkey path on macOS uses `pynput` and is the least-tested piece.
- `pyttsx3` is excluded from the Mac build; speech uses the system `say`
  command instead, which is more reliable there.
