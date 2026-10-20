"""生成签名更新清单 release/update.json（构建/发布时使用）。

用法：
  python scripts/make_update_manifest.py --version 1.0.1 \
      --update-exe release/LocalVoiceInput-Update-x64.exe \
      --full-exe release/LocalVoiceInput-Setup-x64.exe

私钥默认 keys/update_ed25519.pem，仅构建机持有；公钥硬编码在 voiceinput/update.py。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voiceinput import paths  # noqa: E402
from voiceinput.update import canonical_bytes  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset(path: Path, base_url: str) -> dict:
    return {
        "url": f"{base_url.rstrip('/')}/{quote(path.name)}",
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--update-exe", default="release/LocalVoiceInput-Update-x64.exe")
    parser.add_argument("--full-exe", default="release/LocalVoiceInput-Setup-x64.exe")
    parser.add_argument("--portable", default="release/LocalVoiceInput-Portable-x64.zip")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--notes-url", default="")
    parser.add_argument("--private-key", default="keys/update_ed25519.pem")
    parser.add_argument("--out", default="release/update.json")
    args = parser.parse_args()

    version = args.version.lstrip("vV")
    base_url = args.base_url or f"https://github.com/pxxfrank/voiceinput/releases/download/v{version}"
    update_exe = Path(args.update_exe)
    if not update_exe.exists():
        raise SystemExit(f"缺少增量更新包：{update_exe}")
    payload: dict = {
        "schema": 1,
        "version": version,
        "channel": "stable",
        "published": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_set": paths.MODEL_SET,
        "installer": asset(update_exe, base_url),
        "release_notes_url": args.notes_url or f"{base_url.rstrip('/')}/ReleaseNotes.md",
    }
    full = Path(args.full_exe)
    if full.exists():
        payload["full_installer"] = asset(full, base_url)
    portable = Path(args.portable)
    if portable.exists():
        payload["portable"] = asset(portable, base_url)

    key_path = Path(args.private_key)
    if not key_path.exists():
        raise SystemExit(
            f"缺少签名私钥：{key_path}\n请从安全位置恢复，或重新生成密钥并更新 voiceinput/update.py 的公钥。"
        )
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("私钥必须是 Ed25519")
    signature = key.sign(canonical_bytes(payload))
    payload["signature"] = base64.b64encode(signature).decode("ascii")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {out}（版本 {version}，模型集 {paths.MODEL_SET}）")
    print(f"installer: {payload['installer']['url']}")
    print(f"sha256:    {payload['installer']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
