"""10.0 security and antivirus: a security score with fixes, firewall and
Defender status, devices on your Wi-Fi, browser extensions, sign-in history,
failed sign-ins, USB history and alerts, photo metadata removal, VirusTotal,
a VPN/IP leak check, security news — and Defender scans run from JARVIS.

The antivirus is Microsoft Defender's engine: JARVIS starts its scans, reads
its results and watches for USB drives to scan, but it never pretends to
detect malware on its own. Settings that protect the PC are opened for you to
change; JARVIS doesn't flip security switches itself.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from .. import alerts, kit, net, security
from ..registry import command, field, split
from .system import NO_WINDOW, _ps_date, powershell, ps_json

G = "Security"
KNOWN_DEVICES = kit.Store("wifi_devices.json", {})
AV_SETTINGS = kit.Store("antivirus.json", {"usb_scan": True, "schedule": "", "last_scan": 0, "history": []})
SEEN_USB = kit.Store("usb_seen.json", [])
MPCMD = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"

OUI = {"00:1A:11": "Google", "3C:5A:B4": "Google", "F4:F5:D8": "Google", "D8:6C:63": "Google",
       "00:17:88": "Philips Hue", "EC:FA:BC": "Espressif (smart device)", "24:0A:C4": "Espressif (smart device)",
       "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
       "F0:18:98": "Apple", "A4:83:E7": "Apple", "3C:22:FB": "Apple", "AC:BC:32": "Apple", "DC:A9:04": "Apple",
       "8C:85:90": "Apple", "F4:0F:24": "Apple", "00:1E:C2": "Apple", "BC:D0:74": "Apple",
       "50:C7:BF": "TP-Link", "C0:06:C3": "TP-Link", "98:DA:C4": "TP-Link", "60:32:B1": "TP-Link",
       "00:E0:4C": "Realtek", "B4:2E:99": "Gigabyte", "D8:BB:C1": "Micro-Star (MSI)", "04:D4:C4": "ASUS",
       "2C:FD:A1": "ASUS", "AC:22:0B": "ASUS", "00:24:D6": "Intel", "8C:16:45": "Lenovo", "F8:BC:12": "Dell",
       "A0:CE:C8": "Samsung", "8C:79:F5": "Samsung", "5C:0A:5B": "Samsung", "84:25:19": "Samsung",
       "28:6C:07": "Xiaomi", "64:09:80": "Xiaomi", "F8:A2:D6": "Xiaomi", "48:2C:A0": "Xiaomi",
       "00:9A:CD": "Huawei", "48:46:FB": "Huawei", "E8:9A:8F": "Huawei", "F0:27:2D": "Amazon", "44:65:0D": "Amazon",
       "74:C2:46": "Amazon", "00:50:F2": "Microsoft", "7C:1E:52": "Microsoft", "C8:3F:26": "Microsoft",
       "00:04:4B": "NVIDIA", "D4:6D:6D": "Intel", "00:0D:3A": "Microsoft", "1C:1B:0D": "Gigabyte",
       "B0:BE:76": "TP-Link", "70:4F:57": "TP-Link", "E4:C3:2A": "TP-Link", "00:26:5A": "D-Link",
       "C8:D3:A3": "D-Link", "00:18:E7": "Cameo", "BC:F6:85": "D-Link", "00:1F:1F": "Edimax",
       "00:22:6B": "Linksys", "C0:56:27": "Belkin", "E0:63:DA": "Ubiquiti", "FC:EC:DA": "Ubiquiti",
       "04:18:D6": "Ubiquiti", "00:0C:29": "VMware", "08:00:27": "VirtualBox", "52:54:00": "QEMU",
       "A8:5E:45": "ASUS", "CC:2D:E0": "Routerboard", "4C:5E:0C": "Routerboard", "38:2C:4A": "ASUS",
       "BC:EE:7B": "ASUS", "00:1D:D8": "Microsoft (Xbox)", "7C:ED:8D": "Microsoft (Xbox)", "00:D9:D1": "Sony",
       "FC:F1:52": "Sony", "70:9E:29": "Sony (PlayStation)", "00:04:1F": "Sony", "DC:A2:66": "Hon Hai (Foxconn)",
       "00:09:2D": "HTC", "18:F0:E4": "Xiaomi", "9C:28:F7": "Xiaomi", "30:B4:9E": "TP-Link"}
RISKY_PERMISSIONS = {"<all_urls>": "every website", "*://*/*": "every website", "http://*/*": "every website",
                     "https://*/*": "every website", "tabs": "your open tabs", "history": "your history",
                     "cookies": "your cookies", "webRequest": "your web traffic", "webRequestBlocking": "your web traffic",
                     "clipboardRead": "your clipboard", "debugger": "debugging pages", "nativeMessaging":
                     "programs on your PC", "management": "your other extensions", "downloads": "your downloads",
                     "proxy": "your connection's proxy", "privacy": "privacy settings"}
SETTINGS_PAGES = {"firewall": "windowsdefender://network/", "defender": "windowsdefender://threat/",
                  "update": "ms-settings:windowsupdate", "bitlocker": "ms-settings:deviceencryption",
                  "camera": "ms-settings:privacy-webcam", "mic": "ms-settings:privacy-microphone",
                  "remote": "ms-settings:remotedesktop", "uac": "", "signin": "ms-settings:signinoptions",
                  "apps": "ms-settings:appsfeatures", "ransomware": "windowsdefender://ransomwareprotection/"}


# --- status ------------------------------------------------------------------------------

def firewall() -> list[dict]:
    return [{"name": r.get("Name"), "on": bool(r.get("Enabled")), "inbound": r.get("DefaultInboundAction"),
             "outbound": r.get("DefaultOutboundAction")}
            for r in ps_json("Get-NetFirewallProfile -ErrorAction SilentlyContinue | Select Name, Enabled, "
                             "DefaultInboundAction, DefaultOutboundAction")]


def defender() -> dict:
    rows = ps_json("Get-MpComputerStatus -ErrorAction SilentlyContinue | Select AMServiceEnabled, AntivirusEnabled, "
                   "RealTimeProtectionEnabled, AntivirusSignatureLastUpdated, AntivirusSignatureVersion, QuickScanAge, "
                   "FullScanAge, IsTamperProtected, QuickScanEndTime, FullScanEndTime, BehaviorMonitorEnabled, "
                   "AMRunningMode")
    if not rows:
        return {}
    r = rows[0]
    return {"service": bool(r.get("AMServiceEnabled")), "antivirus": bool(r.get("AntivirusEnabled")),
            "realtime": bool(r.get("RealTimeProtectionEnabled")), "behavior": bool(r.get("BehaviorMonitorEnabled")),
            "tamper": bool(r.get("IsTamperProtected")), "mode": r.get("AMRunningMode") or "",
            "signatures": _ps_date(r.get("AntivirusSignatureLastUpdated")), "version": r.get("AntivirusSignatureVersion"),
            "quick_age": r.get("QuickScanAge"), "full_age": r.get("FullScanAge"),
            "quick_end": _ps_date(r.get("QuickScanEndTime")), "full_end": _ps_date(r.get("FullScanEndTime"))}


def antivirus_products() -> list[dict]:
    """Every antivirus Windows Security Center knows of, and which is switched on.

    productState packs it into bytes: the middle one is 0x10 or 0x11 when the
    product is on, the low one 0x00 when its definitions are current.
    """
    out = []
    for r in ps_json("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct "
                     "-ErrorAction SilentlyContinue | Select displayName, productState"):
        try:
            state = int(r.get("productState") or 0)
        except (TypeError, ValueError):
            continue
        out.append({"name": r.get("displayName") or "Unknown antivirus", "on": (state >> 8) & 0xFF in (0x10, 0x11),
                    "current": state & 0xFF == 0})
    return out


def other_antivirus() -> dict | None:
    """The antivirus in charge when it isn't Defender (McAfee, Norton…), else None.

    With one installed, Windows puts Defender in passive mode: its real-time
    protection is off on purpose and the other product guards the PC. Defender
    still scans when asked, so JARVIS's scans keep working as a second opinion.
    """
    return next((p for p in antivirus_products() if p["on"] and "defender" not in p["name"].lower()), None)


def threats(limit: int = 30) -> list[dict]:
    names = {str(t.get("ThreatID")): t for t in ps_json(
        "Get-MpThreat -ErrorAction SilentlyContinue | Select ThreatID, ThreatName, SeverityID, IsActive")}
    out = []
    for d in ps_json("Get-MpThreatDetection -ErrorAction SilentlyContinue | Select ThreatID, InitialDetectionTime, "
                     "ActionSuccess, Resources, ThreatStatusID, ProcessName")[:limit]:
        threat = names.get(str(d.get("ThreatID")), {})
        resources = d.get("Resources") or []
        out.append({"name": threat.get("ThreatName") or f"Threat {d.get('ThreatID')}",
                    "when": _ps_date(d.get("InitialDetectionTime")), "handled": bool(d.get("ActionSuccess")),
                    "active": bool(threat.get("IsActive")),
                    "severity": {1: "low", 2: "moderate", 4: "high", 5: "severe"}.get(threat.get("SeverityID"), ""),
                    "where": (resources if isinstance(resources, list) else [resources])[:2]})
    out.sort(key=lambda t: t["when"] or datetime.min, reverse=True)
    return out


def registry_value(root: str, key: str, name: str):
    try:
        import winreg

        hive = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[root]
        with winreg.OpenKey(hive, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except (OSError, ImportError, KeyError):
        return None


def last_update() -> datetime | None:
    rows = ps_json("Get-HotFix -ErrorAction SilentlyContinue | Sort-Object InstalledOn -Descending | "
                   "Select -First 1 InstalledOn")
    return _ps_date(rows[0].get("InstalledOn")) if rows else None


def score() -> tuple[int, list[dict]]:
    """0-100 and the checks behind it, each with what to do and where."""
    checks: list[dict] = []

    def add(name, ok, weight, fix, page=""):
        checks.append({"name": name, "ok": ok, "weight": weight, "fix": fix, "page": page})

    d = defender()
    other = other_antivirus()
    if other:
        # Defender's own switches are off by design here; marking them as
        # faults told McAfee users to turn on something Windows won't allow.
        name = other["name"]
        add(f"Antivirus is on ({name})", True, 20, "")
        add(f"Real-time protection is on ({name})", True, 15, "")
        add(f"{name}'s definitions are up to date", other["current"], 10, f"Update {name} (from its tray icon)")
    elif d:
        add("Antivirus (Defender) is on", d["antivirus"], 20, "Turn on Microsoft Defender Antivirus", "defender")
        add("Real-time protection is on", d["realtime"], 15, "Turn real-time protection back on", "defender")
        fresh = d["signatures"] is not None and d["signatures"] > datetime.now() - timedelta(days=3)
        add("Virus definitions are up to date", fresh, 10, "Update the definitions (Antivirus page)", "defender")
        add("Tamper protection is on", d["tamper"], 5, "Turn on tamper protection", "defender")
        add("A scan in the last 7 days", d["quick_age"] is not None and d["quick_age"] <= 7, 5, "Run a quick scan")
    else:
        add("Defender is reporting", False, 35, "Windows Security didn't answer — another antivirus may be in charge")
    profiles = firewall()
    add("Firewall is on for every network", bool(profiles) and all(p["on"] for p in profiles), 15,
        "Turn the firewall on", "firewall")
    updated = last_update()
    add("Windows updated in the last 45 days", updated is not None and updated > datetime.now() - timedelta(days=45),
        10, "Install Windows updates", "update")
    uac = registry_value("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "EnableLUA")
    add("User Account Control is on", uac in (None, 1), 10, "Turn UAC back on (Control Panel → User Accounts)")
    rdp = registry_value("HKLM", r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")
    add("Remote Desktop is off", rdp in (None, 1), 5, "Turn off Remote Desktop if you don't use it", "remote")
    smb1 = registry_value("HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters", "SMB1")
    add("Old SMBv1 file sharing is off", smb1 in (None, 0), 5, "Turn off SMB 1.0 in Windows Features")
    total = sum(c["weight"] for c in checks) or 1
    got = sum(c["weight"] for c in checks if c["ok"])
    return round(100 * got / total), checks


def open_setting(name: str) -> bool:
    uri = SETTINGS_PAGES.get(name)
    if not uri:
        return False
    try:
        os.startfile(uri)  # noqa: S606 — a Windows Settings page, opened for the user to change
        return True
    except OSError:
        return False


# --- Wi-Fi devices ----------------------------------------------------------------------------

def local_network() -> tuple[str, str] | None:
    """(this PC's IPv4, the /24 prefix) for the network the default route uses."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
    except OSError:
        return None
    if ip.startswith("127."):
        return None
    return ip, ".".join(ip.split(".")[:3])


def wake_network(prefix: str, wait: float = 1.5) -> None:
    """Make the PC ask every address on the network for its hardware address,
    so the ARP table fills in.

    One empty UDP packet each (to the discard port, where nothing answers)
    makes Windows send the ARP request; devices that ignore pings still
    answer that. It replaced 254 ping processes, which took 25 seconds here.
    Their Windows-only flags also meant "wait 350 seconds" on Linux, and the
    test run on GitHub hung on them.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return
    with sock:
        sock.setblocking(False)
        for host in range(1, 255):
            try:
                sock.sendto(b"", (f"{prefix}.{host}", 9))
            except OSError:
                pass
    time.sleep(wait)


def arp_table(prefix: str) -> list[tuple[str, str]]:
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.decode("utf-8", "replace").splitlines():
        # Windows: "  192.168.1.1   aa-bb-cc-dd-ee-ff   dynamic"; Linux and macOS: "? (192.168.1.1) at aa:bb:…"
        m = (re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(\w+)", line) or
             re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]{17})", line))
        if m and m.group(1).startswith(prefix + ".") and not m.group(1).endswith(".255"):
            found.append((m.group(1), m.group(2).upper().replace("-", ":")))
    return found


def device_names(addresses: list[str], deadline: float = 3.0) -> dict[str, str]:
    """Reverse-DNS names for the addresses, all at once and for at most `deadline` seconds.

    One by one, a network whose DNS doesn't answer for local addresses spent
    seconds on each, which is where the scan on GitHub's runners hung.
    """
    from concurrent.futures import ThreadPoolExecutor, wait

    def lookup(address: str) -> str:
        try:
            return socket.gethostbyaddr(address)[0]
        except (OSError, socket.herror):
            return ""

    pool = ThreadPoolExecutor(max_workers=32)
    futures = {pool.submit(lookup, a): a for a in addresses}
    done, _ = wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)
    return {futures[f]: f.result() for f in done}


def vendor(mac: str) -> str:
    if mac[1:2] in {"2", "6", "A", "E"}:
        return "private address (a phone or laptop hiding its real one)"
    return OUI.get(mac[:8], "")


def scan_network() -> dict:
    local = local_network()
    if local is None:
        return {"error": "Not connected to a local network."}
    ip, prefix = local
    wake_network(prefix)
    gateway = powershell("(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
                         "Sort-Object RouteMetric | Select -First 1).NextHop", timeout=15)
    known = KNOWN_DEVICES.load()
    devices = []
    table = arp_table(prefix)
    names = device_names([address for address, _ in table])
    for address, mac in table:
        name = names.get(address, "")
        devices.append({"ip": address, "mac": mac, "name": name, "vendor": vendor(mac),
                        "new": mac not in known, "label": known.get(mac, {}).get("label", ""),
                        "role": "router" if address == gateway else ""})
    devices.append({"ip": ip, "mac": "", "name": socket.gethostname(), "vendor": "", "new": False, "label": "",
                    "role": "this PC"})
    first_scan = not known
    for d in devices:
        if d["mac"]:
            entry = known.setdefault(d["mac"], {"first": time.time(), "label": ""})
            entry["last"] = time.time()
            entry["ip"] = d["ip"]
    KNOWN_DEVICES.save(known)
    if first_scan:
        for d in devices:
            d["new"] = False
    devices.sort(key=lambda d: tuple(int(x) for x in d["ip"].split(".")))
    return {"devices": devices, "prefix": prefix}


# --- browser extensions ---------------------------------------------------------------------------

def _message(folder: Path, value: str) -> str:
    if not value.startswith("__MSG_"):
        return value
    key = value[6:-2].lower()
    for locale in ("en", "en_US", "en_GB", "tr"):
        path = folder / "_locales" / locale / "messages.json"
        if path.exists():
            try:
                data = {k.lower(): v for k, v in json.loads(path.read_text(encoding="utf-8-sig")).items()}
                if key in data:
                    return data[key].get("message", value)
            except (OSError, ValueError):
                continue
    return value


def extensions() -> list[dict]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    found = []
    for browser, base in (("Chrome", local / "Google" / "Chrome" / "User Data"),
                          ("Edge", local / "Microsoft" / "Edge" / "User Data"),
                          ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
                          ("Opera", roaming / "Opera Software" / "Opera Stable")):
        for ext_dir in base.glob("*/Extensions") if base.is_dir() else []:
            for ext in ext_dir.iterdir():
                versions = sorted((v for v in ext.iterdir() if v.is_dir()), key=lambda v: v.name, reverse=True) \
                    if ext.is_dir() else []
                if not versions:
                    continue
                manifest = versions[0] / "manifest.json"
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
                name = _message(versions[0], str(data.get("name", ext.name)))
                if name.lower().startswith(("chrome pdf", "chrome web store", "google docs offline")):
                    continue
                perms = [str(p) for p in (data.get("permissions") or []) + (data.get("host_permissions") or [])
                         + [m for cs in data.get("content_scripts") or [] for m in cs.get("matches", [])]]
                risky = sorted({RISKY_PERMISSIONS[p] for p in perms if p in RISKY_PERMISSIONS})
                found.append({"browser": browser, "profile": ext_dir.parent.name, "name": name,
                              "version": data.get("version", ""), "id": ext.name, "risky": risky})
    for profile in (roaming / "Mozilla" / "Firefox" / "Profiles").glob("*/extensions.json") if (
            roaming / "Mozilla" / "Firefox" / "Profiles").is_dir() else []:
        try:
            data = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for addon in data.get("addons", []):
            if addon.get("type") == "extension" and not addon.get("location", "").startswith("app-"):
                perms = (addon.get("userPermissions") or {}).get("permissions", []) + \
                        (addon.get("userPermissions") or {}).get("origins", [])
                found.append({"browser": "Firefox", "profile": profile.parent.name,
                              "name": (addon.get("defaultLocale") or {}).get("name", addon.get("id")),
                              "version": addon.get("version", ""), "id": addon.get("id"),
                              "risky": sorted({RISKY_PERMISSIONS[p] for p in perms if p in RISKY_PERMISSIONS})})
    return found


# --- sign-ins and USB ----------------------------------------------------------------------------

def sign_ins(days: int = 7) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = ps_json("Get-WinEvent -FilterHashtable @{LogName='System'; Id=7001,7002,12,13,42,1; StartTime='"
                   f"{since}'}} -MaxEvents 200 -ErrorAction SilentlyContinue | Select TimeCreated, Id, ProviderName",
                   timeout=40)
    names = {7001: "signed in", 7002: "signed out", 12: "Windows started", 13: "Windows shut down",
             42: "went to sleep", 1: "woke up"}
    out = []
    for r in rows:
        provider = str(r.get("ProviderName") or "")
        event = r.get("Id")
        if event in (7001, 7002) and "Winlogon" not in provider:
            continue
        if event in (12, 13) and "Kernel-General" not in provider:
            continue
        if event == 42 and "Kernel-Power" not in provider:
            continue
        if event == 1 and "Power-Troubleshooter" not in provider:
            continue
        out.append({"when": _ps_date(r.get("TimeCreated")), "what": names.get(event, str(event))})
    return out


def failed_sign_ins(limit: int = 30) -> list[dict] | None:
    """None when Windows won't let a normal user read the Security log."""
    out = powershell("try { Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625} -MaxEvents "
                     f"{limit} -ErrorAction Stop | Select TimeCreated, @{{n='User';e={{$_.Properties[5].Value}}}}, "
                     "@{n='From';e={$_.Properties[19].Value}} | ConvertTo-Json -Compress } catch "
                     "{ if ($_.Exception.Message -match 'No events') { '[]' } else { 'DENIED' } }", timeout=40)
    if not out or "DENIED" in out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return []
    data = data if isinstance(data, list) else [data]
    return [{"when": _ps_date(r.get("TimeCreated")), "user": r.get("User") or "?", "from": r.get("From") or ""}
            for r in data]


def usb_history() -> list[dict]:
    rows = ps_json("Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -like 'USBSTOR*' } | "
                   "ForEach-Object { $p = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName "
                   "'DEVPKEY_Device_FirstInstallDate','DEVPKEY_Device_LastArrivalDate','DEVPKEY_Device_LastRemovalDate' "
                   "-ErrorAction SilentlyContinue; [pscustomobject]@{ Name=$_.FriendlyName; Present=$_.Present; "
                   "First=($p | Where KeyName -eq 'DEVPKEY_Device_FirstInstallDate').Data; "
                   "Arrived=($p | Where KeyName -eq 'DEVPKEY_Device_LastArrivalDate').Data; "
                   "Removed=($p | Where KeyName -eq 'DEVPKEY_Device_LastRemovalDate').Data } }", timeout=60)
    out = [{"name": r.get("Name") or "USB drive", "present": bool(r.get("Present")), "first": _ps_date(r.get("First")),
            "arrived": _ps_date(r.get("Arrived")), "removed": _ps_date(r.get("Removed"))} for r in rows]
    out.sort(key=lambda r: r["arrived"] or r["first"] or datetime.min, reverse=True)
    return out


def removable_drives() -> list[str]:
    drives = []
    for part in psutil.disk_partitions(all=False):
        if "removable" in part.opts.lower():
            drives.append(part.mountpoint)
    return drives


# --- metadata -----------------------------------------------------------------------------------

def strip_metadata(path: Path, in_place: bool = False) -> tuple[Path, list[str]]:
    from PIL import ExifTags, Image, ImageOps

    with Image.open(path) as im:
        exif = im.getexif()
        found = []
        gps = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else {}
        if gps:
            found.append("GPS location")
        for tag, value in exif.items():
            name = ExifTags.TAGS.get(tag, str(tag))
            if name in {"Make", "Model", "DateTime", "Software", "Artist", "Copyright", "HostComputer"}:
                found.append(f"{name}: {str(value)[:40]}")
        upright = ImageOps.exif_transpose(im)
        clean = Image.new(upright.mode, upright.size)
        clean.putdata(list(upright.getdata())) if upright.mode in {"1", "L", "P"} else clean.paste(upright)
        if upright.mode == "P" and upright.getpalette():
            clean.putpalette(upright.getpalette())
        target = path if in_place else path.with_name(f"{path.stem}_clean{path.suffix}")
        params = {"quality": 92} if path.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
        clean.save(target, **params)
    return target, found


# --- VirusTotal, IP and news ---------------------------------------------------------------------

def virustotal(path: Path) -> dict:
    from ..config import get_setting
    from ..guard import file_hashes

    key = get_setting("VIRUSTOTAL_API_KEY", "").strip()
    if not key:
        raise PermissionError("Add your free VirusTotal key in Settings → API keys (VIRUSTOTAL_API_KEY) first.")
    digest = file_hashes(path)["sha256"]
    request = urllib.request.Request(f"https://www.virustotal.com/api/v3/files/{digest}",
                                     headers={"x-apikey": key, "User-Agent": net.DEFAULT_USER_AGENT})
    try:
        with net.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if "404" in str(exc):
            return {"sha256": digest, "known": False}
        raise
    attrs = data.get("data", {}).get("attributes", {})
    stats = attrs.get("last_analysis_stats", {})
    names = sorted({r.get("result") for r in attrs.get("last_analysis_results", {}).values() if r.get("result")})[:6]
    return {"sha256": digest, "known": True, "stats": stats, "names": names,
            "label": (attrs.get("popular_threat_classification") or {}).get("suggested_threat_label", ""),
            "link": f"https://www.virustotal.com/gui/file/{digest}"}


def public_ip() -> dict:
    info = kit.get_json("https://ipwho.is/", timeout=12)
    try:
        v6 = kit.get_text("https://api64.ipify.org", timeout=8).strip()
    except Exception:
        v6 = ""
    info["ipv6"] = v6 if ":" in v6 else ""
    return info


HOSTING = re.compile(r"(vpn|proxy|hosting|datacenter|data center|cloud|ovh|digitalocean|linode|hetzner|m247|"
                     r"amazon|google llc|microsoft|choopa|vultr|mullvad|nord|express|proton|surfshark|cyberghost|"
                     r"private internet|ipvanish|windscribe|tunnelbear|leaseweb|contabo|cloudflare)", re.I)

NEWS_FEEDS = [("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
              ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
              ("Krebs on Security", "https://krebsonsecurity.com/feed/")]


def security_news(limit: int = 12) -> list[dict]:
    items = []
    for source, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(kit.get_text(url, timeout=12).encode("utf-8"))
        except Exception:
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = item.findtext("pubDate") or ""
            if title:
                items.append({"source": source, "title": title, "link": link, "date": date[:16]})
            if sum(1 for i in items if i["source"] == source) >= limit // len(NEWS_FEEDS) + 2:
                break
    return items[:limit]


# --- Defender scans -------------------------------------------------------------------------------

class Scanner:
    """One Defender scan at a time, run in the background, results as alerts."""

    def __init__(self) -> None:
        self.running: dict | None = None
        self.last: dict | None = None
        self._lock = threading.Lock()

    def start(self, kind: str, path: str = "", quiet: bool = False) -> str:
        if not MPCMD.exists():
            return "Microsoft Defender's scanner isn't available on this PC (another antivirus may be in charge)."
        with self._lock:
            if self.running:
                return f"A {self.running['kind']} scan is already running."
            self.running = {"kind": kind, "path": path, "started": time.time()}
        argv = [str(MPCMD), "-Scan", "-ScanType", {"quick": "1", "full": "2", "custom": "3"}[kind]]
        if kind == "custom":
            argv += ["-File", path]
        threading.Thread(target=self._run, args=(argv, kind, path, quiet), daemon=True).start()
        return {"quick": "🛡 Quick scan started — a few minutes. I'll tell you when it's done.",
                "full": "🛡 Full scan started — this can take an hour or more. I'll tell you when it's done.",
                "custom": f"🛡 Scanning {path}…"}[kind]

    def _run(self, argv, kind, path, quiet) -> None:
        started = time.time()
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=6 * 3600, creationflags=NO_WINDOW)
            code, out = proc.returncode, proc.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, out = -1, str(exc)
        found = code == 2 or "found" in out.lower() and "no threats" not in out.lower()
        result = {"kind": kind, "path": path, "started": started, "seconds": time.time() - started, "code": code,
                  "threats": found, "output": out[-2000:]}
        with self._lock:
            self.running = None
            self.last = result
        settings = AV_SETTINGS.load()
        settings["last_scan"] = time.time()
        settings["history"] = ([{k: result[k] for k in ("kind", "path", "started", "seconds", "code", "threats")}]
                               + settings.get("history", []))[:30]
        AV_SETTINGS.save(settings)
        target = f" of {path}" if path else ""
        if code not in (0, 2):
            alerts.post(f"The {kind} scan{target} didn't finish", out.strip().splitlines()[-1][:150] if out.strip() else
                        "Defender stopped early.", page="antivirus", kind="warn")
        elif found:
            alerts.post(f"⚠ Threats found in the {kind} scan{target}", "Open the Antivirus page to see what was "
                        "found and whether it was removed.", page="antivirus", kind="error")
        elif not quiet:
            alerts.post(f"✅ {kind.capitalize()} scan{target}: no threats", f"Took {int(result['seconds'] // 60)} min "
                        f"{int(result['seconds'] % 60)} s.", page="antivirus", kind="ok")


scanner = Scanner()


def register_watchers(jarvis, watchers) -> None:
    seen = {"drives": set(removable_drives()), "usb": None}

    def usb():
        drives = set(removable_drives())
        new = drives - seen["drives"]
        seen["drives"] = drives
        for drive in sorted(new):
            alerts.post(f"USB drive connected: {drive}", "Scanning it with Defender…" if AV_SETTINGS.load().get(
                "usb_scan", True) else "", page="antivirus")
            if AV_SETTINGS.load().get("usb_scan", True):
                scanner.start("custom", drive)

    watchers.add("usb-drives", 5, usb, first_after=10)

    def usb_devices():
        names = {r["name"] for r in usb_history() if r["present"]}
        known = set(SEEN_USB.load())
        if seen["usb"] is None:
            seen["usb"] = True
            SEEN_USB.save(sorted(known | names))
            return
        fresh = names - known
        if fresh:
            alerts.post("New USB device", ", ".join(sorted(fresh))[:150], page="security", kind="warn")
            SEEN_USB.save(sorted(known | names))

    watchers.add("usb-devices", 90, usb_devices, first_after=40)

    def scheduled():
        settings = AV_SETTINGS.load()
        plan = settings.get("schedule", "")
        if not plan:
            return
        m = re.match(r"(daily|weekly)\s+(\d{1,2}):(\d{2})", plan)
        if not m:
            return
        now = datetime.now()
        due = now.hour * 60 + now.minute >= int(m.group(2)) * 60 + int(m.group(3))
        gap = 86400 if m.group(1) == "daily" else 7 * 86400
        if due and time.time() - settings.get("last_scan", 0) > gap - 3600 and not scanner.running:
            scanner.start("quick")

    watchers.add("scheduled-scan", 300, scheduled, first_after=120)

    state = {"failed": 0.0}

    def failed():
        found = failed_sign_ins(5)
        if not found:
            return
        newest = max((f["when"].timestamp() for f in found if f["when"]), default=0)
        if state["failed"] and newest > state["failed"]:
            alerts.post("Failed sign-in on this PC", f"Someone typed a wrong password for {found[0]['user']}.",
                        page="security", kind="warn")
        state["failed"] = max(state["failed"], newest)

    watchers.add("failed-logins", 300, failed, first_after=90)


class Shield10:
    @command("securityscore", "secscore", group=G, usage="/securityscore", help="a security score for this PC, "
             "with what to fix", title="Security score with fixes", icon="🛡", page="security")
    def securityscore_cmd(self, args: str, routed: bool = False):
        value, checks = score()
        lines = [f"🛡 Security score: {value}/100"]
        for c in checks:
            lines.append(f"  {'✅' if c['ok'] else '❌'} {c['name']}" + ("" if c["ok"] else f" — {c['fix']}"))
        return "\n".join(lines)

    @command("firewall", group=G, usage="/firewall", help="is the Windows firewall on for every network?",
             title="Firewall status", icon="🧱", page="security")
    def firewall_cmd(self, args: str, routed: bool = False):
        profiles = firewall()
        if not profiles:
            return "Windows didn't report the firewall (another firewall may be managing it)."
        return "🧱 Firewall:\n" + "\n".join(f"  {'✅' if p['on'] else '❌'} {p['name']}: {'on' if p['on'] else 'OFF'}"
                                            for p in profiles)

    @command("defender", group=G, usage="/defender", help="Microsoft Defender's status", title="Defender status",
             icon="🛡", page="antivirus")
    def defender_cmd(self, args: str, routed: bool = False):
        d = defender()
        other = other_antivirus()
        if not d:
            return (f"🛡 {other['name']} is your antivirus; Defender didn't answer." if other else
                    "Defender didn't answer — another antivirus may be in charge.")
        sig = f"{d['signatures']:%d %b %H:%M}" if d["signatures"] else "unknown"
        if other:
            return (f"🛡 {other['name']} is your active antivirus — it does the real-time protection.\n"
                    f"  Defender is in passive mode beside it ({d['mode'] or 'passive'}): it scans when asked, so "
                    f"/avscan and the Antivirus page still work, as a second opinion.\n"
                    f"  Defender's definitions {d['version']} ({sig})")
        return (f"🛡 Defender: antivirus {'on' if d['antivirus'] else 'OFF'} · real-time "
                f"{'on' if d['realtime'] else 'OFF'} · tamper protection {'on' if d['tamper'] else 'off'}\n"
                f"  Definitions {d['version']} ({sig}) · last quick scan {d['quick_age']} day(s) ago · "
                f"last full scan {d['full_age'] if d['full_age'] not in (None, 4294967295) else 'never'} day(s) ago")

    @command("wifidevices", "whoisonmywifi", group=G, usage="/wifidevices", help="the devices on your Wi-Fi network",
             title="Who is on my Wi-Fi", icon="📡", page="security")
    def wifidevices_cmd(self, args: str, routed: bool = False):
        result = scan_network()
        if "error" in result:
            return result["error"]
        lines = [f"📡 {len(result['devices'])} device(s) on {result['prefix']}.x:"]
        for d in result["devices"]:
            what = d["label"] or d["name"] or d["vendor"] or "unknown device"
            tag = f" [{d['role']}]" if d["role"] else (" 🆕 new" if d["new"] else "")
            lines.append(f"  {d['ip']:<15} {what[:40]:<40} {d['mac']}{tag}")
        lines.append("Don't recognise one? Change your Wi-Fi password in the router (the gateway address).")
        return "\n".join(lines)

    @command("extensions", "browserextensions", group=G, usage="/extensions", help="browser extensions and what they can read",
             title="Browser extensions list", icon="🧩", page="security")
    def extensions_cmd(self, args: str, routed: bool = False):
        found = extensions()
        if not found:
            return "No browser extensions found (Chrome, Edge, Brave, Opera, Firefox)."
        lines = [f"🧩 {len(found)} extension(s):"]
        for e in sorted(found, key=lambda e: (not e["risky"], e["browser"], e["name"].lower())):
            lines.append(f"  {'⚠' if e['risky'] else '•'} {e['browser']}: {e['name'][:50]} {e['version']}" +
                         (f" — can see {', '.join(e['risky'])}" if e["risky"] else ""))
        lines.append("Remove what you don't use from the browser's extensions page.")
        return "\n".join(lines)

    @command("logins", "signins", group=G, usage="/logins [days]", help="when this PC was signed into, started, slept "
             "and woke", title="Login history", icon="🔑", page="security",
             fields=(field("days", "number", "Days", "7"),))
    def logins_cmd(self, args: str, routed: bool = False):
        days = int(re.search(r"\d+", args).group(0)) if re.search(r"\d+", args or "") else 7
        events = sign_ins(days)
        if not events:
            return "No sign-in events in Windows' log for that period."
        return f"🔑 Last {days} days:\n" + "\n".join(f"  {e['when']:%a %d %b %H:%M}  {e['what']}" for e in events[:60]
                                                    if e["when"])

    @command("failedlogins", group=G, usage="/failedlogins", help="wrong-password attempts on this PC",
             title="Failed login alerts", icon="🚨", page="security")
    def failedlogins_cmd(self, args: str, routed: bool = False):
        found = failed_sign_ins()
        if found is None:
            return ("Windows only lets administrators read failed sign-ins. Start JARVIS with 'Run as administrator' "
                    "to see them (and to get alerts for new ones).")
        if not found:
            return "✅ No failed sign-ins recorded."
        return "🚨 Failed sign-ins:\n" + "\n".join(f"  {f['when']:%d %b %H:%M}  user {f['user']}" +
                                                  (f" from {f['from']}" if f["from"] and f["from"] != "-" else "")
                                                  for f in found if f["when"])

    @command("usbhistory", group=G, usage="/usbhistory", help="every USB drive that has been plugged into this PC",
             title="USB device history", icon="🔌", page="security")
    def usbhistory_cmd(self, args: str, routed: bool = False):
        found = usb_history()
        if not found:
            return "No USB storage history found."
        lines = [f"🔌 {len(found)} USB storage device(s):"]
        for d in found:
            last = d["arrived"] or d["first"]
            lines.append(f"  {'🟢' if d['present'] else '⚪'} {d['name'][:44]:<44} last {last:%d %b %Y %H:%M}" if last
                         else f"  {'🟢' if d['present'] else '⚪'} {d['name'][:44]}")
        return "\n".join(lines)

    @command("stripmeta", "removegps", group=G, usage="/stripmeta <photo or folder> [| in place]",
             help="removes GPS location and camera details from photos (saves clean copies)",
             title="Remove photo GPS and metadata", icon="📍", page="security",
             fields=(field("path", "files", "Photos (or a folder)", types=(("Pictures", "*.jpg *.jpeg *.png *.webp"),)),
                     field("mode", "choice", "Save as", "copies", ("copies", "in place"))))
    def stripmeta_cmd(self, args: str, routed: bool = False):
        text, mode = split(args, 2)
        targets: list[Path] = []
        for part in text.split(";"):
            path = Path(part.strip().strip('"'))
            if path.is_dir():
                targets += [p for p in path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".tif",
                                                                               ".tiff"}]
            elif path.is_file():
                targets.append(path)
        if not targets:
            return "Usage: /stripmeta <photo or folder>"
        in_place = mode.strip().lower() == "in place"
        if in_place and not security.permissions.ask(security.WRITE_FILE, f"rewrite {len(targets)} photo(s)",
                                                     context="/stripmeta"):
            return "Left them as they were."
        removed, gps = 0, 0
        for path in targets[:500]:
            try:
                _target, found = strip_metadata(path, in_place)
            except Exception:
                continue
            removed += 1
            gps += any("GPS" in f for f in found)
        return f"📍 Cleaned {removed} photo(s); {gps} had a GPS location." + ("" if in_place else
                                                                               " Clean copies end in _clean.")

    @command("virustotal", "vt", group=G, usage="/virustotal <file>", help="what 70+ antivirus engines say about a file "
             "(by its fingerprint — the file isn't uploaded)", title="VirusTotal check", icon="🔬", page="antivirus",
             fields=(field("file", "file", "File"),))
    def virustotal_cmd(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /virustotal <file>"
        try:
            result = virustotal(path)
        except PermissionError as exc:
            return str(exc)
        except Exception as exc:
            return f"VirusTotal didn't answer: {exc}"
        if not result["known"]:
            return (f"🔬 VirusTotal has never seen this file (SHA-256 {result['sha256'][:16]}…). That's normal for your "
                    "own files. Your file was not uploaded.")
        s = result["stats"]
        bad = s.get("malicious", 0) + s.get("suspicious", 0)
        total = sum(s.values()) or 1
        verdict = "✅ clean" if bad == 0 else "⚠ flagged" if bad < 4 else "⛔ malicious"
        return (f"🔬 {path.name}: {verdict} — {bad}/{total} engines flag it" +
                (f" ({result['label']})" if result.get("label") else "") +
                (f"\n  Names: {', '.join(result['names'])}" if result["names"] and bad else "") + f"\n  {result['link']}")

    @command("vpncheck", "ipleak", group=G, usage="/vpncheck", help="what the internet sees: your public IP, ISP, "
             "location, and whether a VPN is hiding them", title="VPN and IP leak check", icon="🕶", page="security")
    def vpncheck_cmd(self, args: str, routed: bool = False):
        try:
            info = public_ip()
        except kit.KitError as exc:
            return f"Couldn't reach the IP checker: {exc}"
        conn = info.get("connection") or {}
        provider = f"{conn.get('isp') or ''} {conn.get('org') or ''}".strip()
        hosted = bool(HOSTING.search(provider))
        lines = [f"🕶 The internet sees: {info.get('ip')} — {info.get('city', '')}, {info.get('country', '')}",
                 f"  Provider: {provider or 'unknown'} (AS{conn.get('asn', '')})"]
        lines.append("  ✅ Looks like a VPN or hosting network — your home IP is hidden." if hosted else
                     "  ℹ This looks like a home/mobile ISP — no VPN is hiding you (that's fine if you don't use one).")
        if info.get("ipv6"):
            lines.append(f"  IPv6 also visible: {info['ipv6']}" + (" — if you use a VPN, check it covers IPv6." if hosted
                                                                     else ""))
        dns = ps_json("Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                      "Where-Object {$_.ServerAddresses} | Select -Expand ServerAddresses")
        if dns:
            lines.append(f"  DNS servers: {', '.join(str(d) for d in dns[:4])}")
        return "\n".join(lines)

    @command("secnews", "securitynews", group=G, usage="/secnews [summary]", help="the latest security news",
             title="Security news digest", icon="📰", page="security",
             fields=(field("style", "choice", "Style", "headlines", ("headlines", "summary")),))
    def secnews_cmd(self, args: str, routed: bool = False):
        items = security_news()
        if not items:
            return "Couldn't fetch the security news right now."
        lines = [f"📰 {i['title']}  ({i['source']})\n   {i['link']}" for i in items]
        if args.strip().lower() == "summary":
            from .. import shield

            wrapped, _ = shield.wrap("\n".join(i["title"] for i in items), "headlines")
            take = self.brain.ask_once(f"{shield.RULE}\nFrom these security headlines, say in 3-5 short bullets what a "
                                       f"normal Windows user should actually do this week.\n\n{wrapped}")
            return take.strip() + "\n\n" + "\n".join(lines)
        return "\n".join(lines)

    # --- antivirus -------------------------------------------------------------------------
    @command("avscan", "virusscan", group=G, usage="/avscan quick|full · /avscan <file or folder>",
             help="a Defender scan: quick, full, or a file or folder", title="Antivirus scan", icon="🦠",
             page="antivirus", fields=(field("what", "text", "quick, full, or a file/folder path", "quick"),))
    def avscan_cmd(self, args: str, routed: bool = False):
        what = args.strip().strip('"') or "quick"
        if what.lower() in {"quick", "full"}:
            return scanner.start(what.lower())
        path = Path(what)
        if not path.exists():
            return "Usage: /avscan quick · /avscan full · /avscan <file or folder>"
        return scanner.start("custom", str(path))

    @command("avschedule", group=G, usage="/avschedule daily 13:00 · /avschedule weekly 20:00 · /avschedule off",
             help="a quick scan on a schedule (while JARVIS is open)", title="Scheduled scans", icon="📆",
             page="antivirus", fields=(field("when", "choice", "How often", "daily", ("daily", "weekly", "off")),
                                       field("time", "time", "At", "13:00")), template="{when} {time}")
    def avschedule_cmd(self, args: str, routed: bool = False):
        settings = AV_SETTINGS.load()
        text = args.strip().lower()
        if text.startswith("off"):
            settings["schedule"] = ""
            AV_SETTINGS.save(settings)
            return "📆 Scheduled scans off."
        m = re.match(r"(daily|weekly)\s+(\d{1,2}):(\d{2})", text)
        if not m:
            return f"📆 Schedule: {settings.get('schedule') or 'off'}. Set one: /avschedule daily 13:00"
        settings["schedule"] = f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}"
        AV_SETTINGS.save(settings)
        return f"📆 A quick scan runs {m.group(1)} at {int(m.group(2)):02d}:{m.group(3)} while JARVIS is open."

    @command("usbscan", group=G, usage="/usbscan on|off", help="scan USB drives as soon as they're plugged in",
             title="Auto-scan USB drives", icon="🔌", page="antivirus",
             fields=(field("state", "choice", "Auto-scan", "on", ("on", "off")),))
    def usbscan_cmd(self, args: str, routed: bool = False):
        settings = AV_SETTINGS.load()
        if args.strip().lower() in {"on", "off"}:
            settings["usb_scan"] = args.strip().lower() == "on"
            AV_SETTINGS.save(settings)
        return f"🔌 Auto-scan of USB drives is {'on' if settings.get('usb_scan', True) else 'off'}."

    @command("threats", group=G, usage="/threats", help="what Defender has found and what it did about it",
             title="Threat history", icon="☣", page="antivirus")
    def threats_cmd(self, args: str, routed: bool = False):
        found = threats()
        if not found:
            return "✅ Defender has no threat history on this PC."
        return "☣ Threats Defender found:\n" + "\n".join(
            f"  {t['when']:%d %b %Y %H:%M}  {t['name']} ({t['severity'] or '?'}) — "
            f"{'handled' if t['handled'] else 'NEEDS ACTION'}" + (f"\n      {t['where'][0][:90]}" if t["where"] else "")
            for t in found if t["when"])

    @command("avupdate", group=G, usage="/avupdate", help="updates Defender's virus definitions",
             title="Update virus definitions", icon="⬇", page="antivirus")
    def avupdate_cmd(self, args: str, routed: bool = False):
        if not MPCMD.exists():
            return "Defender's updater isn't available on this PC."
        try:
            proc = subprocess.run([str(MPCMD), "-SignatureUpdate"], capture_output=True, timeout=600,
                                  creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return "The update took too long — Windows Update will retry by itself."
        out = proc.stdout.decode("utf-8", "replace").strip().splitlines()
        return ("⬇ Definitions updated." if proc.returncode == 0 else
                "⚠ Defender said: " + (out[-1] if out else f"exit {proc.returncode}") +
                " (updating may need administrator rights; Windows Update also does it daily).")
