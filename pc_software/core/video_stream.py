"""
视频接收与预览模块
- 从 MQTT 信号接收 JPEG 帧字节流
- 解码为 OpenCV BGR 帧
- 通过帧缓冲与超时容错保证流畅
- 提供 Qt 信号，转发 QImage 供 UI 显示
- 通过信号把帧同步给人脸姿态识别模块
"""
import time
import threading
from collections import deque
from typing import Optional

import cv2
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QImage

from config.settings import ConfigLoader
from core.logger import logger


class VideoStreamHub(QObject):
    """视频流分发中心"""

    # 新帧 QImage，用于 UI 显示
    frame_ready_qimage = pyqtSignal(QImage)
    # 新帧 BGR ndarray，用于算法处理
    frame_ready_ndarray = pyqtSignal(np.ndarray)
    # 状态变化
    status_changed = pyqtSignal(str)
    # FPS 信号
    fps_reported = pyqtSignal(float)


class VideoReceiver:
    """
    接收 MQTT 图像字节，解码后通过 Qt 信号分发。
    """

    def __init__(self):
        self._cfg = ConfigLoader.get("video", {})
        self._fps_expected = int(self._cfg.get("fps", 25))
        self._buffer_size = int(self._cfg.get("buffer_size", 5))
        self._timeout_ms = int(self._cfg.get("timeout_ms", 500))

        self.signal = VideoStreamHub()

        # 帧缓冲
        self._frame_queue: deque = deque(maxlen=self._buffer_size)
        self._lock = threading.Lock()
        self._last_frame_time: float = 0.0
        self._last_frame: Optional[np.ndarray] = None

        # 超时检测定时器（Qt）
        self._watchdog = QTimer()
        self._watchdog.setInterval(int(self._timeout_ms))
        self._watchdog.timeout.connect(self._on_watchdog_timeout)
        self._watchdog.start()

        # FPS 统计
        self._fps_timer = QTimer()
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._report_fps)
        self._fps_timer.start()
        self._frame_count = 0

        self._running = True

    # ---------- 接收与解码 ----------
    def on_image_payload(self, payload: bytes) -> None:
        """供 MQTT 客户端调用：收到图像字节后解码并分发"""
        if not payload:
            return
        try:
            # OpenCV 解码 JPEG
            arr = np.frombuffer(payload, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.debug("图像解码失败：imdecode 返回 None")
                return
            self._handle_decoded_frame(frame)
        except Exception as e:
            logger.debug(f"图像解码异常: {e}")

    def _handle_decoded_frame(self, frame: np.ndarray) -> None:
        """成功解码后处理"""
        with self._lock:
            self._last_frame = frame.copy()
            self._last_frame_time = time.time()
            self._frame_count += 1

        # 分发 ndarray 给算法模块
        self.signal.frame_ready_ndarray.emit(frame.copy())

        # 转 QImage 给 UI 显示
        qimg = self._ndarray_to_qimage(frame)
        self.signal.frame_ready_qimage.emit(qimg)

    @staticmethod
    def _ndarray_to_qimage(frame: np.ndarray) -> QImage:
        """BGR ndarray -> QImage (RGB)"""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return qimg.copy()  # 拷贝避免 buffer 失效

    # ---------- 超时与状态 ----------
    def _on_watchdog_timeout(self) -> None:
        """超时检测：长时间无帧视为卡顿"""
        if self._last_frame_time == 0.0:
            return
        dt_ms = (time.time() - self._last_frame_time) * 1000.0
        if dt_ms > self._timeout_ms * 3:
            self.signal.status_changed.emit("stalled")
        elif dt_ms > self._timeout_ms:
            self.signal.status_changed.emit("laggy")
        else:
            self.signal.status_changed.emit("live")

    def _report_fps(self) -> None:
        fps = float(self._frame_count)
        self._frame_count = 0
        self.signal.fps_reported.emit(fps)

    # ---------- 释放 ----------
    def stop(self) -> None:
        self._running = False
        self._watchdog.stop()
        self._fps_timer.stop()
        logger.info("视频接收器已停止")
