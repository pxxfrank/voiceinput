"""用户专业词库：错词纠正 + 受保护术语。"""

from __future__ import annotations

from typing import Any

from .normalizer import normalize_text
from .storage import Storage


class TerminologyManager:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._rows: list[dict[str, Any]] = []
        self._replacements: dict[str, str] = {}
        self._protected: list[str] = []
        self.reload()

    def reload(self) -> None:
        self._rows = self.storage.list_terms()
        self._replacements = {
            str(row["wrong"]): str(row["correct"]) for row in self._rows if row["wrong"]
        }
        self._protected = [
            str(row["correct"]) for row in self._rows if row["protected"] and row["correct"]
        ]

    @property
    def replacements(self) -> dict[str, str]:
        return dict(self._replacements)

    @property
    def protected(self) -> list[str]:
        return list(self._protected)

    def apply(self, text: str) -> str:
        return normalize_text(
            text,
            replacements=self._replacements,
            protected_terms=self._protected,
            canonical_terms=True,
            add_terminal=True,
        )

    def add(self, wrong: str, correct: str, *, protected: bool = False) -> int:
        term_id = self.storage.upsert_term(wrong, correct, protected=protected)
        self.reload()
        return term_id

    def remove(self, term_id: int) -> None:
        self.storage.delete_term(term_id)
        self.reload()

    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)
