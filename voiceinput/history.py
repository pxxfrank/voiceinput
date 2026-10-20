"""兼容层：历史记录现在存放在 SQLite（见 storage.py）。"""

from __future__ import annotations

from .storage import Storage


def add(text: str, max_entries: int = 500) -> None:
    if text:
        Storage().add_history(text, max_entries=max_entries)


def load(limit: int = 300) -> list[dict]:
    items = Storage().list_history(limit)
    return [
        {"time": item.get("ts", ""), "text": item.get("final_text", "")}
        for item in items
    ]


def clear() -> None:
    Storage().clear_history()
