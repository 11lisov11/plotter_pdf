from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


TOAST_COLORS = {
    "success": ("#064e3b", "#d1fae5"),
    "error": ("#7f1d1d", "#fee2e2"),
    "info": ("#1e3a8a", "#dbeafe"),
}


class ToastWidget(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWindowFlags(Qt.SubWindow)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(self._label)

        self.hide()
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(180)
        self._anim.finished.connect(self._on_anim_finished)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._fade_out)
        self._hiding = False

    def show_message(self, level: str, text: str, timeout_ms: int = 3000) -> None:
        bg, fg = TOAST_COLORS.get(level, TOAST_COLORS["info"])
        self.setStyleSheet(
            f"""
            QFrame#Toast {{
                background: {bg};
                color: {fg};
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.20);
            }}
            QLabel {{
                color: {fg};
                font-weight: 500;
            }}
            """
        )

        self._label.setText(text)
        self.adjustSize()

        parent = self.parentWidget()
        if parent is not None:
            x = max(16, parent.width() - self.width() - 24)
            y = 24
            self.move(x, y)

        self._fade_timer.stop()
        self._anim.stop()
        self._hiding = False

        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._fade_timer.start(max(200, int(timeout_ms)))

    def _fade_out(self) -> None:
        if not self.isVisible():
            return
        self._anim.stop()
        self._hiding = True
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if self._hiding and self.windowOpacity() <= 0.01:
            self.hide()
            self._hiding = False
