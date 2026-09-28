"""配置加载与默认值。"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml


def _app_root() -> Path:
    """程序根目录：开发时为项目目录，打包成 exe 后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _app_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# 设置窗口以该退出码退出时，主程序会重启自身以应用新配置
SETTINGS_RESTART_EXIT = 42

DEFAULTS: dict[str, Any] = {
    "engine": "sensevoice",  # sensevoice | paraformer | whisper
    "model_dir": "models",
    "threads": 4,
    "sensevoice": {"language": "auto", "use_itn": True},
    "whisper": {"model": "large-v3", "device": "cpu", "compute_type": "int8", "language": "zh"},
    "hotkey": {"key": "f9", "mode": "hold", "undo": "ctrl+alt+z", "continuous": "f10"},
    "audio": {
        "device": None,
        "min_duration": 0.3,
        "max_duration": 300.0,
        "trim_silence": True,
    },
    "output": {
        "method": "paste",  # paste | type
        "restore_clipboard": True,
        "append_space": True,
        "append_newline": False,
    },
    "feedback": {"beep": True, "tray": True},
    "caption": {"mode": "show", "interval": 0.5, "window": 25.0, "font_size": 15},
    "history": {"enabled": True, "max": 500},
    "replacements": {},
    "logging": {"level": "INFO", "file": "voiceinput.log"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
    else:
        user_cfg = {}
    return _deep_merge(DEFAULTS, user_cfg)


def save_default_config(path: Path | str | None = None, force: bool = False) -> Path:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if path.exists() and not force:
        return path
    text = (
        "# voiceinput 配置\n"
        "# 修改后需重启程序生效。\n\n"
        + yaml.safe_dump(DEFAULTS, allow_unicode=True, sort_keys=False, default_flow_style=False)
    )
    path.write_text(text, encoding="utf-8")
    return path


def save_config(cfg: dict[str, Any], path: Path | str | None = None) -> Path:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")
    return path


def resolve_model_dir(cfg: dict[str, Any]) -> Path:
    root = Path(cfg["model_dir"])
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root
