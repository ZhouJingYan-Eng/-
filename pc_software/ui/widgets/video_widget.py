"""
视频预览组件
- QLabel 显示 QImage
- 显示状态指示（无信号、卡顿、正常）
- 支持 FPS 显示
"""
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPen
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.logger import logger


class VideoPreviewWidget(QWidget):
    """视频预览"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qimage: QImage | None = None
        self._status = "disconnected"
        self._fps = 0.0
        self.setMinimumSize(320, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background-color: #0a0a0a; color: #888;")
        self._label.setText("等待视频流...")
        layout.addWidget(self._label)

    @pyqtSlot(QImage)
    def on_frame(self, qimage: QImage) -> None:
        self._qimage = qimage
        self._status = "live"
        self.update()

    @pyqtSlot(str)
    def on_status(self, status: str) -> None:
        self._status = status
        self.update()

    @pyqtSlot(float)
    def on_fps(self, fps: float) -> None:
        self._fps = fps
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 10, 10))
        if self._qimage is not None:
            scaled = self._qimage.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        else:
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, self._status_text())

        # 右上角状态标签
        painter.setPen(QPen(QColor(0, 255, 0) if self._status == "live" else QColor(255, 160, 0)))
        painter.setFont(QFont("Consolas", 10))
        painter.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignTop | Qt.AlignLeft,
                         f"FPS: {self._fps:.1f}  {self._status.upper()}")

    def _status_text(self) -> str:
        if self._status == "disconnected":
            return "未连接"
        if self._status == "stalled":
            return "画面卡顿"
        if self._status == "laggy":
            return "画面延迟"
        if self._status == "live":
            return "等待视频流..."
        return "等待视频流..."
