"""整理结果草稿：编辑时落盘，异常退出后可恢复。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import paths


def _path() -> Path:
    return paths.data_root() / "draft-review.json"


def save(text: str, original: str = "") -> None:
    if not (text or "").strip():
        return
    data = {
        "text": text,
        "original": original,
        "saved_at": time.time(),
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load() -> dict[str, Any] | None:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not str(data.get("text", "")).strip():
        return None
    return data


def clear() -> None:
    try:
        _path().unlink(missing_ok=True)
    except Exception:
        pass
