"""Record what your mouse and keyboard do, and play it back (10.0).

Recording uses Windows' low-level hooks, and only while you have pressed
Record — a red dot on the Automations page says so the whole time. Playback
uses SendInput, can be slowed down or sped up, and stops the moment you press
Esc. Macros are saved sealed in the data folder like everything else.

Windows only. Text you type into password boxes is recorded like any other
key, which is why recording never starts on its own.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from . import kit

MACROS = kit.Store("macros.json", {})
STOP_KEY = 0x1B          # Esc stops playback
RECORD_STOP_KEY = 0x79   # F10 stops recording

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEWHEEL = 0x0204, 0x0205, 0x0207, 0x0208, 0x020A
LLMHF_INJECTED, LLKHF_INJECTED = 0x01, 0x10


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class Recorder:
    def __init__(self) -> None:
        self.events: list[list] = []
        self.recording = False
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._start = 0.0
        self._last_move = 0.0

    def start(self) -> None:
        if self.recording:
            return
        self.events = []
        self.recording = True
        self._start = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-macro-record")
        self._thread.start()

    def _now(self) -> float:
        return round(time.monotonic() - self._start, 3)

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        def keyboard(code, wparam, lparam):
            if code == 0:
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not info.flags & LLKHF_INJECTED:
                    if info.vkCode == RECORD_STOP_KEY and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self.stop()
                    else:
                        down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                        self.events.append([self._now(), "key", int(info.vkCode), 1 if down else 0])
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def mouse(code, wparam, lparam):
            if code == 0:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not info.flags & LLMHF_INJECTED:
                    t = self._now()
                    x, y = info.pt.x, info.pt.y
                    if wparam == WM_MOUSEMOVE:
                        if t - self._last_move >= 0.02:
                            self._last_move = t
                            self.events.append([t, "move", x, y])
                    elif wparam in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN,
                                    WM_MBUTTONUP):
                        button = {WM_LBUTTONDOWN: "left", WM_LBUTTONUP: "left", WM_RBUTTONDOWN: "right",
                                  WM_RBUTTONUP: "right", WM_MBUTTONDOWN: "middle", WM_MBUTTONUP: "middle"}[wparam]
                        down = wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN)
                        self.events.append([t, "click", x, y, button, 1 if down else 0])
                    elif wparam == WM_MOUSEWHEEL:
                        delta = ctypes.c_short(info.mouseData >> 16).value
                        self.events.append([t, "wheel", x, y, delta])
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._kb_proc = HOOKPROC(keyboard)
        self._ms_proc = HOOKPROC(mouse)
        kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, None, 0)
        ms = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, None, 0)
        msg = wintypes.MSG()
        while self.recording and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(kb)
        user32.UnhookWindowsHookEx(ms)

    def stop(self) -> list[list]:
        if not self.recording:
            return self.events
        self.recording = False
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)   # WM_QUIT
        return self.events


def tidy(events: list[list], stopped_by_click: bool = True) -> list[list]:
    """Drop the click on Stop (when that is how recording ended) and the moves around it."""
    events = list(events)
    while events and events[-1][1] == "move":
        events.pop()
    if stopped_by_click and len(events) >= 2 and events[-1][1] == "click" and events[-2][1] == "click":
        events = events[:-2]
        while events and events[-1][1] == "move":
            events.pop()
    return events


class Player:
    def __init__(self) -> None:
        self.playing = False
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def play(self, events: list[list], speed: float = 1.0, repeat: int = 1, on_done=None) -> None:
        self._stop.clear()
        self.playing = True
        thread = threading.Thread(target=self._run, args=(events, speed, repeat, on_done), daemon=True)
        thread.start()

    def _run(self, events, speed, repeat, on_done) -> None:
        user32 = ctypes.windll.user32
        sx, sy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)          # virtual screen origin
        sw, sh = max(1, user32.GetSystemMetrics(78)), max(1, user32.GetSystemMetrics(79))
        flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}

        def send(inp: INPUT):
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        def mouse_at(x, y, extra_flags=0, data=0):
            inp = INPUT(type=0)
            inp.u.mi = MOUSEINPUT(int((x - sx) * 65535 / (sw - 1)), int((y - sy) * 65535 / (sh - 1)),
                                  data & 0xFFFFFFFF, 0x0001 | 0x8000 | 0x4000 | extra_flags, 0, 0)
            send(inp)

        stopped = False
        for _ in range(max(1, repeat)):
            started = time.monotonic()
            for event in events:
                if self._stop.is_set() or user32.GetAsyncKeyState(STOP_KEY) & 0x8000:
                    stopped = True
                    break
                due = event[0] / max(0.1, speed)
                wait = due - (time.monotonic() - started)
                if wait > 0:
                    self._stop.wait(min(wait, 5.0))
                kind = event[1]
                if kind == "move":
                    mouse_at(event[2], event[3])
                elif kind == "click":
                    down_flag, up_flag = flags.get(event[4], flags["left"])
                    mouse_at(event[2], event[3], down_flag if event[5] else up_flag)
                elif kind == "wheel":
                    mouse_at(event[2], event[3], 0x0800, event[4])
                elif kind == "key":
                    inp = INPUT(type=1)
                    inp.u.ki = KEYBDINPUT(event[2], 0, 0 if event[3] else 0x0002, 0, 0)
                    send(inp)
            if stopped:
                break
        self.playing = False
        if on_done is not None:
            on_done(not stopped)


recorder = Recorder()
player = Player()


def save(name: str, events: list[list]) -> None:
    macros = MACROS.load()
    macros[name] = {"events": events, "saved": time.time(), "length": events[-1][0] if events else 0}
    MACROS.save(macros)


def describe(events: list[list]) -> str:
    keys = sum(1 for e in events if e[1] == "key" and e[3])
    clicks = sum(1 for e in events if e[1] == "click" and e[5])
    length = events[-1][0] if events else 0
    return f"{clicks} click(s), {keys} key press(es), {length:.1f} s"
