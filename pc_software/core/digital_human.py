"""
Live2D 虚拟数字人模块
- 加载 Live2D Cubism 模型 (model3.json)
- 头部姿态映射 (yaw -> ParamAngleX, pitch -> ParamAngleY, roll -> ParamAngleZ)
- 唇形同步: 接收音频音量，驱动 ParamMouthOpenY
- 待机动作: 呼吸 + 自然眨眼
- 提供渲染回调供 QOpenGLWidget 调用
"""
import math
import os
import random
import time
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from config.settings import ConfigLoader
from core.logger import logger

# Live2D Cubism SDK Python 绑定 (live2d-py)
# 同时兼容 Cubism 2 / 3+ 模型
try:
    import live2d.v3 as live2d_v3
    _HAS_V3 = True
except Exception:
    live2d_v3 = None
    _HAS_V3 = False

try:
    import live2d.v2 as live2d_v2
    _HAS_V2 = True
except Exception:
    live2d_v2 = None
    _HAS_V2 = False


_LIVE2D_AVAILABLE = _HAS_V3 or _HAS_V2


class DigitalHumanSignalHub(QObject):
    # 语音播放开始/结束
    speaking_started = pyqtSignal()
    speaking_finished = pyqtSignal()
    # 状态
    status_changed = pyqtSignal(str)


class DigitalHumanModel:
    """
    Live2D 模型封装，提供参数设置接口。
    内部根据可用后端 (V3 / V2) 选择。
    """

    def __init__(self):
        self._backend = "v3" if _HAS_V3 else ("v2" if _HAS_V2 else None)
        self._model = None
        self._loaded = False
        self._model_path = ""

    @property
    def backend(self) -> Optional[str]:
        return self._backend

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self, model_path: str) -> bool:
        """加载 model3.json / model.json"""
        if not _LIVE2D_AVAILABLE:
            logger.warning("live2d-py 未安装，Live2D 模型无法加载")
            return False
        if not os.path.exists(model_path):
            logger.error(f"Live2D 模型不存在: {model_path}")
            return False
        try:
            live2d_v3.Init()
            live2d_v3.GLLoadTarget_alpha()
            self._model = live2d_v3.LAppModel()
            self._model.LoadModelJson(model_path)
            self._loaded = True
            self._model_path = model_path
            logger.info(f"Live2D 模型加载成功: {model_path}")
            return True
        except Exception as e:
            logger.error(f"Live2D 模型加载失败: {e}")
            # 尝试 V2 后端
            try:
                if _HAS_V2:
                    self._backend = "v2"
                    live2d_v2.Init()
                    self._model = live2d_v2.LAppModel()
                    self._model.LoadModelJson(model_path)
                    self._loaded = True
                    logger.info(f"Live2D 模型 (V2 后端) 加载成功")
                    return True
            except Exception as e2:
                logger.error(f"V2 后端加载也失败: {e2}")
            return False

    def resize(self, w: int, h: int) -> None:
        if self._loaded:
            self._model.ResizeViewport(w, h)

    def update(self) -> None:
        if self._loaded:
            self._model.Update()

    def draw(self) -> None:
        if self._loaded:
            self._model.Draw()

    # ---------- 参数控制 ----------
    def set_param_float(self, name: str, value: float) -> None:
        if self._loaded:
            try:
                self._model.SetParamFloat(name, float(value))
            except Exception:
                pass

    def add_param_float(self, name: str, value: float) -> None:
        if self._loaded:
            try:
                self._model.AddParamFloat(name, float(value))
            except Exception:
                pass

    def get_param_float(self, name: str) -> float:
        if self._loaded:
            try:
                return float(self._model.GetParamFloat(name))
            except Exception:
                pass
        return 0.0

    def start_random_motion(self, group: str = "Idle", priority: int = 3) -> None:
        if self._loaded:
            try:
                self._model.StartRandomMotion(group, priority)
            except Exception:
                pass

    def start_motion(self, group: str, no: int, priority: int = 3) -> None:
        if self._loaded:
            try:
                self._model.StartMotion(group, no, priority)
            except Exception:
                pass

    def set_expression(self, name: str) -> None:
        if self._loaded:
            try:
                self._model.SetExpression(name)
            except Exception:
                pass


class DigitalHumanController(QObject):
    """
    数字人控制器
    负责姿态映射、唇形同步、待机动作。
    渲染由 UI 端的 QOpenGLWidget 调用 model 的 update/draw
    """

    # 每帧渲染信号（让 widget 调用 update/draw）
    tick = pyqtSignal(float)  # 时间戳秒

    def __init__(self, model: DigitalHumanModel):
        super().__init__()
        self._model = model
        self._cfg = ConfigLoader.get("digital_human", {})
        self._pose_cfg = self._cfg.get("head_pose", {})
        self._idle_cfg = self._cfg.get("idle", {})
        self._lip_cfg = self._cfg.get("lip_sync", {})
        self.signal = DigitalHumanSignalHub()

        # 姿态平滑
        self._pose_smoothing = float(self._pose_cfg.get("smoothing", 0.5))
        self._cur_yaw = 0.0
        self._cur_pitch = 0.0
        self._cur_roll = 0.0
        self._target_yaw = 0.0
        self._target_pitch = 0.0
        self._target_roll = 0.0

        # 唇形同步
        self._lip_smoothing = float(self._lip_cfg.get("smoothing", 0.35))
        self._lip_gain = float(self._lip_cfg.get("gain", 1.5))
        self._cur_mouth = 0.0
        self._target_mouth = 0.0
        self._speaking = False

        # 待机眨眼
        self._blink_min = float(self._idle_cfg.get("blink_interval_min", 2.0))
        self._blink_max = float(self._idle_cfg.get("blink_interval_max", 5.0))
        self._next_blink_time = time.time() + random.uniform(self._blink_min, self._blink_max)
        self._blink_phase = 0.0  # 0: 睁眼, 1: 闭眼
        self._blink_active = False
        self._blink_start_time = 0.0

        # 呼吸
        self._breath_cycle = float(self._idle_cfg.get("breath_cycle", 6.0))

        # 渲染 tick
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._on_tick)
        self._start_time = time.time()

    def start(self) -> None:
        if not self._model.is_loaded:
            self.signal.status_changed.emit("no_model")
            return
        self._timer.start()
        self.signal.status_changed.emit("running")

    def stop(self) -> None:
        self._timer.stop()
        self.signal.status_changed.emit("stopped")

    # ---------- 姿态更新 ----------
    def on_pose_updated(self, yaw: float, pitch: float, roll: float = 0.0) -> None:
        """接收真人头部姿态，更新目标值"""
        # Live2D 角度范围 [-30, 30]
        scale = float(self._pose_cfg.get("angle_x_scale", 30.0)) / 30.0
        self._target_yaw = max(-30.0, min(30.0, yaw * scale))
        scale_y = float(self._pose_cfg.get("angle_y_scale", 30.0)) / 30.0
        # 注意 Live2D 中正Y为抬头，所以 pitch 取反
        self._target_pitch = max(-30.0, min(30.0, -pitch * scale_y))
        scale_z = float(self._pose_cfg.get("angle_z_scale", 30.0)) / 30.0
        self._target_roll = max(-30.0, min(30.0, roll * scale_z))

    # ---------- 唇形同步 ----------
    def on_audio_volume(self, volume: float) -> None:
        """接收音频音量 (0~1)，驱动嘴型"""
        if self._speaking:
            self._target_mouth = min(1.0, volume * self._lip_gain)

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if speaking:
            self.signal.speaking_started.emit()
        else:
            self._target_mouth = 0.0
            self.signal.speaking_finished.emit()

    # ---------- 主循环 ----------
    def _on_tick(self) -> None:
        now = time.time()
        elapsed = now - self._start_time
        # 平滑插值姿态
        alpha = 1.0 - self._pose_smoothing
        self._cur_yaw += (self._target_yaw - self._cur_yaw) * alpha
        self._cur_pitch += (self._target_pitch - self._cur_pitch) * alpha
        self._cur_roll += (self._target_roll - self._cur_roll) * alpha

        # 写入模型参数
        self._model.set_param_float("PARAM_ANGLE_X", self._cur_yaw)
        self._model.set_param_float("PARAM_ANGLE_Y", self._cur_pitch)
        self._model.set_param_float("PARAM_ANGLE_Z", self._cur_roll)

        # 呼吸
        breath = math.sin(2 * math.pi * elapsed / self._breath_cycle) * 0.5
        self._model.set_param_float("PARAM_BREATH", breath)

        # 眨眼
        self._update_blink(now)

        # 唇形同步平滑
        lip_alpha = 1.0 - self._lip_smoothing
        self._cur_mouth += (self._target_mouth - self._cur_mouth) * lip_alpha
        self._model.set_param_float("PARAM_MOUTH_OPEN_Y", self._cur_mouth)

        # 触发 widget 重绘
        self.tick.emit(now)

    def _update_blink(self, now: float) -> None:
        if not self._blink_active and now >= self._next_blink_time:
            self._blink_active = True
            self._blink_start_time = now
            self._blink_phase = 0.0
        if self._blink_active:
            dt = now - self._blink_start_time
            # 闭眼 60ms + 睁眼 60ms 三角波
            cycle = 0.18
            if dt >= cycle:
                self._blink_active = False
                self._blink_phase = 0.0
                self._next_blink_time = now + random.uniform(self._blink_min, self._blink_max)
                self._model.set_param_float("PARAM_EYE_L_OPEN", 1.0)
                self._model.set_param_float("PARAM_EYE_R_OPEN", 1.0)
            else:
                # 三角波: 0~0.5: 1->0, 0.5~1: 0->1
                if dt < cycle / 2:
                    v = 1.0 - (dt / (cycle / 2))
                else:
                    v = (dt - cycle / 2) / (cycle / 2)
                v = max(0.0, min(1.0, v))
                self._model.set_param_float("PARAM_EYE_L_OPEN", v)
                self._model.set_param_float("PARAM_EYE_R_OPEN", v)

    def resize(self, w: int, h: int) -> None:
        self._model.resize(w, h)
