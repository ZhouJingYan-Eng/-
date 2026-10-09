"""
主窗口
4 分区布局：视频预览 + 数字人 + 云台控制 + 日志
顶部工具栏：连接设备、开启/关闭追踪、语音交互、参数重置
"""
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QColor
from PyQt5.QtWidgets import (
    QAction, QFrame, QHBoxLayout, QMainWindow, QMessageBox,
    QPushButton, QSplitter, QStatusBar, QToolBar, QVBoxLayout, QWidget, QLabel,
)

from config.settings import ConfigLoader
from core.logger import logger
from core.mqtt_client import MqttClient
from core.video_stream import VideoReceiver
from core.face_pose import FacePoseEstimator
from core.ptz_controller import PtzController
from core.digital_human import DigitalHumanController, DigitalHumanModel
from core.voice_interaction import VoiceInteraction

from ui.widgets import (
    VideoPreviewWidget,
    DigitalHumanWidget, DigitalHumanPlaceholderWidget,
    PtzPanelWidget, LogPanelWidget,
)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESP32 云台追踪实时交互数字人系统")
        self.resize(1440, 900)

        # ===== 创建核心模块 =====
        self._mqtt = MqttClient()
        self._video = VideoReceiver()
        self._face = FacePoseEstimator()
        self._dh_model = DigitalHumanModel()
        self._digital_human = DigitalHumanController(self._dh_model)
        self._ptz = PtzController(self._mqtt)
        self._voice = VoiceInteraction()

        # ===== 创建 UI 组件 =====
        self._video_widget = VideoPreviewWidget()
        if self._dh_model.is_loaded:
            self._dh_widget = DigitalHumanWidget(self._digital_human, self)
        else:
            self._dh_widget = DigitalHumanPlaceholderWidget(self)
        self._ptz_panel = PtzPanelWidget()
        self._log_panel = LogPanelWidget()

        self._build_ui()
        self._connect_signals()

        # 启动数字人 tick
        self._digital_human.start()
        logger.info("系统已就绪，等待连接设备")

    def _build_ui(self) -> None:
        # 工具栏
        self._build_toolbar()

        # 中央布局
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # 左右分屏
        splitter_h = QSplitter(Qt.Horizontal)
        splitter_h.setHandleWidth(3)

        # 左侧：视频 + 数字人
        left_split = QSplitter(Qt.Vertical)
        left_split.setHandleWidth(3)

        # 视频区
        video_frame = self._make_frame("ESP32-CAM 实时画面", self._video_widget)
        left_split.addWidget(video_frame)

        # 数字人区
        dh_frame = self._make_frame("虚拟数字人", self._dh_widget)
        left_split.addWidget(dh_frame)
        left_split.setSizes([450, 450])

        # 中间：日志
        log_frame = self._make_frame("系统日志", self._log_panel)
        center_split = QSplitter(Qt.Vertical)
        center_split.addWidget(left_split)
        center_split.addWidget(log_frame)
        center_split.setSizes([700, 200])

        splitter_h.addWidget(center_split)

        # 右侧：控制面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self._ptz_panel)
        right_layout.addStretch(1)
        splitter_h.addWidget(right_panel)
        splitter_h.setSizes([1000, 280])

        outer.addWidget(splitter_h, 1)
        self.setCentralWidget(central)

        # 状态栏
        self._build_statusbar()

    def _make_frame(self, title: str, widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #0d1015;
                border: 1px solid #1a2030;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        label = QLabel(title, frame)
        label.setStyleSheet("color: #00d4ff; font-size: 12px; font-weight: bold; padding: 2px 4px;")
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return frame

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize().expandedTo(toolbar.iconSize()))
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #151a22;
                border: none;
                padding: 4px;
                spacing: 4px;
            }
            QToolBar QToolButton, QToolBar QPushButton {
                color: #cccccc;
                background-color: #1e2632;
                border: 1px solid #2a3a4a;
                padding: 6px 14px;
                border-radius: 3px;
            }
            QToolBar QToolButton:hover, QToolBar QPushButton:hover {
                background-color: #2a4060;
                color: #00d4ff;
            }
            QToolBar QToolButton:pressed, QToolBar QPushButton:pressed {
                background-color: #0a1520;
            }
        """)

        # 连接设备
        self._act_connect = QAction("连接设备", self)
        self._act_connect.setCheckable(True)
        self._act_connect.triggered.connect(self._on_connect)
        toolbar.addAction(self._act_connect)

        toolbar.addSeparator()

        # 开启追踪
        self._act_track = QAction("开启追踪", self)
        self._act_track.setCheckable(True)
        self._act_track.triggered.connect(self._on_toggle_tracking)
        toolbar.addAction(self._act_track)

        # 语音交互
        self._act_voice = QAction("语音交互", self)
        self._act_voice.setCheckable(True)
        self._act_voice.triggered.connect(self._on_voice_interaction)
        toolbar.addAction(self._act_voice)

        toolbar.addSeparator()

        # 参数重置
        self._act_reset = QAction("参数重置", self)
        self._act_reset.triggered.connect(self._on_reset)
        toolbar.addAction(self._act_reset)

        # 退出
        self._act_exit = QAction("退出", self)
        self._act_exit.triggered.connect(self.close)
        toolbar.addAction(self._act_exit)

        self.addToolBar(toolbar)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background-color: #151a22; color: #aaa; }")
        self._lbl_mqtt = QLabel("MQTT: 未连接")
        self._lbl_mqtt.setStyleSheet("color: #ff6b6b;")
        self._lbl_ptz = QLabel("PTZ: (0.00°, 0.00°)")
        self._lbl_ptz.setStyleSheet("color: #00ff88;")
        self._lbl_face = QLabel("FACE: 无")
        self._lbl_face.setStyleSheet("color: #ffaa55;")
        self._lbl_voice = QLabel("VOICE: 空闲")
        self._lbl_voice.setStyleSheet("color: #888;")
        sb.addPermanentWidget(self._lbl_mqtt)
        sb.addPermanentWidget(self._make_separator())
        sb.addPermanentWidget(self._lbl_ptz)
        sb.addPermanentWidget(self._make_separator())
        sb.addPermanentWidget(self._lbl_face)
        sb.addPermanentWidget(self._make_separator())
        sb.addPermanentWidget(self._lbl_voice)
        self.setStatusBar(sb)

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #333;")
        return sep

    # ---------- 信号连接 ----------
    def _connect_signals(self) -> None:
        # MQTT
        self._mqtt.signal.status_changed.connect(self._on_mqtt_status)
        self._mqtt.signal.image_received.connect(self._video.on_image_payload)
        self._mqtt.signal.ptz_status_received.connect(self._ptz.on_hardware_status)

        # 视频
        self._video.signal.frame_ready_qimage.connect(self._video_widget.on_frame)
        self._video.signal.frame_ready_ndarray.connect(self._on_video_frame)
        self._video.signal.status_changed.connect(self._video_widget.on_status)
        self._video.signal.fps_reported.connect(self._video_widget.on_fps)

        # 人脸姿态
        self._face.signal.pose_result_ready.connect(self._on_pose_result)
        self._face.signal.status_changed.connect(self._on_face_status)

        # 云台
        self._ptz.signal.angle_updated.connect(self._ptz_panel.on_angle)
        self._ptz.signal.mode_changed.connect(self._ptz_panel.on_mode)
        self._ptz.signal.tracking_state_changed.connect(self._ptz_panel.on_tracking_state)
        self._ptz.signal.command_ready.connect(lambda cmd: logger.info(
            f"PTZ 指令 -> x={cmd.x_angle:.2f} y={cmd.y_angle:.2f} mode={cmd.mode}"
        ))

        # 数字人
        self._digital_human.signal.status_changed.connect(self._on_dh_status)
        self._digital_human.tick.connect(self._on_dh_tick)

        # 语音
        self._voice.signal.status_changed.connect(self._on_voice_status)
        self._voice.signal.asr_result.connect(self._on_asr_result)
        self._voice.signal.qa_reply.connect(self._on_qa_reply)
        self._voice.signal.tts_play_started.connect(self._on_tts_start)
        self._voice.signal.tts_play_finished.connect(self._on_tts_end)
        self._voice.signal.audio_volume.connect(self._digital_human.on_audio_volume)
        self._voice.signal.tts_play_error.connect(
            lambda e: logger.error(f"TTS 播放错误: {e}")
        )

        # 云台面板
        self._ptz_panel.move_left.connect(self._ptz.manual_move_left)
        self._ptz_panel.move_right.connect(self._ptz.manual_move_right)
        self._ptz_panel.move_up.connect(self._ptz.manual_move_up)
        self._ptz_panel.move_down.connect(self._ptz.manual_move_down)
        self._ptz_panel.reset_angle.connect(self._ptz.reset_angle)
        self._ptz_panel.set_mode.connect(self._ptz.set_mode)
        self._ptz_panel.set_tracking.connect(self._ptz.set_tracking)

    # ---------- 按钮槽 ----------
    @pyqtSlot(bool)
    def _on_connect(self, checked: bool) -> None:
        if checked:
            self._mqtt.connect()
            self._act_connect.setText("断开设备")
        else:
            self._mqtt.disconnect()
            self._act_connect.setText("连接设备")

    @pyqtSlot(bool)
    def _on_toggle_tracking(self, checked: bool) -> None:
        self._ptz.set_tracking(checked)
        self._ptz.set_mode("auto" if checked else "manual")
        self._act_track.setText("关闭追踪" if checked else "开启追踪")

    @pyqtSlot(bool)
    def _on_voice_interaction(self, checked: bool) -> None:
        if checked:
            self._act_voice.setText("停止语音")
            self._voice.start_recording()
        else:
            self._act_voice.setText("语音交互")
            self._voice.stop_speaking()

    @pyqtSlot()
    def _on_reset(self) -> None:
        self._ptz.reset_angle()
        self._ptz.set_tracking(False)
        self._act_track.setChecked(False)
        self._act_track.setText("开启追踪")
        logger.info("参数已重置")

    # ---------- 数据处理槽 ----------
    @pyqtSlot(object)
    def _on_video_frame(self, frame):
        # 在主线程做姿态识别
        try:
            pose = self._face.process_frame(frame)
            if pose.detected:
                # 云台自动追踪
                self._ptz.update_with_pose(pose)
                # 数字人姿态同步
                self._digital_human.on_pose_updated(pose.yaw, pose.pitch, pose.roll)
        except Exception as e:
            logger.debug(f"视频帧处理异常: {e}")

    @pyqtSlot(object)
    def _on_pose_result(self, pose):
        if pose.detected:
            self._lbl_face.setText(
                f"FACE: Y{pose.yaw:+.1f} P{pose.pitch:+.1f} R{pose.roll:+.1f} d{pose.distance:.2f}m"
            )

    @pyqtSlot(str)
    def _on_mqtt_status(self, status: str) -> None:
        text_map = {
            "connected": "MQTT: 已连接",
            "disconnected": "MQTT: 未连接",
            "error": "MQTT: 错误",
            "reconnecting": "MQTT: 重连中",
        }
        color_map = {
            "connected": "#00ff88",
            "disconnected": "#ff6b6b",
            "error": "#ff6b6b",
            "reconnecting": "#ffaa55",
        }
        self._lbl_mqtt.setText(text_map.get(status, f"MQTT: {status}"))
        self._lbl_mqtt.setStyleSheet(f"color: {color_map.get(status, '#888')};")

    @pyqtSlot(str)
    def _on_face_status(self, status: str) -> None:
        if status == "tracking":
            pass  # 已在 pose_result 中更新
        elif status == "no_face":
            self._lbl_face.setText("FACE: 无")

    @pyqtSlot(str)
    def _on_voice_status(self, status: str) -> None:
        text_map = {
            "recording": "VOICE: 录音中",
            "asr": "VOICE: 识别中",
            "qa": "VOICE: 思考中",
            "tts": "VOICE: 播报中",
            "error": "VOICE: 错误",
        }
        self._lbl_voice.setText(text_map.get(status, f"VOICE: {status}"))
        if status in ("recording", "asr", "qa", "tts"):
            self._lbl_voice.setStyleSheet("color: #00d4ff;")
        elif status == "error":
            self._lbl_voice.setStyleSheet("color: #ff6b6b;")
        else:
            self._lbl_voice.setStyleSheet("color: #888;")

    @pyqtSlot(str)
    def _on_asr_result(self, text: str) -> None:
        if text:
            logger.info(f"[用户] {text}")

    @pyqtSlot(str)
    def _on_qa_reply(self, reply: str) -> None:
        logger.info(f"[数字人] {reply}")

    @pyqtSlot()
    def _on_tts_start(self) -> None:
        self._digital_human.set_speaking(True)

    @pyqtSlot()
    def _on_tts_end(self) -> None:
        self._digital_human.set_speaking(False)
        # 复位语音按钮
        self._act_voice.setChecked(False)
        self._act_voice.setText("语音交互")

    @pyqtSlot(str)
    def _on_dh_status(self, status: str) -> None:
        if status == "no_model":
            QMessageBox.warning(self, "数字人",
                                 "未找到 Live2D 模型文件，请在 config.yaml 中配置 model_path\n"
                                 "并将 model3.json 等文件放入 resources/live2d/ 目录。")

    @pyqtSlot(float)
    def _on_dh_tick(self, ts: float) -> None:
        if hasattr(self._dh_widget, "update"):
            self._dh_widget.update()

    # ---------- 退出 ----------
    def closeEvent(self, e) -> None:
        logger.info("系统退出中...")
        try:
            self._ptz.set_tracking(False)
            self._mqtt.disconnect()
            self._video.stop()
            self._face.release()
            self._voice.close()
            self._digital_human.stop()
        except Exception as ex:
            logger.error(f"退出清理异常: {ex}")
        super().closeEvent(e)
