"""TP-Link Kasa smart plugs (10.0), switched on the local network.

Kasa plugs (HS100/HS103/HS105/HS110, KP105/KP115…) speak a small JSON
protocol on port 9999, scrambled with an "autokey" XOR. JARVIS finds them
with one broadcast and switches them directly — no cloud, no account.
Newer firmware and Tapo plugs require TP-Link's encrypted login instead,
and don't answer this; the Phone page says so rather than failing quietly.
"""

from __future__ import annotations

import json
import socket
import struct
import time


def scramble(text: str) -> bytes:
    key, out = 171, bytearray()
    for byte in text.encode("utf-8"):
        key = key ^ byte
        out.append(key)
    return bytes(out)


def unscramble(data: bytes) -> str:
    key, out = 171, bytearray()
    for byte in data:
        out.append(key ^ byte)
        key = byte
    return out.decode("utf-8", "replace")


def ask(ip: str, command: dict, timeout: float = 3.0, port: int = 9999) -> dict:
    """One request over TCP (a 4-byte length, then the scrambled JSON)."""
    payload = scramble(json.dumps(command))
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.sendall(struct.pack(">I", len(payload)) + payload)
        header = sock.recv(4)
        if len(header) < 4:
            raise OSError("The plug closed the connection.")
        length = struct.unpack(">I", header)[0]
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
    return json.loads(unscramble(data))


def plug_from(info: dict, ip: str) -> dict | None:
    sysinfo = info.get("system", {}).get("get_sysinfo", {})
    if not sysinfo:
        return None
    return {"ip": ip, "name": sysinfo.get("alias") or sysinfo.get("dev_name") or ip,
            "model": sysinfo.get("model", ""), "on": bool(sysinfo.get("relay_state"))}


def discover(timeout: float = 2.0) -> list[dict]:
    """Plugs that answer the broadcast (UDP: the same scrambling, no length prefix)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)
    found: dict[str, dict] = {}
    try:
        sock.sendto(scramble(json.dumps({"system": {"get_sysinfo": {}}})), ("255.255.255.255", 9999))
        ends = time.time() + timeout
        while time.time() < ends:
            try:
                data, (ip, _) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                plug = plug_from(json.loads(unscramble(data)), ip)
            except ValueError:
                continue
            if plug:
                found[ip] = plug
    finally:
        sock.close()
    return sorted(found.values(), key=lambda p: p["name"].lower())


def set_power(ip: str, on: bool, port: int = 9999) -> bool:
    reply = ask(ip, {"system": {"set_relay_state": {"state": 1 if on else 0}}}, port=port)
    return reply.get("system", {}).get("set_relay_state", {}).get("err_code", 1) == 0
