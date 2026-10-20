"""诊断：模型文件、加载状态、设备、路径、内存。"""

from __future__ import annotations

import json
import platform
import sys
import time
from typing import Any

from . import modelstore, paths
from .audio import list_input_devices
from .config import load_config
from .llm import LlamaServer, process_memory_mb
from .storage import Storage


def _memory_mb() -> float:
    return process_memory_mb(__import__("os").getpid())


def collect(cfg: dict[str, Any] | None = None, *, load_test: bool = False) -> dict[str, Any]:
    cfg = cfg or load_config()
    checks = modelstore.check_models(cfg)
    storage = Storage()
    report: dict[str, Any] = {
        "version": paths.VERSION,
        "python": platform.python_version(),
        "os": platform.platform(),
        "install_dir": str(paths.app_root()),
        "data_dir": str(paths.data_root()),
        "portable": paths.is_portable(),
        "settings": str(paths.settings_path()),
        "database": str(paths.database_path()),
        "models": [c.to_dict() for c in checks],
        "models_ok": all(c.ok for c in checks),
        "model_set": modelstore.model_set_status().to_dict(),
        "devices": list_input_devices(),
        "memory_mb": _memory_mb(),
        "hotkey": cfg.get("hotkey", {}),
        "mode": cfg.get("mode"),
        "storage": storage.stats(),
        "llm": LlamaServer(cfg).status(),
        "loaded": {},
    }
    if load_test:
        loaded: dict[str, Any] = {}
        try:
            from .streaming import StreamingAsr

            t0 = time.time()
            asr = StreamingAsr(cfg)
            loaded["streaming"] = {"ok": True, "seconds": round(time.time() - t0, 2), "model": asr.model_name}
        except Exception as exc:
            loaded["streaming"] = {"ok": False, "error": str(exc)}
        try:
            from .engines import OfflineReviewer

            t0 = time.time()
            reviewer = OfflineReviewer(cfg)
            loaded["review"] = {
                "ok": True,
                "seconds": round(time.time() - t0, 2),
                "engine": reviewer.engine.name,
            }
            reviewer.close()
        except Exception as exc:
            loaded["review"] = {"ok": False, "error": str(exc)}
        try:
            server = LlamaServer(cfg)
            t0 = time.time()
            server.start()
            loaded["llm"] = {
                "ok": True,
                "seconds": round(time.time() - t0, 2),
                **server.status(),
            }
            server.stop()
        except Exception as exc:
            loaded["llm"] = {"ok": False, "error": str(exc)}
        report["loaded"] = loaded
        report["memory_mb"] = _memory_mb()
    return report


def format_text(report: dict[str, Any]) -> str:
    lines = [
        f"本地语音输入 {report['version']}  Python {report['python']}",
        f"安装目录: {report['install_dir']}",
        f"数据目录: {report['data_dir']}  (portable={report['portable']})",
        f"模式: {report['mode']}  热键: {report['hotkey'].get('key')} / {report['hotkey'].get('mode')}",
        f"进程内存: {report['memory_mb']} MB",
        f"模型集: {report.get('model_set', {}).get('actual') or '未知'} "
        f"(需要 {report.get('model_set', {}).get('required')}, "
        f"{'匹配' if report.get('model_set', {}).get('compatible') else '不匹配'})",
        "",
        "模型:",
    ]
    for item in report["models"]:
        flag = "OK " if item["ok"] else "MISS"
        lines.append(f"  [{flag}] {item['name']}: {item['path']} ({item['size']} bytes)")
    lines.append("")
    lines.append("输入设备:")
    for dev in report["devices"]:
        lines.append(f"  {dev['id']}: {dev['name']} [{dev['hostapi']}] {dev['default_samplerate']} Hz")
    if report.get("loaded"):
        lines.append("")
        lines.append("加载测试:")
        for key, value in report["loaded"].items():
            lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines)


def main(load_test: bool = False) -> int:
    report = collect(load_test=load_test)
    print(format_text(report))
    return 0 if report.get("models_ok") else 2
