"""数据目录统一管理。

安装版软件位于 Program Files（普通用户不可写），所以全部用户数据
（录制、分析结果、日志）都放在系统标准位置:
    Windows:  文档\\心电HRV数据\\
    macOS:    ~/Documents/心电HRV数据/
    Linux:    ~/Documents/心电HRV数据/

测试/特殊场景可用环境变量 HEARTHRV_DATA_DIR 重定向到任意目录。
"""

import os
from pathlib import Path

_ENV_OVERRIDE = "HEARTHRV_DATA_DIR"
DIR_NAME = "心电HRV数据"

_cached: Path | None = None


def data_root() -> Path:
    """返回数据根目录（不存在则创建），带进程内缓存。"""
    global _cached
    if _cached is not None:
        return _cached
    env = os.environ.get(_ENV_OVERRIDE)
    if env:
        root = Path(env)
    else:
        try:
            from PySide6.QtCore import QStandardPaths
            doc = QStandardPaths.writableLocation(
                QStandardPaths.DocumentsLocation)
        except Exception:
            doc = ""
        root = (Path(doc) if doc else Path.home() / "Documents") / DIR_NAME
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "录制").mkdir(parents=True, exist_ok=True)
    _cached = root
    return root


def recordings_dir() -> Path:
    return data_root() / "录制"


def logs_dir() -> Path:
    return data_root() / "logs"


def resource(rel: str) -> Path:
    """获取打包后仍可访问的资源文件路径（图标等随exe携带的文件）。"""
    base = Path(getattr(__import__("sys"), "_MEIPASS",
                         Path(__file__).resolve().parent.parent.parent))
    return base / rel
