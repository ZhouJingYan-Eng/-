"""
云台控制面板组件
- 上下左右手动控制按钮
- 模式切换（自动/手动）
- 当前角度显示
- 追踪开关
- 复位按钮
"""
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget, QCheckBox
)


class PtzPanelWidget(QWidget):
    """云台控制面板"""

    # 手动控制信号
    move_left = pyqtSignal()
    move_right = pyqtSignal()
    move_up = pyqtSignal()
    move_down = pyqtSignal()
    reset_angle = pyqtSignal()
    set_mode = pyqtSignal(str)
    set_tracking = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 标题
        title = QLabel("云台控制", self)
        title.setStyleSheet("color: #00d4ff; font-size: 14px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 追踪开关
        self._tracking_cb = QCheckBox("开启自动追踪", self)
        self._tracking_cb.setStyleSheet("color: #ddd;")
        self._tracking_cb.toggled.connect(self._on_tracking_toggled)
        layout.addWidget(self._tracking_cb)

        # 模式切换
        mode_box = QGroupBox("模式", self)
        mode_box.setStyleSheet("color: #aaa; border: 1px solid #333;")
        ml = QHBoxLayout(mode_box)
        self._auto_btn = QPushButton("自动", self)
        self._manual_btn = QPushButton("手动", self)
        self._auto_btn.setCheckable(True)
        self._manual_btn.setCheckable(True)
        self._auto_btn.setChecked(True)
        self._auto_btn.clicked.connect(lambda: self._on_mode_changed("auto"))
        self._manual_btn.clicked.connect(lambda: self._on_mode_changed("manual"))
        ml.addWidget(self._auto_btn)
        ml.addWidget(self._manual_btn)
        layout.addWidget(mode_box)

        # 方向控制
        dir_box = QGroupBox("手动控制", self)
        dir_box.setStyleSheet("color: #aaa; border: 1px solid #333;")
        grid = QGridLayout(dir_box)
        grid.setSpacing(4)

        self._btn_up = self._make_btn("↑", "向上")
        self._btn_left = self._make_btn("←", "向左")
        self._btn_right = self._make_btn("→", "向右")
        self._btn_down = self._make_btn("↓", "向下")
        self._btn_center = self._make_btn("●", "复位", accent=True)

        grid.addWidget(self._btn_up, 0, 1)
        grid.addWidget(self._btn_left, 1, 0)
        grid.addWidget(self._btn_center, 1, 1)
        grid.addWidget(self._btn_right, 1, 2)
        grid.addWidget(self._btn_down, 2, 1)
        layout.addWidget(dir_box)

        # 角度显示
        info_box = QGroupBox("当前角度", self)
        info_box.setStyleSheet("color: #aaa; border: 1px solid #333;")
        info_layout = QGridLayout(info_box)
        info_layout.addWidget(QLabel("X轴:"), 0, 0)
        info_layout.addWidget(QLabel("Y轴:"), 1, 0)
        self._lbl_x = QLabel("+0.00°")
        self._lbl_y = QLabel("+0.00°")
        self._lbl_x.setStyleSheet("color: #00ff88; font-family: Consolas; font-size: 14px;")
        self._lbl_y.setStyleSheet("color: #00ff88; font-family: Consolas; font-size: 14px;")
        info_layout.addWidget(self._lbl_x, 0, 1)
        info_layout.addWidget(self._lbl_y, 1, 1)
        layout.addWidget(info_box)

        layout.addStretch(1)

        # 连接按钮信号
        self._btn_up.pressed.connect(self.move_up.emit)
        self._btn_down.pressed.connect(self.move_down.emit)
        self._btn_left.pressed.connect(self.move_left.emit)
        self._btn_right.pressed.connect(self.move_right.emit)
        self._btn_center.clicked.connect(self.reset_angle.emit)

    def _make_btn(self, text: str, tooltip: str, accent: bool = False) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setFixedSize(48, 48)
        btn.setToolTip(tooltip)
        if accent:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a3050;
                    color: #ffcc55;
                    font-size: 18px;
                    border: 1px solid #2a5080;
                    border-radius: 24px;
                }
                QPushButton:hover { background-color: #2a5080; }
                QPushButton:pressed { background-color: #0a1a30; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #182030;
                    color: #00d4ff;
                    font-size: 18px;
                    border: 1px solid #2a3a55;
                    border-radius: 24px;
                }
                QPushButton:hover { background-color: #2a4060; }
                QPushButton:pressed { background-color: #0a1520; }
            """)
        return btn

    @pyqtSlot(bool)
    def _on_tracking_toggled(self, on: bool) -> None:
        self.set_tracking.emit(on)

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "auto":
            self._manual_btn.setChecked(False)
        else:
            self._auto_btn.setChecked(False)
        self.set_mode.emit(mode)

    @pyqtSlot(float, float)
    def on_angle(self, x: float, y: float) -> None:
        self._lbl_x.setText(f"{x:+.2f}°")
        self._lbl_y.setText(f"{y:+.2f}°")

    @pyqtSlot(str)
    def on_mode(self, mode: str) -> None:
        if mode == "auto":
            self._auto_btn.setChecked(True)
            self._manual_btn.setChecked(False)
        else:
            self._auto_btn.setChecked(False)
            self._manual_btn.setChecked(True)

    @pyqtSlot(bool)
    def on_tracking_state(self, on: bool) -> None:
        self._tracking_cb.blockSignals(True)
        self._tracking_cb.setChecked(on)
        self._tracking_cb.blockSignals(False)
