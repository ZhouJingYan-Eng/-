"""
ESP32 云台追踪实时交互数字人系统 - 上位机入口
"""
import os
import sys
from pathlib import Path

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

# 设置项目根目录到 sys.path
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


def load_stylesheet() -> str:
    """加载全局 QSS"""
    qss_path = ROOT / "ui" / "styles" / "style.qss"
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def ensure_dirs() -> None:
    """创建必要的运行目录"""
    for d in ("logs", "resources/live2d", "resources/icons", "cache"):
        path = ROOT / d
        path.mkdir(parents=True, exist_ok=True)


def main() -> int:
    ensure_dirs()

    # 初始化配置
    from config.settings import ConfigLoader
    ConfigLoader.load(str(ROOT / "config" / "config.yaml"))

    # 初始化日志（在导入 core 之前）
    from core.logger import setup_logger
    setup_logger()
    from core.logger import logger
    logger.info("===== ESP32 数字人系统启动 =====")
    logger.info(f"项目根目录: {ROOT}")

    app = QApplication(sys.argv)
    app.setApplicationName("ESP32 Digital Human")
    app.setFont(QFont("Microsoft YaHei", 9))
    app.setStyleSheet(load_stylesheet())

    from ui.main_window import MainWindow
    win = MainWindow()
    win.show()

    ret = app.exec_()
    logger.info(f"系统退出，返回码 {ret}")
    return ret


if __name__ == "__main__":
    sys.exit(main())
