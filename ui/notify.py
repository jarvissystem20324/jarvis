"""Tell the user a long answer is ready, when they have looked away.

Only used when a request took a while and the window is not focused — a
notification for an answer you are already watching arrive is noise.

No new dependency. On Windows the taskbar button flashes (FlashWindowEx) and
a native toast is raised through PowerShell's own registered app identity, so
nothing has to be installed or registered. macOS uses osascript. Anything
that fails is ignored: a missing notification must never cost the answer.

The toast never contains the reply itself — only that one is ready, which
mode, and how long it took. Notifications are shown on the lock screen and
kept in Action Center, and whatever you asked about has no business there.
"""

from __future__ import annotations

import subprocess
import sys

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# PowerShell's AppUserModelID is registered on every Windows 10/11 install,
# which is what lets a toast appear without registering one of our own.
_POWERSHELL_APP_ID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
)


def _ps_quote(text: str) -> str:
    """A PowerShell single-quoted string; the only escape is a doubled quote."""
    return "'" + text.replace("'", "''") + "'"


def flash(window) -> None:
    """Flash the taskbar button until the window is focused."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd,
                          FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def toast(title: str, body: str) -> None:
    """A native desktop notification. Fire and forget."""
    try:
        if sys.platform.startswith("win"):
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] > $null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$n = $t.GetElementsByTagName('text');"
                f"$n.Item(0).AppendChild($t.CreateTextNode({_ps_quote(title)})) > $null;"
                f"$n.Item(1).AppendChild($t.CreateTextNode({_ps_quote(body)})) > $null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                f"{_ps_quote(_POWERSHELL_APP_ID)}).Show("
                "[Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["osascript", "-e",
                 f"display notification {_as_quote(body)} with title {_as_quote(title)}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _as_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def answer_ready(window, mode: str, seconds: float) -> None:
    """The one notification JARVIS sends: an answer has arrived."""
    flash(window)
    toast("JARVIS answered", f"{mode} mode · {seconds:.0f}s")
