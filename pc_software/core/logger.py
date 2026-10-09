"""
统一日志模块
基于 loguru 实现，支持控制台 + 文件双输出，并提供 Qt 信号桥接
供 UI 实时显示日志
"""
import os
import sys
from loguru import logger
from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import ConfigLoader


class LogSignalBridge(QObject):
    """日志信号桥，把日志转发到 Qt 界面"""

    log_emitted = pyqtSignal(str, str)  # (level, message)

    def emit(self, level: str, message: str) -> None:
        self.log_emitted.emit(level, message)


# 全局 Qt 桥实例
_log_bridge = LogSignalBridge()


def get_log_bridge() -> LogSignalBridge:
    """供 UI 获取桥实例，连接信号"""
    return _log_bridge


class QtSink:
    """把 loguru 日志转发到 Qt 信号"""

    def __write__(self, message):
        # message 形如: "2026-10-09 10:00:00 | INFO | module - 内容\n"
        text = str(message).strip()
        if not text:
            return
        parts = text.split(" | ")
        level = "INFO"
        if len(parts) >= 2:
            level = parts[1].strip()
        _log_bridge.emit(level, text)


def setup_logger() -> None:
    """初始化日志系统"""
    cfg = ConfigLoader.get("logging", {})
    level = cfg.get("level", "INFO")
    log_file = cfg.get("file", "logs/digital_human.log")
    rotation = cfg.get("rotation", "10 MB")
    retention = cfg.get("retention", "30 days")
    console = cfg.get("console", True)

    logger.remove()

    if console:
        logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        )

    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logger.add(
        log_file,
        level=level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
    )

    logger.add(QtSink(), level=level, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}")


setup_logger()
