"""麦克风设备枚举与「哪个麦克风有声音」的信号检测。"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np


def list_input_devices() -> list[tuple[int, str]]:
    """返回 [(设备序号, 名称)]，仅含可录音的输入设备。"""
    import sounddevice as sd

    devices: list[tuple[int, str]] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append((idx, dev["name"]))
    return devices


def detect_best_input_device(seconds: float = 3.0) -> Optional[tuple[int, str, dict]]:
    """同时监听所有输入设备，返回信号最强者。

    用户只需在检测期间对着麦克风说话即可，无需逐个尝试。
    返回 (设备序号, 名称, {序号: 音量})；无可用设备时返回 None。
    """
    import sounddevice as sd

    capture = []  # (序号, 名称, 流, 缓冲区)
    for idx, name in list_input_devices():
        try:
            info = sd.query_devices(idx)
            sr = int(info["default_samplerate"] or 16000)
            buffer: list = []

            def callback(indata, frames, time_info, status, buffer=buffer):  # noqa: ARG001
                buffer.append(indata[:, 0].copy())

            stream = sd.InputStream(
                device=idx, channels=1, samplerate=sr, dtype="float32", callback=callback
            )
            stream.start()
            capture.append((idx, name, stream, buffer))
        except Exception:
            continue

    if not capture:
        return None

    time.sleep(seconds)

    levels: dict[int, float] = {}
    best_idx = None
    best_name = ""
    best_level = -1.0
    for idx, name, stream, buffer in capture:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        if buffer:
            data = np.concatenate(buffer).astype(np.float64)
            level = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
        else:
            level = 0.0
        levels[idx] = level
        if level > best_level:
            best_idx, best_name, best_level = idx, name, level

    if best_idx is None:
        return None
    return best_idx, best_name, levels
