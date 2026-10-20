"""应用路径与版本常量。

安装目录与用户数据目录严格分离：
- 安装目录（只读）：PyInstaller 解包目录 / 源码根目录，包含 exe、runtimes、models、licenses
- 用户数据目录：%LOCALAPPDATA%\\LocalVoiceInput（便携模式为 <程序目录>\\data）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "LocalVoiceInput"
APP_NAME = "本地语音输入"
APP_NAME_EN = "LocalVoiceInput"
VERSION = "1.0.0"
MODEL_SET = "2026-10-20.1"
MUTEX_NAME = "Local\\LocalVoiceInput-singleton"
SETTINGS_RESTART_EXIT = 42


def app_root() -> Path:
    """程序根目录：打包后为 exe 所在目录，开发时为仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    if os.environ.get("VOICEINPUT_PORTABLE") == "1":
        return True
    return (app_root() / "portable.flag").exists()


def data_root() -> Path:
    if is_portable():
        return app_root() / "data"
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_ID


def settings_dir() -> Path:
    return data_root() / "settings"


def settings_path() -> Path:
    return settings_dir() / "config.yaml"


def database_dir() -> Path:
    return data_root() / "database"


def database_path() -> Path:
    return database_dir() / "voiceinput.db"


def logs_dir() -> Path:
    return data_root() / "logs"


def cache_dir() -> Path:
    return data_root() / "cache"


def runtime_dir() -> Path:
    return data_root() / "runtime"


def models_dir() -> Path:
    return app_root() / "models"


def licenses_dir() -> Path:
    return app_root() / "licenses"


def ensure_user_dirs() -> None:
    for path in (settings_dir(), database_dir(), logs_dir(), cache_dir(), runtime_dir()):
        path.mkdir(parents=True, exist_ok=True)


def resource_path(name: str) -> Path:
    """程序自带的只读资源（图标等）。"""
    return app_root() / name
