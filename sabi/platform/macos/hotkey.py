"""Push-to-talk hotkey via a listen-only Quartz event tap.

Hold Control+Option to talk, release to send. Esc stops speech.
Needs Input Monitoring (or Accessibility) permission for the app running SAbi.
"""

from __future__ import annotations

import threading
from typing import Callable

import Quartz

ESC_KEYCODE = 53
_COMBO = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
_OTHER_MODS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift


class PushToTalk:
    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None], on_escape: Callable[[], None]):
        self._on_press = on_press
        self._on_release = on_release
        self._on_escape = on_escape
        self._held = False
        self._tap = None

    def start(self) -> bool:
        """Start listening on a background thread. Returns False if permission is missing."""
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if self._tap is None:
            return False
        threading.Thread(target=self._run, name="sabi-hotkey", daemon=True).start()
        return True

    def _run(self) -> None:
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()

    def _callback(self, proxy, event_type, event, refcon):
        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        if event_type == Quartz.kCGEventKeyDown:
            if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode) == ESC_KEYCODE:
                self._on_escape()
            return event
        flags = Quartz.CGEventGetFlags(event)
        down = (flags & _COMBO) == _COMBO and not (flags & _OTHER_MODS)
        if down and not self._held:
            self._held = True
            self._on_press()
        elif not down and self._held:
            self._held = False
            self._on_release()
        return event
