"""The 10.0 commands, one module per area, gathered into one mixin.

Like 8.0's Eight: each module registers its commands with @command (which
also describes their forms), Jarvis inherits Ten, and Eight.eight_command
finds a method by name. start() and stop() run the background checks some
areas need — alerts, automations, the phone link — while the window is open.
"""

from __future__ import annotations

from .office import Office
from .school import School
from .coding import Coding
from .system import System
from .shield10 import Shield10
from .automate import Automate
from .aihelp import AIHelp
from .media import Media
from .play import Play
from .lifestyle import Lifestyle
from .phone import Phone
from .work import Work
from .design10 import Design10


class Ten(Office, School, Coding, System, Shield10, Automate, AIHelp, Media, Play, Lifestyle, Phone, Work,
          Design10):
    pass


_started = False


def start(jarvis) -> None:
    """Register every area's watchers and start the shared watcher thread."""
    global _started
    from ..watchers import watchers

    if _started:
        return
    _started = True
    from . import school

    for module in (system_mod(), shield_mod(), automate_mod(), lifestyle_mod(), work_mod(), phone_mod(), school):
        hook = getattr(module, "register_watchers", None)
        if hook is not None:
            try:
                hook(jarvis, watchers)
            except Exception:
                pass
    watchers.start()


def stop() -> None:
    global _started
    from ..watchers import watchers

    watchers.stop()
    _started = False
    try:
        phone_mod().stop_server()
    except Exception:
        pass
    import sys

    music = sys.modules.get("jarvis.music")     # only if something played; no need to import it to stop it
    if music is not None:
        try:
            music.player.shutdown()
            music.drums.stop()
        except Exception:
            pass


def system_mod():
    from . import system

    return system


def shield_mod():
    from . import shield10

    return shield10


def automate_mod():
    from . import automate

    return automate


def lifestyle_mod():
    from . import lifestyle

    return lifestyle


def work_mod():
    from . import work

    return work


def phone_mod():
    from . import phone

    return phone
