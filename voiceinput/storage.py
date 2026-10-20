"""SQLite 持久化：历史、词库、会话统计、元数据。

数据库位于用户数据目录，安装目录只读。所有写操作使用短连接 + WAL，设置窗口
（独立进程）与主程序可以安全并发。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    mode TEXT,
    app TEXT,
    raw_text TEXT,
    final_text TEXT,
    duration REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS terminology (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wrong TEXT NOT NULL,
    correct TEXT NOT NULL,
    protected INTEGER NOT NULL DEFAULT 0,
    weight REAL NOT NULL DEFAULT 1.0,
    created TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT,
    ended TEXT,
    mode TEXT,
    app TEXT,
    segments INTEGER,
    asr_ms REAL,
    refine_ms REAL,
    chars INTEGER
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts DESC);
CREATE INDEX IF NOT EXISTS idx_term_wrong ON terminology(wrong);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else paths.database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._legacy_imported = False
        self._init()

    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')"
            )
        self._import_legacy_history()

    def _import_legacy_history(self) -> None:
        """把旧版 history.jsonl 导入一次，然后改名保留备份。"""
        if self._legacy_imported:
            return
        legacy = paths.app_root() / "history.jsonl"
        if not legacy.exists():
            self._legacy_imported = True
            return
        try:
            rows = []
            for line in legacy.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                rows.append((str(item.get("time", "")) or _now(), "fast", "", text, text, 0.0, "legacy"))
            if rows:
                with self._lock, self._connect() as conn:
                    conn.executemany(
                        "INSERT INTO history(ts, mode, app, raw_text, final_text, duration, status)"
                        " VALUES(?,?,?,?,?,?,?)",
                        rows,
                    )
            legacy.replace(legacy.with_suffix(".jsonl.migrated"))
        except Exception:
            pass
        self._legacy_imported = True

    # ------------------------------------------------------------------ #
    # meta
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    @property
    def onboarded(self) -> bool:
        return self.get_meta("onboarded", "0") == "1"

    def mark_onboarded(self, value: bool = True) -> None:
        self.set_meta("onboarded", "1" if value else "0")

    # ------------------------------------------------------------------ #
    # history
    def add_history(
        self,
        final_text: str,
        *,
        raw_text: str = "",
        mode: str = "",
        app: str = "",
        duration: float = 0.0,
        status: str = "committed",
        max_entries: int = 500,
    ) -> int:
        if not final_text.strip():
            return 0
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO history(ts, mode, app, raw_text, final_text, duration, status)"
                " VALUES(?,?,?,?,?,?,?)",
                (_now(), mode, app, raw_text, final_text, float(duration), status),
            )
            new_id = int(cur.lastrowid or 0)
            if max_entries > 0:
                conn.execute(
                    "DELETE FROM history WHERE id NOT IN"
                    " (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                    (int(max_entries),),
                )
        return new_id

    def list_history(self, limit: int = 300) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, mode, app, raw_text, final_text, duration, status"
                " FROM history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_history(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM history")

    # ------------------------------------------------------------------ #
    # terminology
    def list_terms(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, wrong, correct, protected, weight, created"
                " FROM terminology ORDER BY LENGTH(wrong) DESC, id"
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_term(
        self, wrong: str, correct: str, *, protected: bool = False, weight: float = 1.0
    ) -> int:
        wrong, correct = wrong.strip(), correct.strip()
        if not wrong or not correct:
            return 0
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM terminology WHERE wrong=? COLLATE NOCASE", (wrong,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE terminology SET correct=?, protected=?, weight=? WHERE id=?",
                    (correct, int(protected), float(weight), row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO terminology(wrong, correct, protected, weight, created)"
                " VALUES(?,?,?,?,?)",
                (wrong, correct, int(protected), float(weight), _now()),
            )
            return int(cur.lastrowid or 0)

    def delete_term(self, term_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM terminology WHERE id=?", (int(term_id),))

    def replace_terms(self, rows: Iterable[tuple[str, str, bool]]) -> None:
        with self._lock, self._connect() as conn:
            for wrong, correct, protected in rows:
                conn.execute(
                    "INSERT INTO terminology(wrong, correct, protected, weight, created)"
                    " VALUES(?,?,?,1.0,?)",
                    (wrong, correct, int(protected), _now()),
                )

    # ------------------------------------------------------------------ #
    # sessions
    def add_session(
        self,
        *,
        started: str,
        ended: str,
        mode: str,
        app: str,
        segments: int,
        asr_ms: float,
        refine_ms: float,
        chars: int,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(started, ended, mode, app, segments, asr_ms, refine_ms, chars)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (started, ended, mode, app, int(segments), float(asr_ms), float(refine_ms), int(chars)),
            )

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            hist = conn.execute("SELECT COUNT(*) c FROM history").fetchone()["c"]
            sess = conn.execute(
                "SELECT COUNT(*) c, COALESCE(AVG(asr_ms),0) a, COALESCE(AVG(refine_ms),0) r"
                " FROM sessions"
            ).fetchone()
            terms = conn.execute("SELECT COUNT(*) c FROM terminology").fetchone()["c"]
        return {
            "history": hist,
            "sessions": sess["c"],
            "avg_asr_ms": round(float(sess["a"]), 1),
            "avg_refine_ms": round(float(sess["r"]), 1),
            "terms": terms,
        }
