"""10.0 PC: live load and temperatures, battery and disk health, Downloads
that sort themselves, zip/unzip and RAR/7z, winget, keeping the PC awake,
blue screens explained, network use per app, and IP/DNS details.

Readings come from psutil, Windows' own tools (powercfg, Get-PhysicalDisk,
the event log) and nvidia-smi when there is an NVIDIA card. When Windows
doesn't expose something to a normal user — CPU temperature on many PCs —
the answer says so instead of inventing a number.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import psutil

from .. import alerts, kit, security
from ..registry import command, field, split

G = "PC and files"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AUTOSORT = kit.Store("autosort.json", {"on": False, "folder": ""})


def powershell(script: str, timeout: int = 30) -> str:
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                               "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                              capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def ps_json(script: str, timeout: int = 30):
    out = powershell(f"{script} | ConvertTo-Json -Depth 4 -Compress", timeout)
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


# --- load and temperatures ----------------------------------------------------------------

def nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    if not Path(exe).exists() and not shutil.which("nvidia-smi"):
        return []
    try:
        proc = subprocess.run([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
                                    "power.draw,fan.speed", "--format=csv,noheader,nounits"],
                              capture_output=True, timeout=8, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            def num(v):
                try:
                    return float(v)
                except ValueError:
                    return None
            gpus.append({"name": parts[0], "load": num(parts[1]), "mem_used": num(parts[2]), "mem_total": num(parts[3]),
                         "temp": num(parts[4]), "power": num(parts[5]) if len(parts) > 5 else None,
                         "fan": num(parts[6]) if len(parts) > 6 else None})
    return gpus


def gpu_load_counters() -> float | None:
    """3D engine use across all GPUs, from Windows' performance counters (any vendor)."""
    out = powershell("(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue)"
                     ".CounterSamples | Measure-Object CookedValue -Sum | Select -Expand Sum", timeout=12)
    try:
        return min(100.0, float(out.replace(",", ".")))
    except ValueError:
        return None


def cpu_temperature() -> float | None:
    """°C from the ACPI thermal zones Windows exposes without admin, or None."""
    rows = ps_json("Get-CimInstance -Namespace root/cimv2 Win32_PerfFormattedData_Counters_ThermalZoneInformation "
                   "-ErrorAction SilentlyContinue | Select HighPrecisionTemperature, Temperature", timeout=12)
    temps = []
    for row in rows:
        value = row.get("HighPrecisionTemperature") or 0
        kelvin = value / 10 if value > 1000 else row.get("Temperature") or 0
        if 250 < kelvin < 400:
            temps.append(kelvin - 273.15)
    return round(max(temps), 1) if temps else None


def snapshot() -> dict:
    """What the PC page shows every couple of seconds (cheap parts only)."""
    mem = psutil.virtual_memory()
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return {"cpu": psutil.cpu_percent(None), "cores": psutil.cpu_percent(None, percpu=True), "ram": mem.percent,
            "ram_used": mem.used, "ram_total": mem.total,
            "battery": battery.percent if battery else None, "plugged": battery.power_plugged if battery else None,
            "net": psutil.net_io_counters()}


# --- battery and disks -------------------------------------------------------------------------

def battery_report() -> dict:
    path = kit.output_dir("documents") / f"battery-report_{kit.stamp()}.html"
    try:
        subprocess.run(["powercfg", "/batteryreport", "/output", str(path), "/duration", "14"], capture_output=True,
                       timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if not path.exists():
        return {}
    html = path.read_text(encoding="utf-8", errors="replace")

    def grab(label: str) -> float | None:
        m = re.search(label + r"</span></td><td>([\d,. ]+)\s*mWh", html, re.I)
        if not m:
            m = re.search(label + r"\s*</td>\s*<td[^>]*>\s*([\d,. ]+)\s*mWh", html, re.I)
        if m:
            return float(re.sub(r"[^\d]", "", m.group(1)) or 0)
        return None

    design = grab("DESIGN CAPACITY")
    full = grab("FULL CHARGE CAPACITY")
    cycles = re.search(r"CYCLE COUNT\s*</span></td><td>\s*([\d,.]+|-)", html, re.I) or \
        re.search(r"CYCLE COUNT\s*</td>\s*<td[^>]*>\s*([\d,.]+|-)", html, re.I)
    return {"path": path, "design": design, "full": full,
            "health": round(100 * full / design, 1) if design and full else None,
            "cycles": cycles.group(1) if cycles else None}


def disks() -> list[dict]:
    rows = ps_json("Get-PhysicalDisk | Select FriendlyName, MediaType, HealthStatus, OperationalStatus, Size, BusType, "
                   "DeviceId", timeout=20)
    counters = {str(r.get("DeviceId")): r for r in ps_json(
        "Get-PhysicalDisk | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue | "
        "Select DeviceId, Temperature, Wear, ReadErrorsTotal, WriteErrorsTotal, PowerOnHours", timeout=20)}
    out = []
    for r in rows:
        extra = counters.get(str(r.get("DeviceId")), {})
        out.append({"name": r.get("FriendlyName"), "type": {3: "HDD", 4: "SSD"}.get(r.get("MediaType"), "disk"),
                    "health": {0: "Healthy", 1: "Warning", 2: "Unhealthy"}.get(r.get("HealthStatus"),
                                                                               str(r.get("HealthStatus"))),
                    "size": r.get("Size"), "bus": {7: "USB", 11: "SATA", 17: "NVMe"}.get(r.get("BusType"), ""),
                    "temp": extra.get("Temperature") or None, "wear": extra.get("Wear"),
                    "errors": (extra.get("ReadErrorsTotal") or 0) + (extra.get("WriteErrorsTotal") or 0),
                    "hours": extra.get("PowerOnHours")})
    return out


# --- keep awake ----------------------------------------------------------------------------------

class Awake:
    ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x00000001, 0x00000002

    def __init__(self) -> None:
        self.until = 0.0
        self.display = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def on(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, seconds: float = 0, display: bool = True) -> None:
        self.stop()
        self.until = time.time() + seconds if seconds else 0.0
        self.display = display
        self._stop.clear()
        self._thread = threading.Thread(target=self._hold, daemon=True, name="jarvis-awake")
        self._thread.start()

    @staticmethod
    def supported() -> bool:
        """Windows (SetThreadExecutionState) or macOS (its built-in caffeinate)."""
        return sys.platform == "win32" or (sys.platform == "darwin" and shutil.which("caffeinate") is not None)

    def _hold(self) -> None:
        if sys.platform == "darwin":
            self._hold_mac()
            return
        flags = self.ES_CONTINUOUS | self.ES_SYSTEM | (self.ES_DISPLAY if self.display else 0)
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            while not self._stop.wait(20):
                if self.until and time.time() >= self.until:
                    break
        except AttributeError:
            return
        finally:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
            except AttributeError:
                pass

    def _hold_mac(self) -> None:
        try:
            proc = subprocess.Popen(["caffeinate", "-i"] + (["-d"] if self.display else []))
        except OSError:
            return
        try:
            while not self._stop.wait(20):
                if self.until and time.time() >= self.until:
                    break
        finally:
            proc.terminate()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None


awake = Awake()

# --- blue screens --------------------------------------------------------------------------------

BUGCHECKS = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "a driver touched memory it shouldn't — usually a faulty or outdated driver"),
    0x1A: ("MEMORY_MANAGEMENT", "memory trouble — test the RAM (Windows Memory Diagnostic) and update drivers"),
    0x1E: ("KMODE_EXCEPTION_NOT_HANDLED", "a driver crashed — check recently installed drivers or software"),
    0x24: ("NTFS_FILE_SYSTEM", "the disk or file system — run chkdsk and check disk health"),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "a system or graphics driver failed — update the GPU driver and Windows"),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "bad memory or a driver/antivirus bug — test RAM, update drivers"),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "a driver thread crashed — the dump names it; update or roll it back"),
    0x7F: ("UNEXPECTED_KERNEL_MODE_TRAP", "hardware (RAM, overclock, overheating) or a driver"),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "a driver failed during sleep/wake — update chipset, Wi-Fi and GPU drivers"),
    0xBE: ("ATTEMPTED_WRITE_TO_READONLY_MEMORY", "a buggy driver"),
    0xC2: ("BAD_POOL_CALLER", "a driver misused memory — update drivers, check antivirus"),
    0xD1: ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "a network, storage or graphics driver — update it"),
    0xEF: ("CRITICAL_PROCESS_DIED", "a core Windows process stopped — run sfc /scannow and DISM"),
    0xF4: ("CRITICAL_OBJECT_TERMINATION", "a critical process ended — often a failing disk"),
    0x101: ("CLOCK_WATCHDOG_TIMEOUT", "a CPU core stopped responding — overclock, BIOS or CPU issue"),
    0x116: ("VIDEO_TDR_FAILURE", "the graphics driver stopped responding — update or reinstall the GPU driver"),
    0x124: ("WHEA_UNCORRECTABLE_ERROR", "a hardware error (CPU, RAM, PSU, overheating, overclock)"),
    0x133: ("DPC_WATCHDOG_VIOLATION", "a driver took too long — often SSD firmware or storage drivers"),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "corrupted data or a driver — update drivers, check RAM"),
    0x13A: ("KERNEL_MODE_HEAP_CORRUPTION", "a driver corrupted memory"),
    0x154: ("UNEXPECTED_STORE_EXCEPTION", "the disk — check its health and SSD firmware"),
    0x19: ("BAD_POOL_HEADER", "memory corruption by a driver"),
    0x7B: ("INACCESSIBLE_BOOT_DEVICE", "Windows can't reach the boot disk — storage driver or BIOS mode"),
    0xC000021A: ("STATUS_SYSTEM_PROCESS_TERMINATED", "a system process failed — use Startup Repair"),
}


def crashes(limit: int = 15) -> list[dict]:
    rows = ps_json("Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001,41} -MaxEvents 60 "
                   "-ErrorAction SilentlyContinue | Select TimeCreated, Id, ProviderName, Message", timeout=30)
    out = []
    for r in rows:
        message = str(r.get("Message") or "")
        provider = str(r.get("ProviderName") or "")
        when = _ps_date(r.get("TimeCreated"))
        if r.get("Id") == 1001 and ("BugCheck" in provider or "bugcheck" in message.lower()):
            m = re.search(r"0x([0-9a-fA-F]{8,16})", message)
            code = int(m.group(1), 16) if m else None
            out.append({"when": when, "code": code, "kind": "blue screen"})
        elif r.get("Id") == 41:
            out.append({"when": when, "code": None, "kind": "unexpected shutdown (power loss or hard reset)"})
        if len(out) >= limit:
            break
    return out


def _ps_date(value) -> datetime | None:
    if isinstance(value, dict):
        # Some dates come wrapped: Get-HotFix's InstalledOn is
        # {"value": "/Date(…)/", "DateTime": "…"}. Read as "unknown", it once
        # failed "Windows updated in the last 45 days" on a PC updated 25 days before.
        value = value.get("value")
    if isinstance(value, str):
        m = re.search(r"/Date\((\d+)", value)
        if m:
            return datetime.fromtimestamp(int(m.group(1)) / 1000)
        try:
            return datetime.fromisoformat(value[:19])
        except ValueError:
            return None
    return None


def explain_bugcheck(code: int | None) -> str:
    if code is None:
        return "no stop code recorded"
    name, why = BUGCHECKS.get(code, BUGCHECKS.get(code & 0xFFFF, ("", "")))
    return f"0x{code:08X} {name} — {why}" if name else f"0x{code:08X} (search this code with your PC model)"


# --- network --------------------------------------------------------------------------------------

def app_connections() -> list[dict]:
    by_pid: dict[int, dict] = {}
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        conns = []
    for c in conns:
        if not c.pid or not c.raddr:
            continue
        entry = by_pid.setdefault(c.pid, {"pid": c.pid, "count": 0, "remotes": set()})
        entry["count"] += 1
        entry["remotes"].add(c.raddr.ip)
    out = []
    for pid, entry in by_pid.items():
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            io = proc.io_counters() if hasattr(proc, "io_counters") else None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        out.append({"name": name, "pid": pid, "connections": entry["count"], "hosts": len(entry["remotes"]),
                    "other_bytes": getattr(io, "other_bytes", 0) if io else 0})
    out.sort(key=lambda e: (-e["connections"], e["name"].lower()))
    return out


def ip_info() -> dict:
    adapters = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if not st or not st.isup:
            continue
        v4 = [a.address for a in addrs if a.family == socket.AF_INET and not a.address.startswith("169.254")]
        v6 = [a.address.split("%")[0] for a in addrs if a.family == socket.AF_INET6 and
              not a.address.lower().startswith("fe80")]
        mac = next((a.address for a in addrs if a.family == psutil.AF_LINK), "")
        if v4 or v6:
            adapters.append({"name": name, "ipv4": v4, "ipv6": v6, "mac": mac, "speed": st.speed})
    dns = ps_json("Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                  "Where-Object {$_.ServerAddresses} | Select InterfaceAlias, ServerAddresses", timeout=15)
    gateway = powershell("(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
                         "Sort-Object RouteMetric | Select -First 1).NextHop", timeout=15)
    public = {}
    try:
        public = kit.get_json("https://ipwho.is/", timeout=10)
    except kit.KitError:
        pass
    return {"adapters": adapters, "dns": dns, "gateway": gateway, "public": public}


# --- archives ---------------------------------------------------------------------------------------

def seven_zip() -> str | None:
    for candidate in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def extract(archive: Path, target: Path) -> tuple[Path, str]:
    target.mkdir(parents=True, exist_ok=True)
    suffix = "".join(archive.suffixes[-2:]).lower()
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                resolved = (target / member).resolve()
                if not str(resolved).startswith(str(target.resolve())):
                    raise ValueError(f"Refused: {member} would land outside the folder.")
            z.extractall(target)
        return target, "zip"
    tool = seven_zip()
    if tool:
        proc = subprocess.run([tool, "x", "-y", f"-o{target}", str(archive)], capture_output=True, timeout=1800,
                              creationflags=NO_WINDOW)
        if proc.returncode == 0:
            return target, "7-Zip"
    if suffix.endswith((".tar.gz", ".tgz", ".tar", ".tar.bz2", ".tar.xz")) or archive.suffix.lower() in {
            ".rar", ".7z", ".gz", ".tgz", ".tar", ".xz", ".bz2"}:
        tar = shutil.which("tar") or r"C:\Windows\System32\tar.exe"
        proc = subprocess.run([tar, "-xf", str(archive), "-C", str(target)], capture_output=True, timeout=1800,
                              creationflags=NO_WINDOW)
        if proc.returncode == 0:
            return target, "Windows tar"
        raise ValueError("Windows can't open this archive by itself. Install 7-Zip (free, 7-zip.org) and try again.")
    raise ValueError("I can open .zip, .7z, .rar and .tar archives.")


def zip_paths(paths: list[Path], target: Path) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in paths:
            if path.is_dir():
                for sub in path.rglob("*"):
                    if sub.is_file():
                        z.write(sub, Path(path.name) / sub.relative_to(path))
            elif path.is_file():
                z.write(path, path.name)
    return target


# --- winget ---------------------------------------------------------------------------------------------

def winget(*argv: str, timeout: int = 120) -> tuple[int, str]:
    exe = shutil.which("winget")
    if not exe:
        raise FileNotFoundError("winget isn't available — get 'App Installer' from the Microsoft Store.")
    proc = subprocess.run([exe, *argv, "--accept-source-agreements", "--disable-interactivity"], capture_output=True,
                          timeout=timeout, creationflags=NO_WINDOW)
    text = proc.stdout.decode("utf-8", "replace")
    text = re.sub(r"[\r]+", "\n", text)
    text = "\n".join(line for line in text.splitlines() if line.strip() and not set(line.strip()) <= set("-\\|/ █▒"))
    return proc.returncode, text


def parse_winget_table(text: str) -> list[dict]:
    lines = text.splitlines()
    header_i = next((i for i, l in enumerate(lines) if l.startswith("Name") and " Id " in l), None)
    if header_i is None:
        return []
    header = lines[header_i]
    cols = [(m.start(), m.group(0).strip()) for m in re.finditer(r"\S+\s*", header)]
    rows = []
    for line in lines[header_i + 2:]:
        if len(line) < cols[-1][0]:
            continue
        row = {}
        for k, (start, name) in enumerate(cols):
            end = cols[k + 1][0] if k + 1 < len(cols) else None
            row[name] = line[start:end].strip()
        if row.get("Id"):
            rows.append(row)
    return rows


# --- watchers ----------------------------------------------------------------------------------------------

def register_watchers(jarvis, watchers) -> None:
    from ..config import get_setting

    state = {"low": False}

    def battery():
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b is None:
            return
        threshold = float(get_setting("JARVIS_BATTERY_ALERT", "20") or 20)
        if not b.power_plugged and b.percent <= threshold and not state["low"]:
            state["low"] = True
            alerts.post(f"Battery low: {b.percent:.0f}%", "Plug in soon.", page="pc", kind="warn")
        elif b.power_plugged or b.percent > threshold + 5:
            state["low"] = False

    watchers.add("battery", 60, battery, first_after=20)

    def autosort():
        settings = AUTOSORT.load()
        if not settings.get("on"):
            return
        from .. import tidy

        folder = Path(settings.get("folder") or Path.home() / "Downloads")
        if not folder.is_dir():
            return
        moves = tidy.plan(folder)
        if moves:
            moved, _problems = tidy.apply(moves)
            if moved:
                alerts.post(f"Sorted {moved} download(s)", f"into folders in {folder.name}", page="pc")

    watchers.add("autosort", 120, autosort, first_after=60)


class System:
    @command("temps", "temperature", group=G, usage="/temps", help="CPU and GPU temperatures and load",
             title="CPU and GPU temperatures", icon="🌡", page="pc")
    def temps_cmd(self, args: str, routed: bool = False):
        lines = [f"🌡 CPU load {psutil.cpu_percent(0.5):.0f}%"]
        cpu = cpu_temperature()
        lines.append(f"  CPU: {cpu:.0f} °C" if cpu is not None else
                     "  CPU temperature: Windows doesn't share it on this PC without extra tools (HWiNFO, "
                     "LibreHardwareMonitor).")
        gpus = nvidia()
        for g in gpus:
            lines.append(f"  GPU {g['name']}: {g['temp']:.0f} °C, load {g['load']:.0f}%, memory "
                         f"{g['mem_used']:.0f}/{g['mem_total']:.0f} MB" + (f", {g['power']:.0f} W" if g["power"] else ""))
        if not gpus:
            load = gpu_load_counters()
            lines.append(f"  GPU load {load:.0f}% (temperature only shown for NVIDIA cards)" if load is not None
                         else "  GPU: no readings available.")
        return "\n".join(lines)

    @command("battery", "batteryhealth", group=G, usage="/battery", help="battery health: capacity left, cycles",
             title="Battery health report", icon="🔋", page="pc")
    def battery_cmd(self, args: str, routed: bool = False):
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b is None:
            return "This PC has no battery."
        report = battery_report()
        lines = [f"🔋 {b.percent:.0f}% — " + ("charging" if b.power_plugged else
                                             f"{b.secsleft // 3600}h {b.secsleft % 3600 // 60}m left"
                                             if b.secsleft and b.secsleft > 0 else "on battery")]
        if report.get("health"):
            verdict = "good" if report["health"] >= 80 else "worn" if report["health"] >= 60 else "consider replacing"
            lines.append(f"  Health {report['health']}% ({verdict}): holds {report['full']:,.0f} of "
                         f"{report['design']:,.0f} mWh it was built for")
        if report.get("cycles") and report["cycles"] != "-":
            lines.append(f"  Charge cycles: {report['cycles']}")
        if report.get("path"):
            lines.append(f"  Full report: {report['path']}")
        return "\n".join(lines)

    @command("diskhealth", "disks", group=G, usage="/diskhealth", help="your drives' health, temperature and wear",
             title="Disk health", icon="💽", page="pc")
    def diskhealth_cmd(self, args: str, routed: bool = False):
        found = disks()
        if not found:
            return "Windows didn't report any disks."
        lines = ["💽 Disks:"]
        for d in found:
            extras = [f"{d['temp']} °C" if d["temp"] else "", f"wear {d['wear']}%" if d["wear"] not in (None, 0) else "",
                      f"{d['errors']} errors" if d["errors"] else "", f"{d['hours']:,} h on" if d["hours"] else ""]
            icon = "✅" if d["health"] == "Healthy" else "⚠"
            lines.append(f"  {icon} {d['name']} ({d['type']} {d['bus']}, {kit.size(d['size'] or 0)}): {d['health']}"
                         + (" · " + " · ".join(e for e in extras if e) if any(extras) else ""))
        for part in psutil.disk_partitions():
            try:
                use = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            lines.append(f"  {part.mountpoint} {use.percent:.0f}% full ({kit.size(use.free)} free)")
        return "\n".join(lines)

    @command("autosort", group=G, usage="/autosort on|off|now|undo [folder]",
             help="keeps Downloads sorted into folders by type, by itself", title="Downloads auto-sort", icon="🗂",
             page="pc", fields=(field("action", "choice", "Action", "now", ("on", "off", "now", "undo")),
                                field("folder", "folder", "Folder (blank: Downloads)", optional=True)),
             template="{action} {folder}")
    def autosort_cmd(self, args: str, routed: bool = False):
        from .. import tidy

        verb, _, folder = args.strip().partition(" ")
        verb = (verb or "now").lower()
        target = Path(folder.strip().strip('"')) if folder.strip() else Path.home() / "Downloads"
        if verb == "on":
            AUTOSORT.save({"on": True, "folder": str(target)})
            return f"🗂 Auto-sort is on for {target}: new files are moved into folders by type every few minutes. " \
                   "/autosort undo puts the last batch back."
        if verb == "off":
            AUTOSORT.save({"on": False, "folder": str(target)})
            return "🗂 Auto-sort is off."
        if verb == "undo":
            return tidy.undo()
        if not target.is_dir():
            return f"No folder {target}"
        moves = tidy.plan(target)
        if not moves:
            return f"{target.name} is already tidy."
        if not security.permissions.ask(security.WRITE_FILE, f"move {len(moves)} file(s) in {target}",
                                        context="/autosort"):
            return tidy.describe(target, moves)
        moved, problems = tidy.apply(moves)
        return f"🗂 Moved {moved} file(s) into folders." + (f" {len(problems)} skipped." if problems else "") + \
            " /autosort undo reverses it."

    @command("zip", group=G, usage="/zip <file or folder> [| more …] [| name.zip]", help="pack files into a .zip",
             title="Zip files", icon="🗜", page="pc",
             fields=(field("paths", "files", "Files (or a folder)"), field("name", "text", "Zip name", optional=True)))
    def zip_cmd(self, args: str, routed: bool = False):
        parts = [p.strip().strip('"') for p in re.split(r"\s*\|\s*|;", args) if p.strip()]
        name = parts.pop() if parts and parts[-1].lower().endswith(".zip") and not Path(parts[-1]).exists() else ""
        paths = [Path(p) for p in parts if Path(p).exists()]
        if not paths:
            return "Usage: /zip <file or folder> [| another] [| name.zip]"
        target = (paths[0].parent / (name or f"{paths[0].stem}.zip"))
        if target.exists():
            target = target.with_name(f"{target.stem}_{kit.stamp()}.zip")
        zip_paths(paths, target)
        return f"🗜 {target.name} ({kit.size(target.stat().st_size)}):\n  {target}"

    @command("unzip", "extract", group=G, usage="/unzip <archive.zip|.7z|.rar|.tar.gz> [| folder]",
             help="unpacks zip, 7z, rar and tar archives", title="Unzip / open RAR and 7z", icon="📦", page="pc",
             fields=(field("archive", "file", "Archive", types=(("Archives", "*.zip *.7z *.rar *.tar *.gz *.tgz"),)),
                     field("folder", "folder", "Into (blank: next to it)", optional=True)))
    def unzip_cmd(self, args: str, routed: bool = False):
        archive_text, folder = split(args, 2)
        archive = kit.path_arg(archive_text)
        if archive is None or not archive.is_file():
            return "Usage: /unzip <archive>"
        target = Path(folder.strip().strip('"')) if folder else archive.parent / archive.name.split(".")[0]
        try:
            where, how = extract(archive, target)
        except (ValueError, zipfile.BadZipFile, OSError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't open {archive.name}: {exc}"
        count = sum(1 for _ in where.rglob("*"))
        return f"📦 Extracted {count} item(s) with {how}:\n  {where}"

    @command("winget", "install", group=G, usage="/winget search <app> · /winget install <id> · /winget upgrades · /winget list",
             help="find, install and update apps with Windows' package manager", title="Install apps (winget)",
             icon="📥", page="pc", fields=(field("action", "choice", "Action", "search", ("search", "install", "upgrades",
                                                                                          "list")),
                                           field("app", "text", "App name or id", optional=True)),
             template="{action} {app}")
    def winget_cmd(self, args: str, routed: bool = False):
        verb, _, what = args.strip().partition(" ")
        verb = (verb or "search").lower()
        what = what.strip()
        try:
            if verb == "search":
                if not what:
                    return "Usage: /winget search vlc"
                code, out = winget("search", what, "--count", "15")
                rows = parse_winget_table(out)
                if not rows:
                    return out[-1500:] or "Nothing found."
                return "📥 Found:\n" + "\n".join(f"  {r.get('Name', '')[:34]:<34} {r.get('Id', ''):<36} {r.get('Version', '')}"
                                                for r in rows) + "\nInstall: /winget install <Id>"
            if verb == "install":
                if not re.fullmatch(r"[\w.+-]{2,100}", what):
                    return "Give the app's id from /winget search, e.g. /winget install VideoLAN.VLC"
                if not security.permissions.ask(security.RUN_COMMAND, f"winget install --id {what}", context="/winget"):
                    return "Not installed."
                code, out = winget("install", "--id", what, "--exact", "--silent", "--accept-package-agreements",
                                   timeout=1800)
                security.audit.record("winget install", what, f"exit {code}")
                return ("📥 Installed " + what if code == 0 else "⚠ winget said:\n" + out[-1500:])
            if verb in {"upgrades", "upgrade", "updates"}:
                code, out = winget("upgrade", timeout=180)
                rows = parse_winget_table(out)
                if not rows:
                    return "✅ Everything winget manages is up to date."
                return f"📥 {len(rows)} update(s):\n" + "\n".join(
                    f"  {r.get('Name', '')[:30]:<30} {r.get('Version', '')} → {r.get('Available', '')}" for r in rows) + \
                    "\nUpdate one: /winget install <Id>   (or run 'winget upgrade --all' yourself)"
            if verb == "list":
                code, out = winget("list", timeout=180)
                rows = parse_winget_table(out)
                return f"📥 {len(rows)} apps installed." + "\n" + "\n".join(
                    f"  {r.get('Name', '')[:40]}" for r in rows[:60])
        except FileNotFoundError as exc:
            return str(exc)
        except OSError as exc:                 # there, but it wouldn't start (blocked, broken install…)
            return f"winget wouldn't start: {exc}"
        except subprocess.TimeoutExpired:
            return "winget took too long."
        return "Usage: /winget search|install|upgrades|list"

    @command("awake", "keepawake", "caffeine", group=G, usage="/awake on [for 2h] · /awake off",
             help="stops the PC (and screen) going to sleep", title="Keep PC awake", icon="☕", page="pc",
             fields=(field("action", "choice", "Action", "on", ("on", "off")),
                     field("hours", "text", "For how long (blank: until off)", optional=True)),
             template="{action} {hours}")
    def awake_cmd(self, args: str, routed: bool = False):
        text = args.strip().lower()
        if text.startswith("off") or text == "stop":
            awake.stop()
            return "☕ Off — the PC can sleep normally again."
        if not text or text.startswith("on") or re.search(r"\d", text):
            if not awake.supported():
                return "☕ Keeping the PC awake works on Windows and macOS."
            m = re.search(r"(\d+(?:\.\d+)?)\s*(h|hour|hours|m|min|minutes)?", text)
            seconds = 0
            if m:
                seconds = float(m.group(1)) * (60 if (m.group(2) or "h").startswith("m") else 3600)
            awake.start(seconds, display="screen off" not in text)
            return "☕ Keeping the PC awake" + (f" for {seconds / 3600:g} h." if seconds else " until /awake off.")
        return "☕ " + ("On." if awake.on else "Off.") + " /awake on [for 2h] · /awake off"

    @command("bsod", "bluescreen", group=G, usage="/bsod · /bsod 0x0000001A",
             help="explains blue screens and sudden shutdowns from Windows' log", title="Blue screen explainer",
             icon="🟦", page="pc", fields=(field("code", "text", "Stop code (blank: read my crash history)",
                                                optional=True),))
    def bsod_cmd(self, args: str, routed: bool = False):
        code_text = args.strip()
        if code_text:
            m = re.search(r"(?:0x)?([0-9a-fA-F]{1,16})", code_text)
            name_match = next((code for code, (name, _) in BUGCHECKS.items() if name.lower() == code_text.lower()), None)
            code = name_match if name_match is not None else int(m.group(1), 16) if m else None
            return "🟦 " + explain_bugcheck(code)
        found = crashes()
        if not found:
            return "✅ No blue screens or unexpected shutdowns in Windows' recent log."
        lines = ["🟦 Recent crashes:"]
        for c in found:
            when = f"{c['when']:%d %b %Y %H:%M}" if c["when"] else "?"
            lines.append(f"  {when}  {c['kind']}" + (f": {explain_bugcheck(c['code'])}" if c["kind"] == "blue screen"
                                                      else ""))
        codes = Counter_codes(found)
        if codes:
            lines.append(f"Most common: {explain_bugcheck(codes)}")
        dumps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Minidump"
        try:
            count = len(list(dumps.glob("*.dmp")))
            if count:
                lines.append(f"{count} crash dump(s) in {dumps} — WinDbg can name the exact driver.")
        except OSError:
            pass
        return "\n".join(lines)

    @command("netapps", "networkuse", group=G, usage="/netapps", help="which apps are using the network right now",
             title="Network use per app", icon="📶", page="pc")
    def netapps_cmd(self, args: str, routed: bool = False):
        apps = app_connections()
        if not apps:
            return "No apps have open internet connections (or Windows didn't let me see them)."
        lines = ["📶 Apps talking to the internet now:"]
        lines += [f"  {a['name'][:30]:<30} {a['connections']:>3} connection(s) to {a['hosts']} host(s)" for a in apps[:20]]
        lines.append("Windows doesn't count bytes per app for normal users; this shows who is connected, not how much.")
        return "\n".join(lines)

    @command("ipinfo", "myip", "dns", group=G, usage="/ipinfo", help="your IP addresses, gateway, DNS and public IP",
             title="IP and DNS info", icon="🌐", page="pc")
    def ipinfo_cmd(self, args: str, routed: bool = False):
        info = ip_info()
        lines = ["🌐 Network:"]
        for a in info["adapters"]:
            lines.append(f"  {a['name']}: {', '.join(a['ipv4']) or '—'}" + (f"  (IPv6 {a['ipv6'][0]})" if a["ipv6"] else "")
                         + (f"  {a['speed']} Mb/s" if a["speed"] else ""))
        if info["gateway"]:
            lines.append(f"  Router (gateway): {info['gateway']}")
        for d in info["dns"]:
            servers = d.get("ServerAddresses")
            servers = servers if isinstance(servers, list) else [servers]
            lines.append(f"  DNS ({d.get('InterfaceAlias')}): {', '.join(str(s) for s in servers)}")
        p = info["public"]
        if p.get("ip"):
            conn = p.get("connection") or {}
            lines.append(f"  Public IP: {p['ip']} — {p.get('city', '')}, {p.get('country', '')} · "
                         f"{conn.get('isp') or conn.get('org') or ''}")
        return "\n".join(lines)


def Counter_codes(found: list[dict]) -> int | None:
    from collections import Counter

    codes = Counter(c["code"] for c in found if c["code"] is not None)
    return codes.most_common(1)[0][0] if codes else None
