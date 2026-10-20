"""签名更新检查与下载安装。

更新清单使用 Ed25519 签名；应用内置公钥，构建脚本用私钥签名。
签名只保护“更新清单”，安装包本身再用 SHA-256 校验；二者都通过才允许执行。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import paths

log = logging.getLogger("voiceinput.update")

# 发布公钥（私钥 keys/update_ed25519.pem，仅构建机持有）
UPDATE_PUBLIC_KEY_B64 = "ZWwbJ4ZBPR/js7sUAIpgce453uyNrN3KBc77DCpnXhk="
DEFAULT_MANIFEST_URL = "https://github.com/pxxfrank/voiceinput/releases/latest/download/update.json"
MAX_MANIFEST_BYTES = 512 * 1024
CREATE_NO_WINDOW = 0x08000000


class UpdateError(RuntimeError):
    pass


@dataclass
class UpdateInfo:
    version: str
    model_set: str
    installer_url: str
    installer_sha256: str
    installer_size: int
    full_installer_url: str = ""
    release_notes_url: str = ""
    published: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class UpdateCheck:
    status: str  # available | current | model_mismatch | error
    message: str
    info: UpdateInfo | None = None


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    body = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest(payload: dict[str, Any]) -> None:
    signature = str(payload.get("signature", "") or "")
    if not signature:
        raise UpdateError("更新清单缺少签名")
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(UPDATE_PUBLIC_KEY_B64))
        public.verify(base64.b64decode(signature), canonical_bytes(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise UpdateError(f"更新清单签名校验失败：{exc}") from exc


def _read_source(source: str) -> bytes:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": f"LocalVoiceInput/{paths.VERSION}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise UpdateError("更新清单过大")
        return data
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path)).read_bytes()
    return Path(source).read_bytes()


def fetch_manifest(source: str = "") -> dict[str, Any]:
    source = source or DEFAULT_MANIFEST_URL
    try:
        raw = _read_source(source)
        payload = json.loads(raw.decode("utf-8"))
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"无法读取更新清单：{exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError("更新清单格式错误")
    verify_manifest(payload)
    if int(payload.get("schema", 0)) != 1:
        raise UpdateError("不支持的更新清单版本")
    return payload


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(version).lstrip("vV").replace("-", ".").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(candidate: str, current: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def check_for_update(current_version: str = "", source: str = "") -> UpdateCheck:
    current_version = current_version or paths.VERSION
    try:
        payload = fetch_manifest(source)
    except UpdateError as exc:
        return UpdateCheck("error", str(exc))
    version = str(payload.get("version", "")).strip()
    if not version:
        return UpdateCheck("error", "更新清单缺少版本号")
    if not is_newer(version, current_version):
        return UpdateCheck("current", f"已是最新版本（{current_version}）")

    model_set = str(payload.get("model_set", "")).strip()
    installer = payload.get("installer") or {}
    if not isinstance(installer, dict) or not installer.get("url"):
        return UpdateCheck("error", "更新清单缺少安装包地址")
    info = UpdateInfo(
        version=version,
        model_set=model_set,
        installer_url=str(installer.get("url", "")),
        installer_sha256=str(installer.get("sha256", "")).lower(),
        installer_size=int(installer.get("size", 0) or 0),
        full_installer_url=str((payload.get("full_installer") or {}).get("url", "")),
        release_notes_url=str(payload.get("release_notes_url", "")),
        published=str(payload.get("published", "")),
        raw=payload,
    )
    if model_set and model_set != paths.MODEL_SET:
        return UpdateCheck(
            "model_mismatch",
            f"新版本需要模型集 {model_set}，当前为 {paths.MODEL_SET}；请安装完整包。",
            info,
        )
    return UpdateCheck("available", f"发现新版本 {version}", info)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_update(
    info: UpdateInfo,
    dest_dir: Path | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    dest_dir = dest_dir or (paths.cache_dir() / "updates")
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(info.installer_url).path).name or f"LocalVoiceInput-Update-{info.version}.exe"
    dest = dest_dir / name
    if dest.exists() and info.installer_size and dest.stat().st_size == info.installer_size:
        if not info.installer_sha256 or _sha256(dest) == info.installer_sha256:
            return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    parsed = urllib.parse.urlparse(info.installer_url)
    try:
        if parsed.scheme in ("http", "https"):
            request = urllib.request.Request(
                info.installer_url,
                headers={"User-Agent": f"LocalVoiceInput/{paths.VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=30) as response, tmp.open("wb") as fh:
                total = int(response.headers.get("Content-Length", 0) or info.installer_size or 0)
                done = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    fh.write(block)
                    done += len(block)
                    if progress and total:
                        progress(min(1.0, done / total))
        elif parsed.scheme == "file":
            shutil.copyfile(Path(urllib.request.url2pathname(parsed.path)), tmp)
            if progress:
                progress(1.0)
        else:
            shutil.copyfile(info.installer_url, tmp)
            if progress:
                progress(1.0)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"下载更新失败：{exc}") from exc

    size = tmp.stat().st_size
    if info.installer_size and size != info.installer_size:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"更新包大小不符：{size} != {info.installer_size}")
    if info.installer_sha256 and _sha256(tmp) != info.installer_sha256:
        tmp.unlink(missing_ok=True)
        raise UpdateError("更新包 SHA-256 校验失败")
    tmp.replace(dest)
    return dest


def launch_installer_after_exit(installer: Path, delay_seconds: int = 2) -> None:
    """主程序退出后再启动安装器，避免安装器互斥体检测到本程序。"""
    installer = Path(installer)
    if not installer.exists():
        raise UpdateError(f"更新包不存在：{installer}")
    cmd = f'timeout /t {int(delay_seconds)} /nobreak >nul & start "" "{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
    subprocess.Popen(
        ["cmd.exe", "/c", cmd],
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )
    log.info("已计划在退出后启动更新安装器：%s", installer)
