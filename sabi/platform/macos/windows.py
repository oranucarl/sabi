"""Native window behaviour and frontmost-app lookup."""

from __future__ import annotations

import AppKit
import objc
import Quartz


def make_overlay(win_id: int) -> None:
    """Turn a Qt top-level window into a click-through overlay that floats over every Space,
    including full-screen apps, without ever taking focus."""
    view = objc.objc_object(c_void_p=win_id)
    window = view.window()
    if window is None:
        return
    window.setIgnoresMouseEvents_(True)
    window.setHidesOnDeactivate_(False)
    window.setLevel_(AppKit.NSScreenSaverWindowLevel)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorIgnoresCycle
    )
    window.setHasShadow_(False)
    # Keep the buddy out of SAbi's own screenshots so the model never "sees" it.
    window.setSharingType_(AppKit.NSWindowSharingNone)


def keep_visible(win_id: int) -> None:
    """Keep a normal panel visible when the app is not active (we have no Dock icon)."""
    window = objc.objc_object(c_void_p=win_id).window()
    if window is not None:
        window.setHidesOnDeactivate_(False)
        window.setLevel_(AppKit.NSFloatingWindowLevel)
        window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)
        # Screenshots should show what the learner is studying, not SAbi's own panel.
        window.setSharingType_(AppKit.NSWindowSharingNone)


def activate_app() -> None:
    """Bring SAbi forward so its panel receives typing (menu-bar apps aren't activated by default)."""
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def hide_dock_icon() -> None:
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)


def frontmost_context() -> tuple[str, str]:
    """Return (app name, front window title). The title is empty without Screen Recording permission."""
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "", ""
    name = str(app.localizedName() or "")
    pid = app.processIdentifier()
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID
    ) or []
    for info in infos:
        if info.get(Quartz.kCGWindowOwnerPID) == pid and info.get(Quartz.kCGWindowLayer) == 0:
            return name, str(info.get(Quartz.kCGWindowName) or "")
    return name, ""


def has_screen_recording() -> bool:
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def request_screen_recording() -> None:
    Quartz.CGRequestScreenCaptureAccess()
