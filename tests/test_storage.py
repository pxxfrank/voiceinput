from __future__ import annotations

from pathlib import Path

from voiceinput.storage import Storage


def test_history_roundtrip_and_limit(tmp_path: Path):
    storage = Storage(tmp_path / "test.db")
    for i in range(5):
        storage.add_history(f"文本 {i}", max_entries=3)
    items = storage.list_history(10)
    assert len(items) == 3
    assert items[0]["final_text"] == "文本 4"


def test_terms_upsert_and_delete(tmp_path: Path):
    storage = Storage(tmp_path / "test.db")
    term_id = storage.upsert_term("未来", "蔚来", protected=True)
    rows = storage.list_terms()
    assert len(rows) == 1
    assert rows[0]["correct"] == "蔚来"
    assert rows[0]["protected"] == 1
    storage.upsert_term("未来", "蔚来汽车", protected=True)
    rows = storage.list_terms()
    assert len(rows) == 1
    assert rows[0]["correct"] == "蔚来汽车"
    storage.delete_term(rows[0]["id"])
    assert storage.list_terms() == []


def test_meta_onboarded(tmp_path: Path):
    storage = Storage(tmp_path / "test.db")
    assert not storage.onboarded
    storage.mark_onboarded(True)
    assert storage.onboarded


def test_session_stats(tmp_path: Path):
    storage = Storage(tmp_path / "test.db")
    storage.add_session(started="a", ended="b", mode="fast", app="notepad.exe", segments=2, asr_ms=100, refine_ms=50, chars=10)
    stats = storage.stats()
    assert stats["sessions"] == 1
    assert stats["avg_asr_ms"] == 100.0
