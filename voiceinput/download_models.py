"""构建期模型下载、布局整理与清单校验（不参与最终用户运行）。

模型版本固定，来源与许可证记录在 manifest 中。运行期绝不联网。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import modelstore, paths

STREAMING_NAME = "sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05"
STREAMING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{STREAMING_NAME}.tar.bz2"
)
OFFLINE_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
OFFLINE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{OFFLINE_NAME}.tar.bz2"
)
LLM_NAME = "Qwen3.5-2B-Q4_K_M.gguf"
LLM_URL = f"https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/{LLM_NAME}"
LLAMA_BUILD = "b11748"
LLAMA_ZIP = f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/{LLAMA_ZIP}"

LICENSES = {
    "streaming-asr": ("Apache-2.0", "https://github.com/Gilgamesh-J/X-ASR"),
    "offline-asr": (
        "FunASR Model License 1.1",
        "https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE",
    ),
    "llm": ("Apache-2.0", "https://huggingface.co/Qwen/Qwen3.5-2B"),
    "llm-runtime": ("MIT", "https://github.com/ggml-org/llama.cpp"),
}


def _sha256(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path, retries: int = 3) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"已存在，跳过下载：{dest}")
        return dest
    for attempt in range(1, retries + 1):
        try:
            print(f"下载 {url}（第 {attempt} 次）…")
            tmp = dest.with_suffix(dest.suffix + ".part")
            with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as fh:
                total = int(resp.headers.get("Content-Length", 0) or 0)
                done = 0
                while True:
                    block = resp.read(1024 * 1024)
                    if not block:
                        break
                    fh.write(block)
                    done += len(block)
                    if total and done % (50 * 1024 * 1024) < 1024 * 1024:
                        print(f"  {done / 1048576:.0f}/{total / 1048576:.0f} MB")
            tmp.replace(dest)
            return dest
        except Exception as exc:
            print(f"下载失败：{exc}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"下载失败：{url}")


def _extract_tar_bz2(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(dest)
    entries = [p for p in dest.iterdir() if p.is_dir()]
    return entries[0] if entries else dest


def ensure_streaming(refresh: bool = False) -> Path:
    target = paths.models_dir() / "streaming-asr" / STREAMING_NAME
    if target.exists() and (target / "tokens.txt").exists() and not refresh:
        return target
    archive = paths.models_dir() / "streaming-asr" / f"{STREAMING_NAME}.tar.bz2"
    download(STREAMING_URL, archive)
    tmp = paths.models_dir() / "streaming-asr" / "_extract"
    if tmp.exists():
        shutil.rmtree(tmp)
    src = _extract_tar_bz2(archive, tmp)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(src), str(target))
    shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return target


def ensure_offline(refresh: bool = False) -> Path:
    target = paths.models_dir() / "offline-asr" / "sense-voice"
    if target.exists() and (target / "model.int8.onnx").exists() and not refresh:
        return target
    archive = paths.models_dir() / "offline-asr" / f"{OFFLINE_NAME}.tar.bz2"
    download(OFFLINE_URL, archive)
    tmp = paths.models_dir() / "offline-asr" / "_extract"
    if tmp.exists():
        shutil.rmtree(tmp)
    src = _extract_tar_bz2(archive, tmp)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("model.int8.onnx", "tokens.txt", "LICENSE", "README.md"):
        if (src / name).exists():
            shutil.copy2(src / name, target / name)
    if (src / "test_wavs").exists():
        shutil.copytree(src / "test_wavs", target / "test_wavs", dirs_exist_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return target


def ensure_llm(refresh: bool = False) -> Path:
    target = paths.models_dir() / "llm" / LLM_NAME
    if target.exists() and target.stat().st_size > 100 * 1024 * 1024 and not refresh:
        return target
    return download(LLM_URL, target)


def ensure_llama(refresh: bool = False) -> Path:
    server = paths.models_dir() / "llm-runtime" / "llama" / "llama-server.exe"
    if server.exists() and not refresh:
        return server
    archive = paths.models_dir() / "llm-runtime" / LLAMA_ZIP
    download(LLAMA_URL, archive)
    dest = paths.models_dir() / "llm-runtime" / "llama"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    nested = list(dest.glob("llama-*-bin-*"))
    if nested and nested[0].is_dir():
        for item in nested[0].iterdir():
            shutil.move(str(item), str(dest / item.name))
        nested[0].rmdir()
    archive.unlink(missing_ok=True)
    return dest / "llama-server.exe"


def write_manifest() -> Path:
    entries = []
    root = paths.models_dir()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.name == "manifest.json" or path.suffix in (".log", ".part"):
            continue
        if "/_extract/" in f"/{rel}" or rel.startswith("_extract/"):
            continue
        top = rel.split("/", 1)[0]
        license_name, source = LICENSES.get(top, ("unknown", ""))
        print(f"哈希 {rel} …")
        entries.append(
            {
                "name": rel,
                "path": rel,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
                "license": license_name,
                "source": source,
            }
        )
    manifest = {
        "schema": 1,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": paths.VERSION,
        "models": entries,
    }
    out = modelstore.manifest_path()
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}（{len(entries)} 个文件）")
    return out


def verify() -> int:
    if not modelstore.manifest_path().exists():
        print("缺少 models/manifest.json，请先运行 --manifest")
        return 2
    results = modelstore.verify_manifest()
    bad = [r for r in results if not r["ok"]]
    for r in results:
        print(f"[{'OK ' if r['ok'] else 'BAD'}] {r['name']} ({r['size']} bytes)")
    print(f"{len(results) - len(bad)}/{len(results)} 通过")
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="下载缺失模型")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--manifest", action="store_true", help="生成 SHA-256 清单")
    parser.add_argument("--verify", action="store_true", help="按清单校验")
    args = parser.parse_args()
    if args.download:
        ensure_streaming(args.refresh)
        ensure_offline(args.refresh)
        ensure_llm(args.refresh)
        ensure_llama(args.refresh)
    if args.manifest:
        write_manifest()
    if args.verify:
        return verify()
    if not (args.download or args.manifest):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
