from __future__ import annotations

from voiceinput import drafts, paths


def test_draft_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_root", lambda: tmp_path)
    drafts.save("当前编辑内容", "原始内容")
    data = drafts.load()
    assert data is not None
    assert data["text"] == "当前编辑内容"
    assert data["original"] == "原始内容"
    drafts.clear()
    assert drafts.load() is None


def test_empty_draft_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_root", lambda: tmp_path)
    drafts.save("   ", "x")
    assert drafts.load() is None
