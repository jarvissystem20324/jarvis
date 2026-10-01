"""8.0 — Security tools: password strength and breach checks, phishing links,
file hashes, file encryption, shredding, camera/mic use, 2FA codes, Wi-Fi
safety and a suspicious-process scan.

Secrets never enter the conversation. Passwords, 2FA secrets and encryption
passphrases are typed into a hidden box the window opens (see SECRET in
ui/app.py), go straight to these functions, and are neither shown, logged,
saved in the chat nor sent to a model. The breach check sends only the first
five characters of the password's SHA-1 (Have I Been Pwned's k-anonymity
range API), never the password.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
import re
import secrets
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from . import kit, net, security
from .registry import command

G = "Security"
TOTP = kit.Store("totp.json", {})
COMMON = set("""123456 123456789 12345678 password qwerty 12345 1234567 111111 1234567890 123123 abc123 1234 password1
iloveyou 1q2w3e4r 000000 qwerty123 zaq12wsx dragon sunshine princess letmein 654321 monkey 27653 1qaz2wsx 123321
qwertyuiop superman asdfghjkl 666666 football baseball welcome admin passw0rd master hello freedom whatever login
trustno1 starwars 121212 shadow michael jennifer jordan23 hunter2 galatasaray fenerbahce besiktas trabzonspor
istanbul ankara turkiye türkiye sifre şifre parola 123qwe asdasd qweasd 112233 159753 147258 1q2w3e qazwsx""".split())
KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890", "qwertzuiop", "azertyuiop"]
SECRET_HINT = "I'll ask for it in a hidden box so it never lands in the chat: type /{name} on its own and press Enter."


# --- passwords -------------------------------------------------------------------------------

def password_strength(password: str) -> dict:
    """Rough guess entropy with the common weaknesses taken off. No network."""
    lower = password.lower()
    pool = sum(size for test, size in ((r"[a-z]", 26), (r"[A-Z]", 26), (r"\d", 10), (r"[^\w]", 33),
                                       (r"[çğıöşüÇĞİÖŞÜ]", 12)) if re.search(test, password))
    bits = len(password) * math.log2(pool or 1)
    problems = []
    if lower in COMMON or re.sub(r"\d+$", "", lower) in COMMON:
        bits, problems = min(bits, 10), problems + ["it's one of the most common passwords"]
    if len(password) < 12:
        problems.append("it's shorter than 12 characters")
    if re.search(r"(.)\1{2,}", password):
        bits -= 10
        problems.append("it repeats a character")
    for row in KEYBOARD_ROWS:
        for n in range(4, len(row) + 1):
            if any(row[i:i + n] in lower or row[i:i + n][::-1] in lower for i in range(len(row) - n + 1)):
                bits -= 4 * n
                problems.append("it contains a keyboard run") if "it contains a keyboard run" not in problems else None
                break
    if re.search(r"(19|20)\d{2}", password):
        bits -= 8
        problems.append("it contains a year")
    if re.fullmatch(r"[a-zA-Zçğıöşü]+\d{1,4}[^\w]?", password):
        bits -= 12
        problems.append("it's a word followed by a number — the first pattern crackers try")
    if pool <= 10:
        problems.append("it's only digits")
    bits = max(0.0, bits)
    seconds = 2 ** bits / 1e10                    # an offline attack on a fast hash
    verdict = ("very weak", "weak", "fair", "strong", "very strong")[
        0 if bits < 28 else 1 if bits < 40 else 2 if bits < 60 else 3 if bits < 80 else 4]
    return {"bits": bits, "seconds": seconds, "verdict": verdict, "problems": problems}


def crack_time(seconds: float) -> str:
    for limit, unit in ((60, "seconds"), (3600, "minutes"), (86400, "hours"), (86400 * 365, "days"), (86400 * 365 * 100, "years")):
        if seconds < limit:
            divisor = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "years": 86400 * 365}[unit]
            return "instantly" if seconds < 1 else f"about {seconds / divisor:,.0f} {unit}"
    return "centuries"


def pwned_count(password: str) -> int:
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    request = urllib.request.Request(f"https://api.pwnedpasswords.com/range/{prefix}",
                                     headers={"User-Agent": "JARVIS-desktop", "Add-Padding": "true"})
    with net.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    for line in body.splitlines():
        tail, _, count = line.partition(":")
        if tail.strip() == suffix:
            return int(count)
    return 0


# --- links ----------------------------------------------------------------------------------------

BRANDS = ["google", "gmail", "paypal", "apple", "icloud", "microsoft", "outlook", "office", "amazon", "facebook", "instagram",
          "whatsapp", "netflix", "spotify", "steam", "discord", "binance", "garanti", "akbank", "isbank", "ziraat",
          "yapikredi", "halkbank", "vakifbank", "enpara", "papara", "turkiye", "edevlet", "hepsiburada", "trendyol",
          "ptt", "yurtici", "aras", "mng", "turkcell", "vodafone", "turktelekom", "sahibinden", "github", "linkedin"]
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly", "rb.gy", "shorturl.at",
              "t.ly", "tiny.cc", "s.id", "rebrand.ly"}
RISKY_TLDS = {"zip", "mov", "xyz", "top", "click", "icu", "gq", "tk", "ml", "cf", "ga", "work", "rest", "cam", "monster",
              "quest", "cfd", "sbs", "lol", "buzz", "shop", "live", "support"}


def _distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def link_risks(url: str) -> tuple[int, list[str], str]:
    """(risk score 0-10, reasons, registered domain) from the URL alone."""
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "http://" + url
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    reasons, score = [], 0
    labels = host.split(".")
    registered = ".".join(labels[-3:]) if len(labels) > 2 and labels[-2] in {"com", "co", "gov", "org", "net", "edu", "gen", "bel"} else ".".join(labels[-2:])
    name = registered.split(".")[0]
    if parts.scheme == "http":
        score, reasons = score + 1, reasons + ["it isn't encrypted (http, not https)"]
    if re.fullmatch(r"[\d.]+|\[[0-9a-f:]+\]", host):
        score, reasons = score + 3, reasons + ["it points at a bare IP address, not a name"]
    if "xn--" in host:
        score, reasons = score + 3, reasons + ["it uses look-alike international letters (punycode)"]
    if "@" in parts.netloc:
        score, reasons = score + 3, reasons + ["it hides the real address after an '@'"]
    if host in SHORTENERS:
        score, reasons = score + 2, reasons + ["it's a link shortener — the real destination is hidden"]
    if labels and labels[-1] in RISKY_TLDS:
        score, reasons = score + 2, reasons + [f"'.{labels[-1]}' domains are common in scams"]
    if len(labels) > 4:
        score, reasons = score + 1, reasons + ["it has an unusual number of sub-domains"]
    flat = name.replace("-", "")
    for brand in BRANDS:
        if brand in host.replace("-", "").replace(".", "") and flat != brand and brand not in {"ptt", "aras", "mng"}:
            if flat.startswith(brand) or brand in ".".join(labels[:-2]):
                score, reasons = score + 3, reasons + [f"it mentions {brand} but the site is really {registered}"]
                break
        if flat != brand and 0 < _distance(flat, brand) <= 2 and len(brand) > 4:
            score, reasons = score + 4, reasons + [f"'{name}' looks like '{brand}' with letters changed"]
            break
    if re.search(r"login|signin|verify|verification|secure|account|update|wallet|bonus|gift|prize|kazan|odul|ödül|iade|ceza",
                 parts.path + parts.query, re.I):
        score, reasons = score + 1, reasons + ["it asks for a login, verification or a prize — typical bait"]
    if parts.port and parts.port not in (80, 443):
        score, reasons = score + 1, reasons + [f"it uses an unusual port ({parts.port})"]
    if len(url) > 160:
        score, reasons = score + 1, reasons + ["it's unusually long"]
    return min(score, 10), reasons, registered


def redirect_target(url: str) -> str:
    """Where a link (e.g. a shortener) leads, without opening the page."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=net.ssl_context()))
    try:
        response = opener.open(urllib.request.Request(url, method="HEAD", headers={"User-Agent": net.DEFAULT_USER_AGENT}), timeout=10)
        return response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("Location", "") if exc.code in (301, 302, 303, 307, 308) else ""
    except Exception:
        return ""


# --- files ---------------------------------------------------------------------------------------

MAGIC = b"JENC1"


def file_hashes(path: Path) -> dict[str, str]:
    hashes = {name: hashlib.new(name) for name in ("md5", "sha1", "sha256")}
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            for h in hashes.values():
                h.update(block)
    return {name: h.hexdigest() for name, h in hashes.items()}


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def encrypt_file(path: Path, password: str) -> Path:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(16), os.urandom(12)
    data = path.read_bytes()
    name = path.name.encode("utf-8")
    sealed = AESGCM(_key(password, salt)).encrypt(nonce, struct.pack(">H", len(name)) + name + data, MAGIC)
    out = path.with_name(path.name + ".jenc")
    out.write_bytes(MAGIC + salt + nonce + sealed)
    return out


def decrypt_file(path: Path, password: str) -> Path:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        raise ValueError("That isn't a file JARVIS encrypted.")
    salt, nonce, sealed = blob[5:21], blob[21:33], blob[33:]
    try:
        plain = AESGCM(_key(password, salt)).decrypt(nonce, sealed, MAGIC)
    except InvalidTag:
        raise ValueError("Wrong password (or the file was changed).") from None
    length = struct.unpack(">H", plain[:2])[0]
    name = plain[2:2 + length].decode("utf-8")
    out = path.with_name(name)
    if out.exists():
        out = path.with_name(f"{Path(name).stem} (decrypted){Path(name).suffix}")
    out.write_bytes(plain[2 + length:])
    return out


def shred(path: Path) -> None:
    size = path.stat().st_size
    with path.open("r+b") as handle:
        remaining = size
        while remaining > 0:
            chunk = min(remaining, 1 << 20)
            handle.write(os.urandom(chunk))
            remaining -= chunk
        handle.flush()
        os.fsync(handle.fileno())
    scrambled = path.with_name(secrets.token_hex(8))
    path.rename(scrambled)
    scrambled.unlink()


# --- 2FA codes ------------------------------------------------------------------------------------

def parse_secret(text: str) -> dict:
    """A base32 secret, or an otpauth:// URI from a QR code."""
    text = text.strip()
    if text.lower().startswith("otpauth://"):
        parts = urllib.parse.urlparse(text)
        query = dict(urllib.parse.parse_qsl(parts.query))
        return {"secret": query.get("secret", ""), "digits": int(query.get("digits", 6)),
                "period": int(query.get("period", 30)), "algorithm": query.get("algorithm", "SHA1").lower(),
                "label": urllib.parse.unquote(parts.path.strip("/"))}
    return {"secret": re.sub(r"[\s-]", "", text).upper(), "digits": 6, "period": 30, "algorithm": "sha1"}


def totp(secret: str, at: float | None = None, digits: int = 6, period: int = 30, algorithm: str = "sha1") -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algorithm)).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(code).zfill(digits)


# --- the machine --------------------------------------------------------------------------------------

def _filetime(value: int) -> datetime | None:
    return datetime.fromtimestamp(value / 1e7 - 11644473600) if value else None


def sensor_use(kind: str) -> list[dict]:
    """Apps Windows recorded using the camera ('webcam') or 'microphone'."""
    import winreg

    base = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{kind}"
    found = []

    def read(key_path: str, name: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                start = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
                stop = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
        except OSError:
            return
        if start:
            found.append({"app": name, "start": _filetime(start), "stop": _filetime(stop), "now": stop == 0 or stop < start})

    for sub in ("", "NonPackaged"):
        path = f"{base}\\{sub}" if sub else base
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    child = winreg.EnumKey(key, i)
                    if child == "NonPackaged":
                        continue
                    pretty = child.replace("#", "\\").split("\\")[-1] if sub else child.split("_")[0]
                    read(f"{path}\\{child}", pretty)
        except OSError:
            continue
    return sorted(found, key=lambda f: f["start"] or datetime.min, reverse=True)


SYSTEM_NAMES = {"svchost.exe", "lsass.exe", "csrss.exe", "winlogon.exe", "services.exe", "smss.exe", "explorer.exe",
                "wininit.exe", "spoolsv.exe", "taskhostw.exe", "dwm.exe", "conhost.exe", "rundll32.exe"}


def suspicious_processes() -> list[tuple[str, int, str, list[str]]]:
    import psutil

    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    risky_dirs = [d.lower() for d in (os.environ.get("TEMP", ""), str(Path.home() / "Downloads"),
                                       os.environ.get("PUBLIC", "")) if d]
    flagged = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name, exe = (proc.info["name"] or ""), (proc.info["exe"] or "")
        except (psutil.Error, KeyError):
            continue
        reasons = []
        low_exe, low_name = exe.lower(), name.lower()
        if low_name in SYSTEM_NAMES and exe and not low_exe.startswith(windir):
            reasons.append(f"named like a Windows process but runs from {Path(exe).parent}")
        if exe and any(low_exe.startswith(d + "\\") for d in risky_dirs):
            reasons.append("runs from Temp, Downloads or Public")
        if re.search(r"\.(pdf|docx?|jpe?g|png|txt)\.exe$", low_name):
            reasons.append("disguised with a double extension")
        if reasons:
            flagged.append((name, proc.info["pid"], exe, reasons))
    if flagged and sys.platform == "win32":
        paths = sorted({f[2] for f in flagged if f[2]})[:40]
        if paths:
            quoted = ",".join("'" + p.replace("'", "''") + "'" for p in paths)
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                      f"@({quoted}) | % {{ (Get-AuthenticodeSignature $_).Status.ToString() + '|' + $_ }}"],
                                     capture_output=True, text=True, timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                signed = {line.split("|", 1)[1].lower() for line in out.stdout.splitlines() if line.startswith("Valid|")}
                flagged = [(n, pid, exe, reasons + ([] if exe.lower() in signed else ["not digitally signed"]))
                           for n, pid, exe, reasons in flagged]
            except Exception:
                pass
    return flagged


class Guard:
    # --- passwords (the window asks for the secret itself) --------------------------------

    @command("passcheck", "passwordcheck", group=G, usage="/passcheck", help="how strong a password is (hidden box)")
    def passcheck(self, args: str, routed: bool = False):
        return SECRET_HINT.format(name="passcheck")

    def check_password(self, password: str) -> str:
        if not password:
            return "Nothing to check."
        result = password_strength(password)
        lines = [f"🔐 {result['verdict'].capitalize()} — about {result['bits']:.0f} bits; a fast offline attack would take "
                 f"{crack_time(result['seconds'])}."]
        if result["problems"]:
            lines.append("Weak because " + "; ".join(p for p in result["problems"] if p) + ".")
        if result["bits"] < 60:
            lines.append("Better: four or more random words (e.g. 'lamba-kedi-river-orbit'), or /password for a random one.")
        lines.append("/pwned checks whether it has appeared in a data breach.")
        return "\n".join(lines)

    @command("pwned", "breach", group=G, usage="/pwned", help="whether a password appeared in a breach (hidden box)")
    def pwned(self, args: str, routed: bool = False):
        return SECRET_HINT.format(name="pwned")

    def check_pwned(self, password: str) -> str:
        if not password:
            return "Nothing to check."
        try:
            count = pwned_count(password)
        except Exception as exc:
            return f"Couldn't reach Have I Been Pwned: {exc}"
        security.audit.record("breach check", "one password", "found" if count else "not found")
        if count:
            return (f"⚠ That password appears {count:,} times in known data breaches. Stop using it everywhere and "
                    "change it now — attackers try these first. (Only the first 5 characters of its SHA-1 hash left "
                    "this PC.)")
        return "✅ Not found in any known breach. (Only the first 5 characters of its SHA-1 hash left this PC.)"

    @command("checklink", "phishing", "linkcheck", group=G, usage="/checklink <link>", help="does this link look like phishing?")
    def check_link(self, args: str, routed: bool = False):
        url = args.strip().split()[0] if args.strip() else ""
        if not url:
            return "Usage: /checklink <the link>   — it is examined, not opened."
        score, reasons, domain = link_risks(url)
        target = ""
        host = urllib.parse.urlparse(url if "://" in url else "http://" + url).hostname or ""
        if host in SHORTENERS:
            target = redirect_target(url if "://" in url else "https://" + url)
            if target:
                inner, more, domain2 = link_risks(target)
                score, reasons = max(score, inner), reasons + [f"it leads to {domain2}: " + (", ".join(more) or "no other red flags")]
        verdict = "🚫 Very likely phishing" if score >= 6 else "⚠ Suspicious" if score >= 3 else "🟡 Probably fine, but be careful" \
            if score >= 1 else "✅ No red flags"
        lines = [f"{verdict} — real site: {domain}"] + [f"  • {r}" for r in reasons]
        if target:
            lines.append(f"  → redirects to {target[:120]}")
        lines.append("Never enter a password or card number after following a link from a message — go to the site yourself.")
        return "\n".join(lines)

    @command("hash", "checksum", group=G, usage="/hash <file> [expected] · /hash text <words>",
             help="file checksums (verify downloads) or hashes of text")
    def hash_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower().startswith("text "):
            data = text[5:].encode("utf-8")
            return "\n".join(f"  {n:<7} {hashlib.new(n, data).hexdigest()}" for n in ("md5", "sha1", "sha256", "sha512"))
        m = re.match(r'^("[^"]+"|.+?)(?:\s+([0-9a-fA-F]{32,128}))?$', text)
        path = kit.path_arg(m.group(1)) if m else None
        if path is None or not path.is_file():
            return "Usage: /hash <file> [expected checksum]   ·   /hash text <anything>"
        hashes = file_hashes(path)
        lines = [f"#️⃣ {path.name} ({kit.size(path.stat().st_size)})"] + [f"  {n:<7} {h}" for n, h in hashes.items()]
        if m.group(2):
            expected = m.group(2).lower()
            match = next((n for n, h in hashes.items() if h == expected), None)
            lines.append(f"✅ Matches the expected {match.upper()} — the file is intact." if match else
                         "❌ Does NOT match the expected checksum — the download is corrupt or was tampered with.")
        return "\n".join(lines)

    @command("encrypt", group=G, usage="/encrypt <file>", help="locks a file with a password (AES-256)")
    def encrypt(self, args: str, routed: bool = False):
        return "Type /encrypt <file> and press Enter — I'll ask for the password in a hidden box."

    def encrypt_with(self, args: str, password: str) -> str:
        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /encrypt <file>"
        if len(password) < 8:
            return "Use a password of at least 8 characters — a sentence is best."
        try:
            out = encrypt_file(path, password)
        except ImportError:
            return "Encryption needs the cryptography package (pip install cryptography)."
        security.audit.record("encrypt", path.name)
        return (f"🔒 Encrypted to {out}\nThe original is still there — delete it (or /shred it) if the locked copy is "
                "all you want to keep. Without the password nobody, including me, can open it.")

    @command("decrypt", group=G, usage="/decrypt <file.jenc>", help="unlocks a file /encrypt locked")
    def decrypt(self, args: str, routed: bool = False):
        return "Type /decrypt <file.jenc> and press Enter — I'll ask for the password in a hidden box."

    def decrypt_with(self, args: str, password: str) -> str:
        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /decrypt <file.jenc>"
        try:
            out = decrypt_file(path, password)
        except ValueError as exc:
            return str(exc)
        security.audit.record("decrypt", path.name)
        return f"🔓 Decrypted to {out}"

    @command("shred", group=G, usage="/shred <file>", help="overwrites a file, then deletes it")
    def shred_cmd(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /shred <file>   — overwritten with random data, then deleted. It cannot be undone."
        if not security.permissions.ask(security.DELETE_FILE, f"permanently destroy {path} ({kit.size(path.stat().st_size)}) — "
                                        "it cannot be recovered", context="/shred"):
            return "Denied. The file is untouched."
        try:
            shred(path)
        except OSError as exc:
            return f"Couldn't shred it: {exc}"
        security.audit.record("shred", path.name)
        return (f"🔥 {path.name} was overwritten and deleted. (On SSDs the drive may keep old copies in spare blocks; "
                "full-disk encryption (BitLocker) is the real protection there.)")

    @command("camcheck", "miccheck", "privacycheck", group=G, usage="/camcheck",
             help="which apps used your camera and microphone")
    def camcheck(self, args: str, routed: bool = False):
        if sys.platform != "win32":
            return "That works on Windows only."
        lines = []
        for kind, label in (("webcam", "📷 Camera"), ("microphone", "🎙 Microphone")):
            uses = sensor_use(kind)
            live = [u for u in uses if u["now"]]
            lines.append(f"{label}: " + (f"IN USE NOW by {', '.join(u['app'] for u in live)}" if live else "not in use"))
            for u in uses[:6]:
                if not u["now"]:
                    lines.append(f"  {u['app'][:40]:<40} last {u['start']:%d %b %H:%M}")
        lines.append("Windows records these; turn access off per app in Settings → Privacy & security.")
        return "\n".join(lines)

    @command("2fa", "totp", "otp", group=G, usage="/2fa · /2fa add <name> · /2fa <name>",
             help="2FA codes, like an authenticator app (secrets sealed)")
    def two_factor(self, args: str, routed: bool = False):
        text = args.strip()
        accounts = TOTP.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            return "Type /2fa add <name> and press Enter — I'll ask for the secret (or otpauth:// link) in a hidden box."
        if verb.lower() in {"delete", "remove"}:
            name = next((n for n in accounts if n.lower() == rest.strip().lower()), None)
            if not name:
                return f"No 2FA account '{rest.strip()}'."
            del accounts[name]
            TOTP.save(accounts)
            return f"Deleted {name}. Make sure you still have another way into that account."
        if not accounts:
            return "No 2FA accounts yet. /2fa add github — then paste the setup key the site shows (or the otpauth:// link)."
        shown = {n: a for n, a in accounts.items() if not text or text.lower() in n.lower()}
        if not shown:
            return f"No 2FA account matching '{text}'."
        lines = ["🔑 2FA codes:"]
        for name, a in sorted(shown.items()):
            left = a.get("period", 30) - int(time.time()) % a.get("period", 30)
            code = totp(a["secret"], digits=a.get("digits", 6), period=a.get("period", 30), algorithm=a.get("algorithm", "sha1"))
            lines.append(f"  {name:<18} {code[:3]} {code[3:]}   ({left}s left)")
        return "\n".join(lines)

    def add_totp(self, name: str, secret_text: str) -> str:
        name = name.strip()
        if not name:
            return "Usage: /2fa add <name>"
        try:
            account = parse_secret(secret_text)
            totp(account["secret"], digits=account["digits"], period=account["period"], algorithm=account["algorithm"])
        except Exception:
            return "That isn't a valid setup key. Copy the text key (letters A-Z and 2-7) or the otpauth:// link."
        accounts = TOTP.load()
        accounts[name] = {k: v for k, v in account.items() if k != "label"}
        TOTP.save(accounts)
        security.audit.record("2fa add", name)
        return f"🔑 Added {name}. /2fa {name} shows its code. Keep the site's recovery codes somewhere safe too."

    def wifi_safety(self, args: str) -> str:
        from . import pctools

        info = pctools.wifi_info()
        if not info.get("ssid"):
            return "Not connected to Wi-Fi."
        auth, cipher = info.get("authentication", ""), info.get("cipher", "")
        problems, good = [], []
        if auth.lower() in {"open", "açık"} or "open" in auth.lower():
            problems.append("the network is OPEN — anyone nearby can see unencrypted traffic; avoid logins, use a VPN")
        elif "wep" in auth.lower():
            problems.append("it uses WEP, which can be broken in minutes")
        elif "wpa3" in auth.lower():
            good.append("WPA3 encryption")
        elif "wpa2" in auth.lower():
            good.append("WPA2 encryption")
        if "tkip" in cipher.lower():
            problems.append("it uses the old TKIP cipher")
        try:
            category = pctools.powershell("(Get-NetConnectionProfile | Select -First 1).NetworkCategory")
        except Exception:
            category = ""
        if category.lower() == "private" and problems:
            problems.append("Windows treats it as a Private network, so your PC is discoverable — set it to Public")
        elif category.lower() == "public":
            good.append("your PC is set to Public (not discoverable)")
        verdict = "⚠ Be careful on this network" if problems else "✅ This network looks safe"
        lines = [f"{verdict}: {info.get('ssid')} ({auth or '?'}, {cipher or '?'})"]
        lines += [f"  ✗ {p}" for p in problems] + [f"  ✓ {g}" for g in good]
        return "\n".join(lines)

    @command("wifisafe", group=G, usage="/wifisafe", help="is this Wi-Fi network safe?")
    def wifisafe(self, args: str, routed: bool = False):
        if sys.platform != "win32":
            return "That works on Windows only."
        return self.wifi_safety(args)

    @command("procscan", "processes", group=G, usage="/procscan · /procscan defender",
             help="looks for suspicious running programs")
    def procscan(self, args: str, routed: bool = False):
        if args.strip().lower() == "defender":
            if not security.permissions.ask(security.RUN_COMMAND, "start a Microsoft Defender quick scan", context="/procscan"):
                return "Denied."
            subprocess.Popen(["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "🛡 Defender quick scan started. Results appear in Windows Security."
        flagged = suspicious_processes()
        if not flagged:
            return "✅ Nothing suspicious among the running programs. (/procscan defender runs a Defender quick scan too.)"
        lines = [f"⚠ {len(flagged)} program(s) worth a look:"]
        for name, pid, exe, reasons in flagged[:15]:
            lines.append(f"  {name} (pid {pid}) — {'; '.join(reasons)}\n      {exe}")
        lines.append("Not proof of malware — but if you don't recognise one, look it up and run /procscan defender.")
        return "\n".join(lines)
