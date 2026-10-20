"""模型文件定位、校验与清单。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class ModelCheck:
    name: str
    path: Path
    exists: bool
    size: int
    expected_size: int = 0
    sha256: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        if not self.exists:
            return False
        if self.expected_size and self.size != self.expected_size:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "exists": self.exists,
            "size": self.size,
            "expected_size": self.expected_size,
            "sha256": self.sha256,
            "ok": self.ok,
            "detail": self.detail,
        }


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


@dataclass
class ModelSetStatus:
    actual: str
    required: str
    compatible: bool
    source: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "required": self.required,
            "compatible": self.compatible,
            "source": self.source,
            "message": self.message,
        }


def model_set_marker_path() -> Path:
    return paths.models_dir() / "model-set.txt"


def model_set_status() -> ModelSetStatus:
    """校验应用所需模型集与安装目录模型集是否配套。

    兼容旧版：v1.0.0 的 models 缺少 model-set.txt，但模型文件相同；
    此时按当前所需模型集兼容处理（仅一次迁移），后续版本必须带 marker。
    """
    required = paths.MODEL_SET
    marker = model_set_marker_path()
    manifest = load_manifest()
    manifest_set = str(manifest.get("model_set", "") or "").strip()
    if marker.exists():
        actual = marker.read_text(encoding="ascii", errors="ignore").strip()
        source = "model-set.txt"
    elif manifest_set:
        actual = manifest_set
        source = "manifest.json"
    else:
        actual = ""
        source = "legacy"
    compatible = actual == required
    message = ""
    if not compatible and not actual and manifest.get("models"):
        compatible = True
        message = "旧版模型集（无 model-set.txt），按当前版本兼容处理"
    elif not compatible:
        message = f"模型集不匹配：需要 {required}，实际 {actual or '未知'}"
    return ModelSetStatus(actual=actual, required=required, compatible=compatible, source=source, message=message)


def _search(root: Path, predicate) -> Path | None:
    if not root.exists():
        return None
    for path in sorted(root.rglob("*")):
        if path.is_dir() and predicate(path):
            return path
    return None


def find_streaming_dir(cfg: dict[str, Any] | None = None) -> Path | None:
    cfg = cfg or {}
    configured = str((cfg.get("streaming") or {}).get("model", "") or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = paths.models_dir() / p
        if p.is_file():
            p = p.parent
        return p if p.exists() else None

    root = paths.models_dir() / "streaming-asr"
    candidates = []
    if root.exists():
        for d in sorted(root.rglob("*")):
            if not d.is_dir():
                continue
            if list(d.glob("encoder*.onnx")) and (d / "tokens.txt").exists():
                candidates.append(d)
    if not candidates:
        # 兼容旧目录结构
        for d in sorted(paths.models_dir().rglob("*")):
            if d.is_dir() and "streaming" in d.name.lower() and list(d.glob("encoder*.onnx")):
                candidates.append(d)
    if not candidates:
        return None

    def score(p: Path) -> tuple[int, int, int]:
        name = p.name.lower()
        # 480ms 版本在准确率与 RTF 上均优于 160ms 版本（实测见性能报告）
        return (
            2 if "480ms" in name else 0,
            1 if "x-asr" in name or "punct" in name else 0,
            len(name),
        )

    return max(candidates, key=score)


def find_offline_dir(cfg: dict[str, Any] | None = None) -> Path | None:
    cfg = cfg or {}
    configured = str((cfg.get("offline") or {}).get("model", "") or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = paths.models_dir() / p
        return p if p.exists() else None

    root = paths.models_dir()
    for sub in (root / "offline-asr", root):
        if not sub.exists():
            continue
        for d in sorted(sub.rglob("*")):
            if not d.is_dir():
                continue
            if not list(d.glob("*.onnx")):
                continue
            if "sense-voice" in d.name.lower() or "sensevoice" in d.name.lower():
                return d
    for d in sorted(root.rglob("*")):
        if d.is_dir() and "paraformer" in d.name.lower() and list(d.glob("*.onnx")):
            return d
    return None


def find_llm_model(cfg: dict[str, Any] | None = None) -> Path | None:
    cfg = cfg or {}
    configured = str((cfg.get("refine") or {}).get("model", "") or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = paths.models_dir() / p
        return p if p.exists() else None
    root = paths.models_dir() / "llm"
    if not root.exists():
        return None
    ggufs = [p for p in root.glob("*.gguf") if "mmproj" not in p.name.lower()]
    if not ggufs:
        return None
    return max(ggufs, key=lambda p: p.stat().st_size)


def find_llama_server(cfg: dict[str, Any] | None = None) -> Path | None:
    cfg = cfg or {}
    configured = str((cfg.get("refine") or {}).get("runtime", "") or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = paths.models_dir() / p
        return p if p.exists() else None
    for candidate in (
        paths.models_dir() / "llm-runtime" / "llama" / "llama-server.exe",
        paths.models_dir() / "llama" / "llama-server.exe",
    ):
        if candidate.exists():
            return candidate
    return None


def _check(name: str, path: Path | None, expected_size: int = 0, detail: str = "") -> ModelCheck:
    if path is None:
        return ModelCheck(name, Path(""), False, 0, expected_size, "", detail or "未找到")
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    return ModelCheck(name, path, exists, size, expected_size, "", detail)


def check_models(cfg: dict[str, Any] | None = None) -> list[ModelCheck]:
    cfg = cfg or {}
    checks: list[ModelCheck] = []
    stream = find_streaming_dir(cfg)
    checks.append(_check("streaming-asr", stream, detail="流式主模型目录"))
    if stream:
        for fname in ("tokens.txt",):
            checks.append(_check(f"streaming-asr/{fname}", stream / fname))
        encoders = sorted(stream.glob("encoder*.onnx"))
        checks.append(_check("streaming-asr/encoder", encoders[0] if encoders else None))
        checks.append(_check("streaming-asr/decoder", stream / "decoder.onnx"))
    offline = find_offline_dir(cfg)
    checks.append(_check("offline-asr", offline, detail="复核模型目录"))
    if offline:
        onnx = sorted(offline.glob("*.onnx"))
        checks.append(_check("offline-asr/model", onnx[0] if onnx else None))
        checks.append(_check("offline-asr/tokens.txt", offline / "tokens.txt"))
    llm = find_llm_model(cfg)
    checks.append(_check("llm", llm, detail="GGUF 精修模型"))
    server = find_llama_server(cfg)
    checks.append(_check("llama-server", server, detail="本地推理运行时"))
    return checks


def manifest_path() -> Path:
    return paths.models_dir() / "manifest.json"


def load_manifest() -> dict[str, Any]:
    try:
        return json.loads(manifest_path().read_text(encoding="utf-8"))
    except Exception:
        return {"models": []}


def verify_manifest(progress=None) -> list[dict[str, Any]]:
    """按 manifest 校验每个文件的大小与 SHA-256（构建/诊断时使用）。"""
    manifest = load_manifest()
    results: list[dict[str, Any]] = []
    for item in manifest.get("models", []):
        rel = item.get("path", "")
        path = paths.models_dir() / rel
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        ok = exists and (not item.get("size") or size == int(item["size"]))
        digest = ""
        if exists and item.get("sha256"):
            digest = sha256_file(path)
            ok = ok and digest.lower() == str(item["sha256"]).lower()
        results.append(
            {
                "name": item.get("name", rel),
                "path": str(path),
                "exists": exists,
                "size": size,
                "expected_size": int(item.get("size", 0) or 0),
                "sha256": digest or item.get("sha256", ""),
                "ok": ok,
            }
        )
        if progress:
            progress(results[-1])
    return results
