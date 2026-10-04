"""Casting to a TV (10.0) with DLNA/UPnP — what most smart TVs from Samsung,
LG, Sony and Philips, and many receivers and media boxes, understand.

Finding a TV is an SSDP "who's out there?" sent to the local network; the TV
answers with the address of a description of itself, which names the
AVTransport service JARVIS then tells "play this URL". The URL is served by
the phone link (jarvis/phonelink.py), so the TV pulls the file straight from
the PC. Chromecast speaks a different protocol and isn't covered.
"""

from __future__ import annotations

import html
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SSDP = ("239.255.255.250", 1900)
AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"


class CastError(Exception):
    pass


def parse_ssdp(data: bytes) -> dict[str, str]:
    headers = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    return headers


def _text(node, name: str) -> str:
    for child in node.iter():
        if child.tag.split("}")[-1] == name:
            return (child.text or "").strip()
    return ""


def parse_description(xml: str, location: str) -> dict | None:
    """The TV's name and the URL to send AVTransport commands to (None if it can't play things)."""
    root = ET.fromstring(xml)
    base = _text(root, "URLBase") or location
    name = _text(root, "friendlyName") or urllib.parse.urlparse(location).hostname
    for service in root.iter():
        if service.tag.split("}")[-1] != "service":
            continue
        kind = _text(service, "serviceType")
        if "AVTransport" in kind:
            return {"name": name, "location": location, "service": kind,
                    "control": urllib.parse.urljoin(base, _text(service, "controlURL")),
                    "host": urllib.parse.urlparse(location).hostname}
    return None


def discover(timeout: float = 3.0) -> list[dict]:
    """TVs and other players on the network that accept a URL to play."""
    message = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
               f"ST: {AVTRANSPORT}\r\n\r\n").encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    locations: list[str] = []
    try:
        for _ in range(2):                  # UDP can drop a packet; ask twice
            sock.sendto(message, SSDP)
        ends = time.time() + timeout
        while time.time() < ends:
            try:
                data, _ = sock.recvfrom(65507)
            except socket.timeout:
                continue
            location = parse_ssdp(data).get("location")
            if location and location not in locations:
                locations.append(location)
    finally:
        sock.close()
    found = []
    for location in locations:
        try:
            with urllib.request.urlopen(location, timeout=3) as response:
                device = parse_description(response.read().decode("utf-8", "replace"), location)
        except Exception:
            continue
        if device and all(d["control"] != device["control"] for d in found):
            found.append(device)
    return found


def envelope(action: str, service: str, args: dict) -> bytes:
    body = "".join(f"<{k}>{html.escape(str(v))}</{k}>" for k, v in args.items())
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{service}">{body}</u:{action}></s:Body></s:Envelope>').encode("utf-8")


def soap(device: dict, action: str, **args) -> str:
    request = urllib.request.Request(device["control"], data=envelope(action, device["service"], args), headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{device["service"]}#{action}"'})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:
        raise CastError(f"{device['name']} said no to {action}: {exc}") from None


def didl(url: str, title: str, mime: str) -> str:
    kind = ("object.item.videoItem" if mime.startswith("video") else "object.item.audioItem.musicTrack"
            if mime.startswith("audio") else "object.item.imageItem.photo")
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="0" parentID="-1" restricted="1">'
            f"<dc:title>{html.escape(title)}</dc:title><upnp:class>{kind}</upnp:class>"
            f'<res protocolInfo="http-get:*:{mime}:*">{html.escape(url)}</res></item></DIDL-Lite>')


def play(device: dict, url: str, title: str, mime: str) -> None:
    soap(device, "SetAVTransportURI", InstanceID=0, CurrentURI=url, CurrentURIMetaData=didl(url, title, mime))
    soap(device, "Play", InstanceID=0, Speed=1)


def pause(device: dict) -> None:
    soap(device, "Pause", InstanceID=0)


def stop(device: dict) -> None:
    soap(device, "Stop", InstanceID=0)
