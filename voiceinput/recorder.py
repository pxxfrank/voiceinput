"""麦克风录音与音频预处理。"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

try:
    import soxr  # 高质量重采样
except ImportError:  # pragma: no cover
    soxr = None

TARGET_SR = 16000  # sherpa-onnx 模型要求的采样率


def resample_to_16k(data: np.ndarray, sr: int) -> np.ndarray:
    if data.size == 0 or sr == TARGET_SR:
        return data.astype(np.float32, copy=False)
    if soxr is not None:
        return soxr.resample(data, sr, TARGET_SR).astype(np.float32)
    # 退化方案：线性插值（仅在缺少 soxr 时使用）
    n = int(round(data.size * TARGET_SR / sr))
    x_old = np.arange(data.size, dtype=np.float64)
    x_new = np.linspace(0, data.size - 1, n)
    return np.interp(x_new, x_old, data).astype(np.float32)


def trim_silence(
    data: np.ndarray,
    sr: int = TARGET_SR,
    frame_ms: int = 20,
    threshold_db: float = -45.0,
    pad_ms: int = 120,
) -> np.ndarray:
    """按能量裁剪首尾静音，避免把环境噪声送进模型。"""
    if data.size == 0:
        return data
    frame = max(1, int(sr * frame_ms / 1000))
    n = data.size // frame
    if n == 0:
        return data
    frames = data[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-12)
    voiced = np.where(db > threshold_db)[0]
    if voiced.size == 0:
        return data[:0]
    pad = int(sr * pad_ms / 1000)
    start = max(0, voiced[0] * frame - pad)
    end = min(data.size, (voiced[-1] + 1) * frame + pad)
    return data[start:end]


def split_long_audio(
    data: np.ndarray, sr: int = TARGET_SR, max_seconds: float = 22.0
) -> list[np.ndarray]:
    """把过长的音频按静音切成若干段（每段 <= max_seconds），避免单次解码超长。

    SenseVoice 单次最佳长度约 30s，连续听写可能远超；在静音处切段再逐段解码更稳。
    """
    max_len = int(max_seconds * sr)
    if data.size <= max_len or max_len <= 0:
        return [data]
    frame = max(1, int(sr * 0.02))
    n = data.size // frame
    if n == 0:
        return [data]
    rms = np.sqrt(
        np.mean(data[: n * frame].astype(np.float64).reshape(n, frame) ** 2, axis=1) + 1e-12
    )
    silent = (20.0 * np.log10(rms + 1e-12)) < -45.0

    segments: list[np.ndarray] = []
    start = 0
    step = max(1, max_len // frame)
    while start < n:
        limit = start + step
        if limit >= n:
            segments.append(data[start * frame:])
            break
        cut = limit
        j = limit
        while j > start + 5:  # 从 limit 往前找最近的静音帧作为切点
            if silent[j]:
                cut = j
                break
            j -= 1
        segments.append(data[start * frame: cut * frame])
        start = cut
    return [seg for seg in segments if seg.size > 0]


class Recorder:
    """按住录音、松开停止的麦克风录制器。"""

    def __init__(
        self,
        device: int | str | None = None,
        max_duration: float = 60.0,
        on_max_duration: Optional[Callable[[], None]] = None,
    ) -> None:
        self.device = device
        self.max_duration = max_duration
        self.on_max_duration = on_max_duration
        self._chunks: list[np.ndarray] = []
        self._chunk_lock = threading.Lock()
        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._start_time = 0.0
        self._notified = False
        self.native_sr = TARGET_SR

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        info = sd.query_devices(self.device, "input")
        self.native_sr = int(info["default_samplerate"])
        self._chunks = []
        self._notified = False
        self._stream = sd.InputStream(
            samplerate=self.native_sr,
            device=self.device,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self._start_time = time.time()
        self._recording = True

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._chunk_lock:
            self._chunks.append(indata[:, 0].copy())
        if (
            self.max_duration
            and not self._notified
            and (time.time() - self._start_time) >= self.max_duration
        ):
            self._notified = True
            if self.on_max_duration:
                threading.Thread(target=self.on_max_duration, daemon=True).start()

    def stop(self) -> Optional[np.ndarray]:
        if not self._recording:
            return None
        self._recording = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
        with self._chunk_lock:
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return None
        data = np.concatenate(chunks).astype(np.float32)
        return resample_to_16k(data, self.native_sr)

    def snapshot(self) -> Optional[np.ndarray]:
        """返回「到目前为止」录到的音频（16k 单声道），供实时字幕使用。"""
        with self._chunk_lock:
            if not self._chunks:
                return None
            data = np.concatenate(self._chunks).astype(np.float32)
        return resample_to_16k(data, self.native_sr)
