"""下载并解压离线 ASR 模型（一次性联网，之后完全离线）。"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .config import load_config, resolve_model_dir

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

MODELS = {
    "sensevoice": {
        "name": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "file": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
    },
    "paraformer": {
        "name": "sherpa-onnx-paraformer-zh-2023-09-14",
        "file": "sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2",
    },
}


def _progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    if total_size <= 0:
        return
    downloaded = min(block_num * block_size, total_size)
    pct = downloaded * 100 / total_size
    mb = total_size / (1024 * 1024)
    sys.stdout.write(f"\r  下载中 {pct:5.1f}% ({mb:.0f} MB)")
    sys.stdout.flush()


def download(name: str, model_dir: Path, progress: Optional[Callable[[float], None]] = None) -> None:
    """下载并解压模型。

    ``progress`` 为可选回调，接收 0~1 的进度；传入时不再向标准输出打印。
    """
    info = MODELS[name]
    target = model_dir / info["name"]
    if target.exists():
        if progress:
            progress(1.0)
        else:
            print(f"[跳过] {info['name']} 已存在")
        return

    url = f"{RELEASES}/{info['file']}"
    model_dir.mkdir(parents=True, exist_ok=True)

    if progress:

        def hook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                progress(min(block_num * block_size, total_size) / total_size)
    else:
        hook = _progress_hook
        print(f"[下载] {url}")

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / info["file"]
        urllib.request.urlretrieve(url, archive, reporthook=hook)
        if progress is None:
            sys.stdout.write("\n")
            print(f"[解压] {info['name']}")
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(model_dir)  # noqa: S202 - 来源可信的官方模型包
    if not target.exists():
        raise RuntimeError(f"解压后未找到 {target}")
    if progress is None:
        print(f"[完成] {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 voiceinput 离线 ASR 模型")
    parser.add_argument(
        "models",
        nargs="*",
        choices=[*MODELS, "all"],
        default=None,
        help="要下载的模型，默认按 config.yaml 的 engine 选择",
    )
    args = parser.parse_args()

    cfg = load_config()
    model_dir = resolve_model_dir(cfg)

    if args.models:
        names = list(MODELS) if "all" in args.models else args.models
    else:
        names = [str(cfg.get("engine", "sensevoice")).lower()]
        if names[0] == "whisper":
            print("whisper 引擎由 faster-whisper 在首次使用时自动下载，无需此脚本。")
            return
        names = [n for n in names if n in MODELS] or ["sensevoice"]

    for name in dict.fromkeys(names):
        download(name, model_dir)
    print("全部完成。现在可以运行 `run.bat` 启动。")


if __name__ == "__main__":
    main()
