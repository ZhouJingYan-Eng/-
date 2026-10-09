"""
云台追踪控制模块
- 自动模式: PID 控制器，根据画面中心偏移闭环驱动 X/Y 轴角度
- 手动模式: 按方向键微调角度
- 防抖: 一阶低通滤波 + 死区 + 历史窗口滑动平均
- 物理限位钳制
- 接收硬件回传角度形成闭环反馈
"""
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import ConfigLoader
from core.logger import logger
from core.face_pose import FacePoseResult


@dataclass
class PtzCommand:
    x_angle: float
    y_angle: float
    mode: str = "auto"   # auto / manual
    valid: bool = True


class PtzSignalHub(QObject):
    # 派发给 MQTT 的控制指令
    command_ready = pyqtSignal(object)  # PtzCommand
    # 当前角度状态（用于 UI 显示）
    angle_updated = pyqtSignal(float, float)  # x, y
    # 模式切换
    mode_changed = pyqtSignal(str)
    # 追踪状态
    tracking_state_changed = pyqtSignal(bool)


class PIDController:
    """简易 PID 控制器，带积分限幅"""

    def __init__(self, kp: float, ki: float, kd: float, out_min: float, out_max: float):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self._integral = 0.0
        self._prev_err = 0.0
        self._prev_t = None

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_err = 0.0
        self._prev_t = None

    def update(self, err: float, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        dt = 1.0 / 60.0 if self._prev_t is None else now - self._prev_t
        if dt <= 0:
            dt = 1.0 / 60.0
        d_err = (err - self._prev_err) / dt if self._prev_t is not None else 0.0
        self._integral += err * dt
        # 积分限幅
        self._integral = max(-30.0, min(30.0, self._integral))
        out = self.kp * err + self.ki * self._integral + self.kd * d_err
        out = max(self.out_min, min(self.out_max, out))
        self._prev_err = err
        self._prev_t = now
        return out


class AntiShake:
    """防抖：一阶低通 + 死区 + 历史滑窗"""

    def __init__(self, smoothing: float, dead_zone: float, jitter_threshold: float, history_size: int):
        self.smoothing = smoothing
        self.dead_zone = dead_zone
        self.jitter_threshold = jitter_threshold
        self._history: deque = deque(maxlen=max(1, history_size))
        self._last_value: Optional[float] = None

    def reset(self) -> None:
        self._history.clear()
        self._last_value = None

    def apply(self, value: float) -> float:
        # 死区
        if self._last_value is not None and abs(value - self._last_value) < self.jitter_threshold:
            if abs(value - self._last_value) < self.dead_zone:
                return self._last_value
        # 历史滑窗均值
        self._history.append(value)
        avg = sum(self._history) / len(self._history)
        # 一阶低通
        if self._last_value is None:
            smoothed = avg
        else:
            alpha = self.smoothing
            smoothed = alpha * self._last_value + (1.0 - alpha) * avg
        self._last_value = smoothed
        return smoothed


class PtzController:
    """云台控制器"""

    def __init__(self, mqtt_client=None):
        self._cfg = ConfigLoader.get("ptz", {})
        self._auto_cfg = self._cfg.get("auto", {})
        self._limit = self._cfg.get("limit", {})
        self._shake_cfg = self._cfg.get("anti_shake", {})

        self.signal = PtzSignalHub()
        self._mqtt = mqtt_client

        # 当前角度（绝对，度），由本控制器维护 + 硬件回传校准
        self._cur_x = 0.0
        self._cur_y = 0.0
        self._cur_x_real = 0.0
        self._cur_y_real = 0.0

        self._mode = "auto"
        self._tracking = False

        # PID 控制器
        ac = self._auto_cfg
        self._pid_x = PIDController(
            ac.get("pid_x", {}).get("kp", 0.12),
            ac.get("pid_x", {}).get("ki", 0.01),
            ac.get("pid_x", {}).get("kd", 0.04),
            -ac.get("max_step", 5.0),
            ac.get("max_step", 5.0),
        )
        self._pid_y = PIDController(
            ac.get("pid_y", {}).get("kp", 0.12),
            ac.get("pid_y", {}).get("ki", 0.01),
            ac.get("pid_y", {}).get("kd", 0.04),
            -ac.get("max_step", 5.0),
            ac.get("max_step", 5.0),
        )

        # 防抖
        shake = self._shake_cfg
        self._shake_x = AntiShake(
            float(shake.get("smoothing", 0.65)),
            float(ac.get("dead_zone", 0.015)),
            float(shake.get("jitter_threshold", 0.6)),
            int(shake.get("history_size", 5)),
        )
        self._shake_y = AntiShake(
            float(shake.get("smoothing", 0.65)),
            float(ac.get("dead_zone", 0.015)),
            float(shake.get("jitter_threshold", 0.6)),
            int(shake.get("history_size", 5)),
        )

    # ---------- 模式控制 ----------
    def set_mode(self, mode: str) -> None:
        if mode not in ("auto", "manual"):
            return
        if mode != self._mode:
            self._pid_x.reset()
            self._pid_y.reset()
            self._shake_x.reset()
            self._shake_y.reset()
        self._mode = mode
        self.signal.mode_changed.emit(mode)
        logger.info(f"云台模式切换: {mode}")

    def set_tracking(self, on: bool) -> None:
        self._tracking = on
        self.signal.tracking_state_changed.emit(on)
        logger.info(f"自动追踪: {'开启' if on else '关闭'}")
        if not on:
            self._pid_x.reset()
            self._pid_y.reset()
            self._shake_x.reset()
            self._shake_y.reset()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_tracking(self) -> bool:
        return self._tracking

    @property
    def current_angle(self) -> tuple:
        return (self._cur_x_real, self._cur_y_real)

    # ---------- 自动追踪 ----------
    def update_with_pose(self, pose: FacePoseResult) -> None:
        """根据人脸姿态更新云台角度"""
        if not self._tracking or self._mode != "auto":
            return
        if not pose.detected:
            # 无脸时保持原位
            return

        # 误差：人脸偏离画面中心的归一化比例
        err_x = pose.offset_x
        err_y = pose.offset_y

        # 防抖处理
        err_x_smooth = self._shake_x.apply(err_x)
        err_y_smooth = self._shake_y.apply(err_y)

        # PID 计算 → 角度增量
        dx = self._pid_x.update(err_x_smooth)
        dy = self._pid_y.update(err_y_smooth)

        # 更新当前角度
        new_x = self._cur_x + dx
        new_y = self._cur_y + dy

        # 限位
        new_x = self._clamp(new_x, self._limit.get("x_min", -90), self._limit.get("x_max", 90))
        new_y = self._clamp(new_y, self._limit.get("y_min", -45), self._limit.get("y_max", 45))

        if abs(new_x - self._cur_x) < 0.05 and abs(new_y - self._cur_y) < 0.05:
            # 角度无变化，避免无意义下发
            return

        self._cur_x = new_x
        self._cur_y = new_y
        self._cur_x_real = new_x
        self._cur_y_real = new_y

        self._publish(new_x, new_y, "auto")
        self.signal.angle_updated.emit(new_x, new_y)

    # ---------- 手动控制 ----------
    def manual_step(self, dx: float, dy: float) -> None:
        """手动微调，单位度"""
        if self._mode != "manual":
            self.set_mode("manual")
        new_x = self._clamp(self._cur_x + dx,
                            self._limit.get("x_min", -90), self._limit.get("x_max", 90))
        new_y = self._clamp(self._cur_y + dy,
                            self._limit.get("y_min", -45), self._limit.get("y_max", 45))
        self._cur_x = new_x
        self._cur_y = new_y
        self._cur_x_real = new_x
        self._cur_y_real = new_y
        self._publish(new_x, new_y, "manual")
        self.signal.angle_updated.emit(new_x, new_y)

    def manual_move_left(self, step: float = 3.0):
        self.manual_step(-step, 0.0)

    def manual_move_right(self, step: float = 3.0):
        self.manual_step(step, 0.0)

    def manual_move_up(self, step: float = 3.0):
        self.manual_step(0.0, -step)

    def manual_move_down(self, step: float = 3.0):
        self.manual_step(0.0, step)

    def reset_angle(self):
        self._cur_x = 0.0
        self._cur_y = 0.0
        self._cur_x_real = 0.0
        self._cur_y_real = 0.0
        self._publish(0.0, 0.0, "manual")
        self.signal.angle_updated.emit(0.0, 0.0)
        logger.info("云台已复位至 (0,0)")

    # ---------- 硬件回传闭环 ----------
    def on_hardware_status(self, x: float, y: float) -> None:
        """硬件回传当前角度，用于闭环校准"""
        # 校准真实角度
        self._cur_x_real = x
        self._cur_y_real = y
        # 若偏差过大，调整内部角度
        if abs(x - self._cur_x) > 5.0:
            self._cur_x = x
        if abs(y - self._cur_y) > 5.0:
            self._cur_y = y

    # ---------- 内部方法 ----------
    def _publish(self, x: float, y: float, mode: str) -> None:
        cmd = PtzCommand(x_angle=x, y_angle=y, mode=mode)
        self.signal.command_ready.emit(cmd)
        if self._mqtt and self._mqtt.is_connected:
            self._mqtt.publish_ptz_control(x, y, mode)

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))
