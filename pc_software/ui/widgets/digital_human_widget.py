"""
Live2D 数字人渲染组件
基于 QOpenGLWidget 集成 Live2D Cubism Python SDK
"""
import os

from PyQt5.QtCore import Qt, pyqtSlot, QSize
from PyQt5.QtGui import QPainter, QColor, QFont
from PyQt5.QtWidgets import QOpenGLWidget, QWidget, QVBoxLayout, QLabel

from config.settings import ConfigLoader
from core.digital_human import DigitalHumanController, DigitalHumanModel
from core.logger import logger


class DigitalHumanWidget(QOpenGLWidget):
    """Live2D OpenGL 渲染容器"""

    def __init__(self, controller: DigitalHumanController, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._model: DigitalHumanModel = controller._model
        self.setMinimumSize(360, 480)
        self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        # Live2D 需要透明
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    def initializeGL(self) -> None:
        try:
            # 初始化 Live2D
            from OpenGL import OpenGL
            # 触发 model 的 OpenGL 资源加载（在 GL 上下文中）
            if not self._model.is_loaded:
                path = ConfigLoader.get("digital_human.model_path", "")
                if path:
                    full = ConfigLoader.resource_path(path) if not os.path.isabs(path) else path
                    self._model.load(full)
        except Exception as e:
            logger.error(f"Live2D 初始化失败: {e}")

    def resizeGL(self, w: int, h: int) -> None:
        self._controller.resize(w, h)

    def paintGL(self) -> None:
        # 清屏
        from OpenGL.GL import glClearColor, glClear, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT
        glClearColor(0.05, 0.06, 0.08, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        # 渲染模型
        self._model.update()
        try:
            self._model.draw()
        except Exception as e:
            logger.debug(f"Live2D 绘制异常: {e}")

    @pyqtSlot(float)
    def on_tick(self, _ts: float) -> None:
        self.update()


class DigitalHumanPlaceholderWidget(QWidget):
    """无 Live2D 时的占位符"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 480)
        self.setStyleSheet("background-color: #0a0d12;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("数字人模型未加载\n请检查 model3.json 路径", self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #ffaa55; font-size: 14px;")
        layout.addWidget(label)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 13, 18))
        painter.setPen(QColor(255, 170, 80))
        painter.setFont(QFont("Microsoft YaHei", 14))
        painter.drawText(self.rect(), Qt.AlignCenter, "数字人模型未加载")
