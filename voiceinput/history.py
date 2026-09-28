"""转录历史（JSONL 持久化，位于程序目录）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import PROJECT_ROOT


def _path() -> Path:
    return PROJECT_ROOT / "history.jsonl"


def add(text: str, max_entries: int = 500) -> None:
    if not text:
        return
    path = _path()
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text}
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        _trim(path, max_entries)
    except Exception:
        pass


def _trim(path: Path, max_entries: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_entries:
        path.write_text("\n".join(lines[-max_entries:]) + "\n", encoding="utf-8")


def load(limit: int = 300) -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            pass
    items.reverse()  # 最新的排在前面
    return items


def clear() -> None:
    try:
        _path().write_text("", encoding="utf-8")
    except Exception:
        pass
