"""The answer panel: transcript, answer with sources, typed questions, documents, quiz and pathways."""

from __future__ import annotations

import html

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sabi.language import LANGUAGES
from sabi.platform.macos import windows

DOC_FILTER = "Documents (*.pdf *.txt *.md)"

# Colors are always set explicitly: mixing our backgrounds with the system's dark-mode text color
# made text invisible.
THEMES = {
    "light": dict(bg="#FBFCFB", fg="#141816", muted="#5B6660", soft="#3D4743", field="#FFFFFF", border="#D5DBD8", accent="#008751"),
    "dark": dict(bg="#1C211F", fg="#EEF2F0", muted="#A3ADA8", soft="#C5CDC9", field="#262C29", border="#3A423E", accent="#1FA971"),
}

STYLE = """
QWidget#panel {{ background: {bg}; color: {fg}; }}
QLabel {{ color: {fg}; }}
QLabel#title {{ font-size: 17px; font-weight: 700; color: {accent}; }}
QLabel#status {{ color: {muted}; font-size: 12px; }}
QLabel#you {{ color: {soft}; font-style: italic; font-size: 13px; }}
QLabel#sources {{ color: {soft}; font-size: 12px; }}
QLabel#providerNote {{ color: {muted}; font-size: 11px; }}
QTextBrowser {{ border: none; background: transparent; font-size: 14px; color: {fg}; }}
QLineEdit {{ border: 1px solid {border}; border-radius: 8px; padding: 7px 10px; font-size: 13px;
             background: {field}; color: {fg}; selection-background-color: {accent}; }}
QPushButton {{ border: 1px solid {border}; border-radius: 8px; padding: 6px 10px; background: {field};
               color: {fg}; font-size: 12px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton#primary {{ background: {accent}; color: white; border: none; }}
QComboBox {{ font-size: 12px; color: {fg}; background: {field}; border: 1px solid {border}; border-radius: 6px;
             padding: 3px 8px; }}
QComboBox QAbstractItemView {{ color: {fg}; background: {field}; selection-background-color: {accent}; }}
"""


def _theme() -> str:
    from PyQt6.QtGui import QGuiApplication

    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


STATUS = {
    "idle": "Hold ⌃ Control + ⌥ Option and ask out loud, or type below.",
    "listening": "Listening… release to send.",
    "thinking": "Thinking…",
    "speaking": "Speaking… press Esc to stop.",
    "connecting": "Waiting for ChatGPT sign-in in your browser…",
}


class Panel(QWidget):
    def __init__(self, controller) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.c = controller
        self.setObjectName("panel")
        self.setWindowTitle("SAbi")
        self._apply_theme()
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: self._apply_theme())
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.resize(420, 570)

        title = QLabel("SAbi")
        title.setObjectName("title")
        self.lang = QComboBox()
        self.lang.addItem("Language: auto", "auto")
        for code, lang in LANGUAGES.items():
            self.lang.addItem(lang.name, code)
        self.lang.currentIndexChanged.connect(lambda _i: self.c.set_language(self.lang.currentData()))
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.lang)

        self.status = QLabel(STATUS["idle"])
        self.status.setObjectName("status")
        self.status.setWordWrap(True)

        self.provider = QComboBox()
        self.provider.currentIndexChanged.connect(self._provider_selected)
        self.account = QPushButton("Continue with ChatGPT")
        self.account.clicked.connect(self._account_clicked)
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("AI:"))
        provider_row.addWidget(self.provider, 1)
        provider_row.addWidget(self.account)
        self.provider_note = QLabel("")
        self.provider_note.setObjectName("providerNote")
        self.provider_note.setWordWrap(True)
        self.you = QLabel("")
        self.you.setObjectName("you")
        self.you.setWordWrap(True)
        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        self.answer.setMarkdown(
            "**Welcome to SAbi.** Ask about anything on your screen: a maths question in a PDF, an Excel "
            "formula, a confusing website.\n\nDrop your notes or past questions here and answers will cite them.\n\n"
            'Say *"quiz me"* to revise, or *"what should I learn next?"* to see your path.'
        )
        self.sources = QLabel("")
        self.sources.setObjectName("sources")
        self.sources.setWordWrap(True)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a question…")
        self.input.returnPressed.connect(self._ask)
        self.input.installEventFilter(self)

        quiz = QPushButton("Quiz me")
        quiz.clicked.connect(self.c.start_quiz)
        path = QPushButton("My path")
        path.clicked.connect(lambda: self.c.show_pathways(speak=False))
        add = QPushButton("Add notes…")
        add.clicked.connect(self.pick_document)
        ask = QPushButton("Ask")
        ask.setObjectName("primary")
        ask.clicked.connect(self._ask)
        buttons = QHBoxLayout()
        for b in (quiz, path, add):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(ask)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addLayout(head)
        layout.addWidget(self.status)
        layout.addLayout(provider_row)
        layout.addWidget(self.provider_note)
        layout.addWidget(self.you)
        layout.addWidget(self.answer, 1)
        layout.addWidget(self.sources)
        layout.addWidget(self.input)
        layout.addLayout(buttons)

        c = self.c
        c.state_changed.connect(self._state_update)
        c.transcript.connect(lambda t: self.you.setText(f"You: “{t}”"))
        c.answer_delta.connect(self.answer.setPlainText)
        c.answer_done.connect(self._done)
        c.show_markdown.connect(self._markdown)
        c.notice.connect(lambda n: self.status.setText(n))
        c.language_changed.connect(self._sync_language)
        c.provider_changed.connect(self._provider_update)
        self._provider_update(c.provider_snapshot())

    def eventFilter(self, obj, event) -> bool:
        if obj is self.input and event.type() == QEvent.Type.MouseButtonPress:
            windows.activate_app()
            self.activateWindow()
        return super().eventFilter(obj, event)

    def _apply_theme(self) -> None:
        self.setStyleSheet(STYLE.format(**THEMES[_theme()]))

    def _state_update(self, state: str) -> None:
        self.status.setText(STATUS.get(state, state))
        self.account.setEnabled(state != "connecting")

    def place_top_right(self) -> None:
        from PyQt6.QtWidgets import QApplication

        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 16, area.top() + 16)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        windows.keep_visible(int(self.winId()))

    def _ask(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.c.ask_text(text)

    def _done(self, text: str, sources: list) -> None:
        self.answer.setPlainText(text)
        self.sources.setText(("Sources: " + " · ".join(html.escape(s) for s in sources)) if sources else "")

    def _markdown(self, title: str, md: str) -> None:
        self.you.setText(title)
        self.answer.setMarkdown(md)
        self.sources.setText("Links are from SAbi's curated list of free, official resources.")
        self.show()

    def _sync_language(self, code: str) -> None:
        i = self.lang.findData(code)
        if i >= 0 and i != self.lang.currentIndex():
            self.lang.blockSignals(True)
            self.lang.setCurrentIndex(i)
            self.lang.blockSignals(False)

    def _provider_update(self, state: dict) -> None:
        self.provider.blockSignals(True)
        self.provider.clear()
        self.provider.addItem("Offline · Ollama", "local")
        for display, slug in state.get("models", []):
            self.provider.addItem(f"ChatGPT · {display}", f"chatgpt:{slug}")
        if state.get("connected") and state.get("selected_model") and not state.get("models"):
            slug = state["selected_model"]
            self.provider.addItem(f"ChatGPT · {slug}", f"chatgpt:{slug}")
        selected = "local" if state.get("mode") != "chatgpt" else f"chatgpt:{state.get('selected_model', '')}"
        index = self.provider.findData(selected)
        self.provider.setCurrentIndex(max(0, index))
        self.provider.blockSignals(False)

        connected = bool(state.get("connected"))
        self.account.setText("Disconnect" if connected else "Continue with ChatGPT")
        if state.get("mode") == "chatgpt" and connected:
            email = state.get("email") or "connected account"
            self.provider_note.setText(f"Using ChatGPT plan · {email}. Screen images and questions are sent to OpenAI.")
        else:
            self.provider_note.setText("Local AI mode · no questions, notes or screenshots are sent to OpenAI.")

    def _provider_selected(self) -> None:
        value = self.provider.currentData()
        if value:
            self.c.select_provider(value)

    def _account_clicked(self) -> None:
        if self.c.chatgpt_session.connected:
            self.c.disconnect_chatgpt()
        else:
            self.c.connect_chatgpt()

    def pick_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add notes or past questions", "", DOC_FILTER)
        if path:
            self.c.add_document(path)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith((".pdf", ".txt", ".md")):
                self.c.add_document(url.toLocalFile())
