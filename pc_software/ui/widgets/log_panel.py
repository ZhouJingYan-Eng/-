"""
日志面板组件
- 实时显示日志（来自 logger 桥）
- 按级别筛选
- 自动滚动到底部
"""
from collections import deque
from typing import Deque

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PyQt5.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QPlainTextEdit, QPushButton, QWidget, QButtonGroup, QCheckBox,
)

from core.logger import get_log_bridge

LEVEL_COLORS = {
    "TRACE": "#888888",
    "DEBUG": "#5dade2",
    "INFO": "#2ecc71",
    "SUCCESS": "#16a085",
    "WARNING": "#f39c12",
    "ERROR": "#e74c3c",
    "CRITICAL": "#9b59b6",
}


class LogPanelWidget(QWidget):
    """日志面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffer: Deque[str] = deque(maxlen=2000)
        self._filter_level = "DEBUG"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # 日志文本框
        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(2000)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0e0e10;
                color: #cccccc;
                border: none;
            }
        """)
        layout.addWidget(self._text, 1)

        # 级别筛选按钮
        side = QVBoxLayout()
        side.setSpacing(2)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for lvl in ("DEBUG", "INFO", "WARNING", "ERROR"):
            cb = QCheckBox(lvl, self)
            cb.setChecked(lvl == self._filter_level)
            cb.toggled.connect(lambda checked, l=lvl: self._set_filter(l, checked))
            self._btn_group.addButton(cb)
            side.addWidget(cb)
        side.addStretch(1)

        # 清空按钮
        clear_btn = QPushButton("清空", self)
        clear_btn.clicked.connect(self._clear)
        side.addWidget(clear_btn)

        layout.addLayout(side)

        # 连接日志桥
        bridge = get_log_bridge()
        bridge.log_emitted.connect(self._on_log)

    def _set_filter(self, level: str, checked: bool) -> None:
        if checked:
            self._filter_level = level
            self._rerender()

    def _clear(self) -> None:
        self._buffer.clear()
        self._text.clear()

    @pyqtSlot(str, str)
    def _on_log(self, level: str, message: str) -> None:
        self._buffer.append((level, message))
        # 简单级别序号
        order = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "SUCCESS": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}
        if order.get(level, 2) < order.get(self._filter_level, 1):
            return
        self._append_line(level, message)

    def _rerender(self) -> None:
        self._text.clear()
        order = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "SUCCESS": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}
        threshold = order.get(self._filter_level, 1)
        for level, message in self._buffer:
            if order.get(level, 2) < threshold:
                continue
            self._append_line(level, message)

    def _append_line(self, level: str, message: str) -> None:
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        color = LEVEL_COLORS.get(level, "#cccccc")
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")
        self._text.setTextCursor(cursor)
        self._text.verticalScrollBar().setValue(self._text.verticalScrollBar().maximum())
