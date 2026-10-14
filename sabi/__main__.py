"""Entry point: `python -m sabi` or `sabi`."""

from __future__ import annotations

import signal
import sys

import Quartz
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from sabi.config import FROZEN, settings
from sabi.controller import Controller
from sabi.platform.macos import windows
from sabi.platform.macos.hotkey import PushToTalk
from sabi.ui.overlay import Overlay
from sabi.ui.panel import Panel
from sabi.ui.tray import build_tray


def _log_to_file() -> None:
    """The packaged app has no terminal, so send output to ~/Library/Logs/SAbi.log."""
    from pathlib import Path

    log = Path.home() / "Library" / "Logs" / "SAbi.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log, "a", buffering=1)


def main() -> int:
    if FROZEN:
        _log_to_file()
    app = QApplication(sys.argv)
    app.setApplicationName("SAbi")
    app.setQuitOnLastWindowClosed(False)
    windows.hide_dock_icon()

    controller = Controller(settings)
    overlay = Overlay(lambda: controller.recorder.level)
    panel = Panel(controller)
    tray = build_tray(controller, panel)

    controller.state_changed.connect(overlay.set_state)
    controller.point_at.connect(overlay.buddy.point)
    controller.clear_point.connect(overlay.buddy.release)
    controller.notice.connect(lambda n: overlay.buddy.say(n, 5))
    controller.transcript.connect(lambda t: overlay.buddy.say(f"“{t}”", 3))

    if not windows.has_screen_recording():
        windows.request_screen_recording()
        controller.notice.emit("Allow Screen Recording in System Settings so SAbi can see your screen, then restart.")

    hotkey = PushToTalk(controller.on_hotkey_press, controller.on_hotkey_release, controller.on_escape)
    hotkey_ok = hotkey.start()
    print(f"[sabi] started; screen recording={windows.has_screen_recording()} hotkey={hotkey_ok}", flush=True)
    if not hotkey_ok:
        Quartz.CGRequestListenEventAccess()
        controller.notice.emit("Allow Input Monitoring for this app in System Settings, then restart. You can still type.")

    panel.place_top_right()
    panel.show()
    controller.warm_up()
    app.aboutToQuit.connect(controller.shutdown)

    # Let Ctrl+C in the terminal quit cleanly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(250)
    tick.timeout.connect(lambda: None)

    _keep = (overlay, panel, tray, hotkey, tick)  # noqa: F841
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
