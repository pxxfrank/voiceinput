from __future__ import annotations

import json
from pathlib import Path

import pytest

from voiceinput import update


FIXTURE = Path(__file__).parent / "fixtures" / "update-valid.json"


def test_version_compare():
    assert update.is_newer("1.0.1", "1.0.0")
    assert not update.is_newer("1.0.0", "1.0.0")
    assert update.is_newer("v1.2.0", "1.1.9")
    assert not update.is_newer("1.0.0", "1.0.1")


def test_signed_manifest_available():
    assert FIXTURE.exists(), "缺少签名更新清单 fixture"
    result = update.check_for_update("1.0.0", str(FIXTURE))
    assert result.status == "available"
    assert result.info and result.info.version == "9.9.9"
    assert result.info.installer_sha256


def test_same_version_is_current():
    result = update.check_for_update("9.9.9", str(FIXTURE))
    assert result.status == "current"


def test_tampered_manifest_rejected(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["version"] = "9.9.10"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = update.check_for_update("1.0.0", str(bad))
    assert result.status == "error"
    assert "签名" in result.message


def test_canonical_bytes_stable():
    a = {"b": 2, "a": 1, "signature": "x"}
    b = {"a": 1, "b": 2}
    assert update.canonical_bytes(a) == update.canonical_bytes(b)
