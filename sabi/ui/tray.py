"""Menu-bar item."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def _icon() -> QIcon:
    pm = QPixmap(44, 44)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.GlobalColor.black)
    font = QFont(".AppleSystemUIFont", 30)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    icon = QIcon(pm)
    icon.setIsMask(True)  # adapts to light/dark menu bar
    return icon


def build_tray(controller, panel) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_icon())
    tray.setToolTip("SAbi")
    menu = QMenu()

    def add(label, fn):
        action = QAction(label, menu)
        action.triggered.connect(fn)
        menu.addAction(action)
        return action

    add("Show SAbi", lambda: (panel.show(), panel.raise_()))
    add("Add notes or past questions…", panel.pick_document)
    add("Quiz me", controller.start_quiz)
    add("My learning path", lambda: controller.show_pathways(speak=False))
    menu.addSeparator()
    provider_status = add("AI: Offline · Ollama", lambda: None)
    provider_status.setEnabled(False)
    connect_chatgpt = add("Continue with ChatGPT…", controller.connect_chatgpt)
    use_offline = add("Use Offline Ollama", lambda: controller.select_provider("local"))
    disconnect_chatgpt = add("Disconnect ChatGPT", controller.disconnect_chatgpt)
    menu.addSeparator()
    add("Quit SAbi", QApplication.instance().quit)

    def sync_provider(state: dict) -> None:
        provider_status.setText(f"AI: {state.get('active_name', 'Offline · Ollama')}")
        connected = bool(state.get("connected"))
        connect_chatgpt.setVisible(not connected)
        disconnect_chatgpt.setVisible(connected)
        use_offline.setVisible(connected and state.get("mode") == "chatgpt")

    controller.provider_changed.connect(sync_provider)
    sync_provider(controller.provider_snapshot())
    tray.setContextMenu(menu)
    tray.show()
    tray._menu = menu  # keep a reference
    return tray
