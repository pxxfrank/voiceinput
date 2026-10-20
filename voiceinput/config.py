"""配置加载、校验与保存。

配置文件位于用户数据目录（便携模式位于程序目录 data 下），绝不写入安装目录。
旧版本的仓库根目录 config.yaml 会在首次加载时自动导入。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import paths

SETTINGS_RESTART_EXIT = paths.SETTINGS_RESTART_EXIT

DEFAULTS: dict[str, Any] = {
    "mode": "auto",  # fast | smart | auto
    "hotkey": {
        "key": "f9",
        "mode": "hold",
        "continuous": "f10",
        "undo": "ctrl+alt+z",
        "commit": "ctrl+enter",
        "cancel": "esc",
    },
    "audio": {
        "device": None,
        "min_duration": 0.35,
        "max_duration": 600.0,
        "silence_timeout": 30.0,
        "trim_silence": True,
        "vad": {
            "threshold_db": -45.0,
            "adaptive": True,
            "speech_start_ms": 60,
            "endpoint_ms": 650,
            "min_segment_s": 0.4,
            "max_segment_s": 20.0,
        },
    },
    "streaming": {
        "threads": 4,
        "model": "",  # 空 = 自动在 models/streaming-asr 下查找
        "decoding": "greedy_search",
        "partial_interval": 0.08,
    },
    "review": {
        "enabled": True,
        "mode": "auto",  # off | auto | always
        "min_segment_s": 2.5,
        "timeout_s": 2.0,
        "engine": "sensevoice",
    },
    "refine": {
        "enabled": True,
        "level": "standard",  # faithful | standard | deep
        "model": "",
        "runtime": "",
        "threads": 0,  # 0 = 自动
        "context": 2048,
        "timeout_s": 12.0,
        "preload": True,
        "idle_unload_s": 900,
        "max_context_sentences": 3,
        "temperature": 0.2,
        "max_tokens": 256,
    },
    "terminology": {"auto_apply": True, "protected": []},
    "output": {
        "method": "paste",  # paste | type
        "restore_clipboard": True,
        "append_space": False,
        "append_newline": False,
        "verify_target": True,
        "type_fallback": True,
        "compat_mode": "auto",  # auto | paste | type
    },
    "ui": {
        "theme": "dark",  # dark | light | system
        "width": 720,
        "font_size": 14,
        "opacity": 1.0,
        "position": None,
        "overlay": "show",  # show | minimal | off
        "show_level": True,
        "review_auto_open": True,
    },
    "history": {"enabled": True, "max": 500, "store_audio": False},
    "feedback": {"beep": True, "tray": True},
    "logging": {"level": "INFO", "max_mb": 2, "backups": 3},
    "auto": {"smart_after_seconds": 20.0},
    "update": {
        "manifest_url": "https://github.com/pxxfrank/voiceinput/releases/latest/download/update.json",
        "auto_check": False,
    },
    "replacements": {},
}

_LEGACY_KEYS = {
    "engine",
    "model_dir",
    "threads",
    "sensevoice",
    "whisper",
    "caption",
    "replacements",
    "logging",
    "feedback",
    "history",
    "output",
    "audio",
    "hotkey",
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """把 0.x 配置映射到 1.0 结构，未知键丢弃。"""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    if "mode" in raw:
        out["mode"] = raw["mode"]

    hot = raw.get("hotkey") or {}
    out["hotkey"] = {
        k: v
        for k, v in {
            "key": hot.get("key"),
            "mode": hot.get("mode"),
            "continuous": hot.get("continuous"),
            "undo": hot.get("undo"),
            "commit": hot.get("commit"),
            "cancel": hot.get("cancel"),
        }.items()
        if v is not None
    }

    audio = raw.get("audio") or {}
    if audio:
        nested_vad = audio.get("vad") or {}
        out["audio"] = {k: v for k, v in audio.items() if k != "vad"}
        out["audio"]["vad"] = nested_vad

    if raw.get("output"):
        out["output"] = dict(raw["output"])
    if raw.get("feedback"):
        out["feedback"] = dict(raw["feedback"])
    if raw.get("history"):
        out["history"] = dict(raw["history"])
    if raw.get("logging"):
        out["logging"] = dict(raw["logging"])
    if isinstance(raw.get("replacements"), dict):
        out["replacements"] = dict(raw["replacements"])

    cap = raw.get("caption") or {}
    if cap:
        mode = cap.get("mode", "show")
        out["ui"] = {
            "overlay": {"off": "off", "dot": "minimal"}.get(mode, "show"),
            "font_size": cap.get("font_size", 14),
        }

    if raw.get("threads"):
        out.setdefault("streaming", {})["threads"] = int(raw["threads"])
    if raw.get("engine") and raw["engine"] in ("sensevoice", "paraformer"):
        out.setdefault("review", {})["engine"] = raw["engine"]
    return out


def _normalize(cfg: dict[str, Any]) -> dict[str, Any]:
    """校验并修正非法值，保证运行期不再做防御式判断。"""
    if cfg.get("mode") not in ("fast", "smart", "auto"):
        cfg["mode"] = "auto"
    hot = cfg.setdefault("hotkey", {})
    hot["mode"] = hot.get("mode") if hot.get("mode") in ("hold", "toggle") else "hold"
    for key in ("key", "continuous", "undo", "commit", "cancel"):
        if key in hot and hot[key] is not None:
            hot[key] = str(hot[key]).strip()

    audio = cfg.setdefault("audio", {})
    audio["min_duration"] = max(0.1, float(audio.get("min_duration", 0.35)))
    audio["max_duration"] = max(5.0, float(audio.get("max_duration", 600.0)))
    audio["silence_timeout"] = max(0.0, float(audio.get("silence_timeout", 30.0)))
    vad = audio.setdefault("vad", {})
    for k, default in (
        ("threshold_db", -45.0),
        ("speech_start_ms", 60),
        ("endpoint_ms", 650),
        ("min_segment_s", 0.4),
        ("max_segment_s", 20.0),
    ):
        try:
            vad[k] = float(vad.get(k, default))
        except (TypeError, ValueError):
            vad[k] = default
    vad["threshold_db"] = min(-20.0, max(-80.0, vad["threshold_db"]))
    vad["endpoint_ms"] = max(200.0, min(3000.0, vad["endpoint_ms"]))
    vad["max_segment_s"] = max(5.0, min(60.0, vad["max_segment_s"]))

    threads = int(cfg.get("streaming", {}).get("threads", 4))
    cfg.setdefault("streaming", {})["threads"] = max(1, min(16, threads))
    cfg["streaming"]["decoding"] = "greedy_search"

    review = cfg.setdefault("review", {})
    if review.get("mode") not in ("off", "auto", "always"):
        review["mode"] = "auto"
    review["timeout_s"] = max(0.2, min(10.0, float(review.get("timeout_s", 2.0))))
    review["min_segment_s"] = max(0.5, float(review.get("min_segment_s", 2.5)))

    refine = cfg.setdefault("refine", {})
    if refine.get("level") not in ("faithful", "standard", "deep"):
        refine["level"] = "standard"
    refine["threads"] = max(0, min(16, int(refine.get("threads", 0))))
    refine["timeout_s"] = max(2.0, min(60.0, float(refine.get("timeout_s", 12.0))))
    refine["context"] = max(512, min(8192, int(refine.get("context", 2048))))
    refine["max_tokens"] = max(64, min(2048, int(refine.get("max_tokens", 256))))

    ui = cfg.setdefault("ui", {})
    if ui.get("overlay") not in ("show", "minimal", "off"):
        ui["overlay"] = "show"
    if ui.get("theme") not in ("dark", "light", "system"):
        ui["theme"] = "dark"
    ui["width"] = max(420, min(1200, int(ui.get("width", 720))))
    ui["font_size"] = max(10, min(32, int(ui.get("font_size", 14))))
    ui["opacity"] = max(0.5, min(1.0, float(ui.get("opacity", 1.0))))

    out = cfg.setdefault("output", {})
    out["method"] = out.get("method") if out.get("method") in ("paste", "type") else "paste"
    out["compat_mode"] = out.get("compat_mode") if out.get("compat_mode") in ("auto", "paste", "type") else "auto"

    cfg.setdefault("feedback", {})
    cfg.setdefault("logging", {})
    cfg.setdefault("history", {})
    cfg.setdefault("terminology", {})
    cfg.setdefault("auto", {})
    cfg.setdefault("update", {})
    return cfg


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else paths.settings_path()
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
    else:
        legacy = paths.app_root() / "config.yaml"
        if legacy.exists():
            try:
                raw = _migrate_legacy(yaml.safe_load(legacy.read_text(encoding="utf-8")) or {})
            except Exception:
                raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if "mode" not in raw and any(k in raw for k in _LEGACY_KEYS):
        raw = _migrate_legacy(raw)
    return _normalize(_deep_merge(DEFAULTS, raw))


def save_config(cfg: dict[str, Any], path: Path | str | None = None) -> Path:
    path = Path(path) if path else paths.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def ensure_config() -> Path:
    path = paths.settings_path()
    if not path.exists():
        save_config(load_config())
    return path
