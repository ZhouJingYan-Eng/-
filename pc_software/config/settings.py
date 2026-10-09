"""
配置加载器
统一加载 config.yaml 并提供配置访问入口
"""
import os
from pathlib import Path
from typing import Any, Dict
import yaml


class ConfigLoader:
    """单例配置加载器"""

    _instance = None
    _config: Dict[str, Any] = {}
    _base_path: Path = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = None):
        if config_path:
            self.load(config_path)

    @classmethod
    def load(cls, config_path: str) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            cls._config = yaml.safe_load(f) or {}
        cls._base_path = path.parent.parent
        return cls._config

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        获取配置项，支持点号分隔的多级路径
        例如: ConfigLoader.get("mqtt.broker", "127.0.0.1")
        """
        if not cls._config:
            return default
        keys = key.split(".")
        val = cls._config
        for k in keys:
            if not isinstance(val, dict) or k not in val:
                return default
            val = val[k]
        return val

    @classmethod
    def base_path(cls) -> Path:
        """项目根路径"""
        return cls._base_path or Path(os.getcwd())

    @classmethod
    def resource_path(cls, relative: str) -> str:
        """资源绝对路径"""
        return str(cls.base_path() / relative)


# 默认配置路径
DEFAULT_CONFIG_PATH = ConfigLoader.base_path() / "config" / "config.yaml"
if DEFAULT_CONFIG_PATH.exists():
    ConfigLoader.load(str(DEFAULT_CONFIG_PATH))
