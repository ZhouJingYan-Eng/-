"""UI 子组件包"""
from .video_widget import VideoPreviewWidget
from .digital_human_widget import DigitalHumanWidget, DigitalHumanPlaceholderWidget
from .ptz_panel import PtzPanelWidget
from .log_panel import LogPanelWidget

__all__ = [
    "VideoPreviewWidget",
    "DigitalHumanWidget",
    "DigitalHumanPlaceholderWidget",
    "PtzPanelWidget",
    "LogPanelWidget",
]
