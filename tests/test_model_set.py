from __future__ import annotations

import json
from pathlib import Path

from voiceinput import modelstore, paths


def _setup(tmp_path: Path, monkeypatch, marker: str | None, manifest_set: str | None):
    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path)
    manifest = {"schema": 1, "models": [{"name": "x"}]}
    if manifest_set is not None:
        manifest["model_set"] = manifest_set
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if marker is not None:
        (tmp_path / "model-set.txt").write_text(marker + "\n", encoding="ascii")


def test_matching_marker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, paths.MODEL_SET, paths.MODEL_SET)
    status = modelstore.model_set_status()
    assert status.compatible
    assert status.actual == paths.MODEL_SET


def test_mismatched_marker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "old-set", "old-set")
    status = modelstore.model_set_status()
    assert not status.compatible
    assert "不匹配" in status.message


def test_legacy_without_marker_is_compatible(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, None, None)
    status = modelstore.model_set_status()
    assert status.compatible
    assert status.source == "legacy"


def test_manifest_set_used_when_marker_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, None, "other-set")
    status = modelstore.model_set_status()
    assert not status.compatible
    assert status.source == "manifest.json"
