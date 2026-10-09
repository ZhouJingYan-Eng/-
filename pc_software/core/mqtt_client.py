"""
MQTT 通信管理模块
负责与 ESP32 硬件双向通信：
- 订阅图像上传、云台回传、心跳主题
- 发布云台控制指令
- 自动重连
- 状态信号转发到 Qt UI
"""
import json
import time
import threading
from typing import Optional, Callable

import paho.mqtt.client as mqtt
from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import ConfigLoader
from core.logger import logger


class MqttSignalHub(QObject):
    """MQTT 事件信号中心，供 UI 监听"""

    status_changed = pyqtSignal(str)        # 连接状态: connected/disconnected/error/reconnecting
    image_received = pyqtSignal(bytes)      # 收到的图像字节流
    ptz_status_received = pyqtSignal(float, float)  # 云台回传 (x_angle, y_angle)
    heartbeat_received = pyqtSignal(str)   # 心跳消息


class MqttClient:
    """MQTT 客户端封装"""

    def __init__(self):
        self._cfg = ConfigLoader.get("mqtt", {})
        self.broker: str = self._cfg.get("broker", "127.0.0.1")
        self.port: int = int(self._cfg.get("port", 1883))
        self.client_id: str = self._cfg.get("client_id", "digital_human_pc")
        self.username: str = self._cfg.get("username", "")
        self.password: str = self._cfg.get("password", "")
        self.keepalive: int = int(self._cfg.get("keepalive", 60))
        self.topics: dict = self._cfg.get("topics", {})

        self.signal = MqttSignalHub()

        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._should_reconnect = True
        self._reconnect_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 图像分片缓冲（MQTT 大消息分片传输）
        self._image_buffer = bytearray()
        self._expected_image_size = 0

    # ---------- 生命周期 ----------
    def connect(self) -> None:
        """连接 MQTT 服务器"""
        if self._client and self._connected:
            logger.warning("MQTT 已连接，无需重复连接")
            return

        self._should_reconnect = True
        self._client = mqtt.Client(client_id=self.client_id, clean_session=True)
        if self.username:
            self._client.username_pw_set(self.username, self.password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_log = self._on_log

        try:
            self._client.connect(self.broker, self.port, self.keepalive)
            self._client.loop_start()
            logger.info(f"MQTT 正在连接 {self.broker}:{self.port}")
        except Exception as e:
            logger.error(f"MQTT 连接失败: {e}")
            self.signal.status_changed.emit("error")
            self._schedule_reconnect()

    def disconnect(self) -> None:
        """断开连接"""
        self._should_reconnect = False
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=1.0)
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._connected = False
        self.signal.status_changed.emit("disconnected")
        logger.info("MQTT 已断开")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ---------- 订阅 ----------
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("MQTT 连接成功")
            self.signal.status_changed.emit("connected")
            # 订阅主题
            for key, topic in self.topics.items():
                if key in ("image_upload", "ptz_status", "heartbeat"):
                    client.subscribe(topic, qos=0)
                    logger.info(f"订阅主题: {topic}")
        else:
            logger.error(f"MQTT 连接失败，返回码: {rc}")
            self.signal.status_changed.emit("error")
            self._schedule_reconnect()

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT 异常断开，rc={rc}，准备重连")
            self.signal.status_changed.emit("reconnecting")
            self._schedule_reconnect()
        else:
            self.signal.status_changed.emit("disconnected")

    # ---------- 消息处理 ----------
    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        try:
            topic = msg.topic
            payload = msg.payload

            # 图像帧主题
            if topic == self.topics.get("image_upload"):
                self._handle_image_payload(payload)
            # 云台状态回传
            elif topic == self.topics.get("ptz_status"):
                self._handle_ptz_status(payload)
            # 心跳
            elif topic == self.topics.get("heartbeat"):
                self.signal.heartbeat_received.emit(payload.decode("utf-8", errors="ignore"))
        except Exception as e:
            logger.error(f"处理 MQTT 消息异常: {e}")

    def _handle_image_payload(self, payload: bytes) -> None:
        """
        处理图像数据。
        协议1: 直接 JPEG 字节流 (payload 以 FF D8 开头)
        协议2: 分片 JSON {"seq": n, "total": m, "data": "base64"}
        此处同时支持两种。
        """
        # 直接 JPEG
        if len(payload) >= 2 and payload[0] == 0xFF and payload[1] == 0xD8:
            self.signal.image_received.emit(bytes(payload))
            return

        # 分片协议
        try:
            obj = json.loads(payload.decode("utf-8", errors="ignore"))
            if "data" in obj:
                import base64
                chunk = base64.b64decode(obj["data"])
                total = int(obj.get("total", 1))
                seq = int(obj.get("seq", 0))
                if total <= 1:
                    self.signal.image_received.emit(chunk)
                    return
                if seq == 0:
                    self._image_buffer = bytearray()
                self._image_buffer.extend(chunk)
                if seq + 1 >= total:
                    self.signal.image_received.emit(bytes(self._image_buffer))
                    self._image_buffer = bytearray()
        except Exception as e:
            logger.debug(f"无法解析图像 payload: {e}")

    def _handle_ptz_status(self, payload: bytes) -> None:
        try:
            obj = json.loads(payload.decode("utf-8", errors="ignore"))
            x = float(obj.get("x", 0.0))
            y = float(obj.get("y", 0.0))
            self.signal.ptz_status_received.emit(x, y)
        except Exception as e:
            logger.debug(f"无法解析 PTZ 状态: {e}")

    # ---------- 发布 ----------
    def publish_ptz_control(self, x_angle: float, y_angle: float, mode: str = "auto") -> None:
        """发布云台控制指令"""
        if not self._connected or not self._client:
            logger.warning("MQTT 未连接，无法发送控制指令")
            return
        topic = self.topics.get("ptz_control", "esp32/ptz/control")
        payload = json.dumps({
            "x": round(float(x_angle), 3),
            "y": round(float(y_angle), 3),
            "mode": mode,
            "ts": int(time.time() * 1000),
        })
        self._client.publish(topic, payload, qos=0, retain=False)

    # ---------- 自动重连 ----------
    def _schedule_reconnect(self) -> None:
        if not self._should_reconnect:
            return
        with self._lock:
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                return
            self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        backoff = 2
        while self._should_reconnect and not self._connected:
            logger.info(f"{backoff} 秒后尝试 MQTT 重连...")
            time.sleep(backoff)
            if not self._should_reconnect:
                return
            try:
                if self._client is None:
                    self.connect()
                    return
                self._client.reconnect()
                self._client.loop_start()
                logger.info("MQTT 重连请求已发出")
                # 等待 on_connect 回调
                for _ in range(20):
                    if self._connected:
                        return
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"MQTT 重连失败: {e}")
            backoff = min(backoff * 2, 30)

    def _on_log(self, client, userdata, level, buf):
        if level == mqtt.MQTT_LOG_ERR:
            logger.error(f"MQTT 内部错误: {buf}")
