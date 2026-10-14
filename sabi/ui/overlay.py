"""The on-screen buddy: follows the cursor, shows listening/thinking/speaking, and flies to what it explains.

One transparent, click-through window per display (a single window spanning displays is unreliable on
macOS). All windows draw from one shared Buddy model, in global screen points.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from sabi.platform.macos import windows

GREEN = QColor(0, 135, 81)  # Nigerian flag green
GREEN_SOFT = QColor(0, 135, 81, 70)
INK = QColor(20, 24, 22)
OFFSET = QPointF(22, 18)  # rest position relative to the cursor


def _smoothstep(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


class Buddy:
    """Position and animation state, advanced once per frame."""

    def __init__(self, level_source) -> None:
        self.pos = QPointF(QApplication.primaryScreen().geometry().center())
        self.vel = QPointF(0, 0)
        self.state = "idle"
        self.level_source = level_source  # callable → mic RMS
        self.target: QPointF | None = None
        self.target_label = ""
        self._flight: tuple[QPointF, QPointF, float, float] | None = None  # start, end, t0, duration
        self.bubble = ""
        self._bubble_until = 0.0
        self.t = 0.0

    def say(self, text: str, seconds: float = 4.0) -> None:
        self.bubble = text if len(text) <= 90 else text[:87] + "…"
        self._bubble_until = time.monotonic() + seconds

    def point(self, x: float, y: float, label: str) -> None:
        end = QPointF(x, y)
        dist = math.hypot(end.x() - self.pos.x(), end.y() - self.pos.y())
        self._flight = (QPointF(self.pos), end, time.monotonic(), min(1.4, 0.6 + dist / 1800))
        self.target, self.target_label = end, label

    def release(self) -> None:
        self.target, self._flight, self.target_label = None, None, ""

    def step(self, cursor: QPointF) -> None:
        now = time.monotonic()
        self.t = now
        if self.bubble and now > self._bubble_until:
            self.bubble = ""
        if self._flight:
            start, end, t0, dur = self._flight
            u = _smoothstep((now - t0) / dur)
            # Quadratic Bézier arcing upward, like a hand moving to point.
            ctrl = QPointF((start.x() + end.x()) / 2, min(start.y(), end.y()) - 120)
            a, b = (1 - u) ** 2, 2 * (1 - u) * u
            self.pos = start * a + ctrl * b + end * (u * u)
            if u >= 1:
                self._flight = None
            return
        if self.target is not None:
            self.pos = QPointF(self.target)
            return
        goal = cursor + OFFSET
        # Critically-damped-ish spring toward the cursor.
        self.vel = (self.vel + (goal - self.pos) * 0.25) * 0.55
        self.pos += self.vel


class OverlayWindow(QWidget):
    def __init__(self, screen, buddy: Buddy) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.buddy = buddy
        for attr in (
            Qt.WidgetAttribute.WA_TranslucentBackground,
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
        ):
            self.setAttribute(attr, True)
        self.setGeometry(screen.geometry())
        self.show()
        windows.make_overlay(int(self.winId()))

    def paintEvent(self, event) -> None:
        b = self.buddy
        origin = QPointF(self.geometry().topLeft())
        local = b.pos - origin
        reach = QRectF(-400, -200, self.width() + 800, self.height() + 400)
        if not reach.contains(local) and (b.target is None or not reach.contains(b.target - origin)):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if b.target is not None:
            self._draw_ring(p, b.target - origin, b.t)
        self._draw_buddy(p, local, b)
        label = b.target_label if b.target is not None and b.target_label else b.bubble
        if label:
            self._draw_bubble(p, local, label)
        p.end()

    def _draw_ring(self, p: QPainter, c: QPointF, t: float) -> None:
        pulse = (math.sin(t * 5) + 1) / 2
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(GREEN, 3))
        p.drawEllipse(c, 18 + pulse * 6, 18 + pulse * 6)
        p.setPen(QPen(GREEN_SOFT, 8))
        p.drawEllipse(c, 30 + pulse * 10, 30 + pulse * 10)

    def _draw_buddy(self, p: QPainter, c: QPointF, b: Buddy) -> None:
        scale = 1.0 + (0.08 * math.sin(b.t * 8) if b.state == "speaking" else 0)
        path = QPainterPath()
        # A rounded pointer tilted toward the top-left, so its tip "touches" what it points at.
        tip = QPointF(0, 0)
        path.moveTo(tip)
        path.lineTo(QPointF(4, 22) * scale)
        path.quadTo(QPointF(9, 15) * scale, QPointF(17, 14) * scale)
        path.closeSubpath()
        path.translate(c - QPointF(2, 2) if b.target is not None else c - OFFSET * 0.6)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(GREEN)
        p.drawPath(path)

        anchor = path.boundingRect().bottomRight() + QPointF(6, 0)
        if b.state == "listening":
            level = min(1.0, b.level_source() * 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(GREEN)
            for i in range(5):
                h = 4 + level * 18 * (0.5 + 0.5 * math.sin(b.t * 14 + i * 1.3))
                p.drawRoundedRect(QRectF(anchor.x() + i * 5, anchor.y() - h, 3, h), 1.5, 1.5)
        elif b.state == "thinking":
            p.setPen(QPen(GREEN, 3, cap=Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(anchor.x(), anchor.y() - 16, 14, 14), int(-b.t * 360 * 16 * 1.5) % (360 * 16), 270 * 16)

    def _draw_bubble(self, p: QPainter, c: QPointF, text: str) -> None:
        font = QFont(".AppleSystemUIFont", 12)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = QFontMetricsF(font)
        w = min(360.0, fm.horizontalAdvance(text) + 20)
        rect = fm.boundingRect(QRectF(0, 0, w - 20, 200), Qt.TextFlag.TextWordWrap, text)
        box = QRectF(c.x() + 26, c.y() + 18, w, rect.height() + 12)
        if box.right() > self.width() - 8:
            box.moveRight(c.x() - 12)
        if box.bottom() > self.height() - 8:
            box.moveBottom(c.y() - 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(INK)
        p.drawText(box.adjusted(10, 6, -10, -6), Qt.TextFlag.TextWordWrap, text)


class Overlay:
    """Owns one window per screen and the shared animation clock."""

    def __init__(self, level_source) -> None:
        self.buddy = Buddy(level_source)
        self._windows: list[OverlayWindow] = []
        app = QApplication.instance()
        app.screenAdded.connect(lambda _s: self._rebuild())
        app.screenRemoved.connect(lambda _s: self._rebuild())
        self._rebuild()
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _rebuild(self) -> None:
        for w in self._windows:
            w.close()
        self._windows = [OverlayWindow(s, self.buddy) for s in QApplication.screens()]

    def _tick(self) -> None:
        from PyQt6.QtGui import QCursor

        self.buddy.step(QPointF(QCursor.pos()))
        for w in self._windows:
            w.update()

    def set_state(self, state: str) -> None:
        self.buddy.state = state
        if state == "listening":
            self.buddy.say("Listening…", 30)
        elif state == "idle" and self.buddy.bubble == "Listening…":
            self.buddy.bubble = ""
