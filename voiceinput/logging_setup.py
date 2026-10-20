"""日志初始化（仅本地文件，不记录音频）。"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import paths

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level: str = "INFO", max_mb: int = 2, backups: int = 3) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = logging.Formatter(_FORMAT, "%Y-%m-%d %H:%M:%S")
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
    try:
        paths.logs_dir().mkdir(parents=True, exist_ok=True)
        path = paths.logs_dir() / "voiceinput.log"
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max(256 * 1024, int(max_mb * 1024 * 1024)),
            backupCount=max(1, int(backups)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        pass
