"""自检工具：用一段音频验证模型是否可用。

用法：
    python -m voiceinput.selftest                       # 用模型自带的测试音频
    python -m voiceinput.selftest path/to/audio.wav     # 用指定 wav 文件
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

from .config import load_config, resolve_model_dir
from .engines import build_engine
from .recorder import TARGET_SR, resample_to_16k


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())

    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"不支持的位宽：{width * 8} bit")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32), sr


def _default_wavs() -> list[Path]:
    root = resolve_model_dir(load_config())
    for child in sorted(root.iterdir()) if root.exists() else []:
        wavs = child / "test_wavs"
        if wavs.is_dir():
            return [wavs / "zh.wav", wavs / "en.wav"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="voiceinput 自检")
    parser.add_argument("wav", nargs="*", help="待转写的 wav 文件（默认用模型自带测试音频）")
    args = parser.parse_args()

    cfg = load_config()
    print(f"引擎：{cfg.get('engine')}  模型目录：{resolve_model_dir(cfg)}")

    t0 = time.time()
    engine = build_engine(cfg)
    print(f"模型加载完成（{time.time() - t0:.1f}s）：{engine.name}")

    wavs = [Path(p) for p in args.wav] or _default_wavs()
    if not wavs:
        print("没有可用的测试音频，请传入 wav 路径。")
        return 1

    for wav in wavs:
        if not wav.exists():
            print(f"[跳过] 文件不存在：{wav}")
            continue
        samples, sr = read_wav(wav)
        samples = resample_to_16k(samples, sr)
        t1 = time.time()
        text = engine.transcribe(samples, TARGET_SR)
        dt = time.time() - t1
        audio_len = samples.size / TARGET_SR
        print(f"\n{wav.name}  音频 {audio_len:.2f}s  耗时 {dt:.2f}s  (RTF {dt / audio_len:.3f})")
        print(f"  文本：{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
