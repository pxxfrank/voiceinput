"""麦克风采集、重采样与录音工具。

- WASAPI 共享模式（sounddevice/PortAudio 默认共享），不改变系统默认设备/音量，不独占。
- 有界队列：ASR 消费慢时丢弃最旧音频，绝不无限积压。
- soxr 流式重采样到 16 kHz，避免每块独立插值造成的边界失真。
- 设备拔插/流中止时尝试有限次重开，并上报错误。
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

try:
    import soxr
except ImportError:  # pragma: no cover
    soxr = None

log = logging.getLogger("voiceinput.audio")

TARGET_SR = 16000


def resample_to_16k(data: np.ndarray, sr: int) -> np.ndarray:
    if data is None or data.size == 0 or sr == TARGET_SR:
        return np.asarray(data, dtype=np.float32)
    if soxr is not None:
        return soxr.resample(np.asarray(data, dtype=np.float32), sr, TARGET_SR).astype(np.float32)
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
    if data is None or data.size == 0:
        return np.zeros(0, dtype=np.float32)
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


def split_long_audio(data: np.ndarray, sr: int = TARGET_SR, max_seconds: float = 22.0) -> list[np.ndarray]:
    max_len = int(max_seconds * sr)
    if data.size <= max_len or max_len <= 0:
        return [data]
    frame = max(1, int(sr * 0.02))
    n = data.size // frame
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
            segments.append(data[start * frame :])
            break
        cut = limit
        j = limit
        while j > start + 5:
            if silent[j]:
                cut = j
                break
            j -= 1
        segments.append(data[start * frame : cut * frame])
        start = cut
    return [seg for seg in segments if seg.size > 0]


def has_voice(samples, threshold_db: float = -45.0) -> bool:
    if samples is None or len(samples) == 0:
        return False
    data = np.asarray(samples, dtype=np.float64)
    rms = float(np.sqrt(np.mean(data ** 2) + 1e-12))
    return 20.0 * math.log10(rms + 1e-12) > threshold_db


def load_wav(path) -> tuple[np.ndarray, int]:
    """读取 PCM WAV 为 float32 单声道 + 采样率（测试/自检用）。"""
    import wave

    with wave.open(str(path), "rb") as fh:
        channels = fh.getnchannels()
        width = fh.getsampwidth()
        sr = fh.getframerate()
        raw = fh.readframes(fh.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float32) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"不支持的 WAV 位深：{width * 8} bit")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32), sr


def save_wav(path, samples: np.ndarray, sr: int = TARGET_SR) -> None:
    import wave

    data = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(pcm)


def list_input_devices() -> list[dict]:
    devices: list[dict] = []
    try:
        hostapis = sd.query_hostapis()
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) <= 0:
                continue
            host = ""
            try:
                host = str(hostapis[dev["hostapi"]]["name"])
            except Exception:
                pass
            devices.append(
                {
                    "id": idx,
                    "name": str(dev["name"]),
                    "hostapi": host,
                    "default_samplerate": int(dev.get("default_samplerate", 0) or 0),
                    "channels": int(dev.get("max_input_channels", 1)),
                }
            )
    except Exception as exc:
        log.warning("枚举音频设备失败：%s", exc)
    return devices


def default_input_device() -> Optional[int]:
    try:
        return int(sd.default.device[0])
    except Exception:
        return None


class AudioCapture:
    """持续采集麦克风，输出 16 kHz 单声道 float32 块。"""

    def __init__(
        self,
        device: int | str | None = None,
        *,
        target_sr: int = TARGET_SR,
        max_buffer_chunks: int = 300,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.device = device
        self.target_sr = target_sr
        self.on_error = on_error
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_buffer_chunks)
        self._stream: sd.InputStream | None = None
        self._native_sr = target_sr
        self._resampler = None
        self._recording = False
        self._stopping = False
        self._lock = threading.Lock()
        self._monitor: threading.Thread | None = None
        self._all_chunks: list[np.ndarray] = []
        self._collect_all = False
        self.native_sr = target_sr
        self.device_name = ""
        self.level_db = -100.0
        self.peak = 0.0
        self.dropped_chunks = 0
        self.restarts = 0
        self.last_status = ""

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        self._stopping = False
        info = sd.query_devices(self.device, "input")
        self._native_sr = int(info.get("default_samplerate") or self.target_sr)
        self.native_sr = self._native_sr
        self.device_name = str(info.get("name", ""))
        self._resampler = self._make_resampler()
        self._stream = sd.InputStream(
            samplerate=self._native_sr,
            device=self.device,
            channels=1,
            dtype="float32",
            blocksize=0,
            latency="low",
            callback=self._callback,
        )
        self._stream.start()
        self._recording = True
        self._monitor = threading.Thread(target=self._monitor_loop, name="audio-monitor", daemon=True)
        self._monitor.start()
        log.info("开始采集：%s @ %d Hz", self.device_name, self._native_sr)

    def _make_resampler(self):
        if soxr is None or self._native_sr == self.target_sr:
            return None
        try:
            return soxr.ResampleStream(self._native_sr, self.target_sr, 1, dtype="float32")
        except Exception:
            return None

    def _resample(self, mono: np.ndarray) -> np.ndarray:
        if self._native_sr == self.target_sr or mono.size == 0:
            return mono.astype(np.float32, copy=False)
        if self._resampler is not None:
            try:
                out = self._resampler.resample_chunk(mono, last=False)
                return np.asarray(out, dtype=np.float32).reshape(-1)
            except Exception:
                self._resampler = None
        return resample_to_16k(mono, self._native_sr)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            self.last_status = str(status)
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        out = self._resample(mono)
        if out.size:
            self._push(out)
            rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2) + 1e-12))
            db = 20.0 * math.log10(rms + 1e-12)
            self.level_db = 0.7 * self.level_db + 0.3 * db if self.level_db > -99 else db
            self.peak = float(np.max(np.abs(out)))
            if self._collect_all:
                self._all_chunks.append(out.copy())

    def _push(self, chunk: np.ndarray) -> None:
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                pass
            self.dropped_chunks += 1

    def read(self, timeout: float = 0.2) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list[np.ndarray]:
        chunks = []
        while True:
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    def snapshot(self) -> np.ndarray:
        with self._lock:
            chunks = list(self._all_chunks)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32)

    def begin_collect(self) -> None:
        with self._lock:
            self._all_chunks = []
            self._collect_all = True

    def end_collect(self) -> np.ndarray:
        data = self.snapshot()
        with self._lock:
            self._collect_all = False
            self._all_chunks = []
        return data

    def _monitor_loop(self) -> None:
        while self._recording and not self._stopping:
            time.sleep(0.5)
            stream = self._stream
            if stream is not None and not stream.active and not self._stopping:
                log.warning("音频流已停止，尝试恢复…")
                try:
                    if self.restarts < 3:
                        stream.start()
                        self.restarts += 1
                        log.info("音频流已恢复（第 %d 次）", self.restarts)
                    else:
                        self._recording = False
                        if self.on_error:
                            self.on_error("麦克风连接中断，且多次恢复失败。请检查设备后重试。")
                        return
                except Exception as exc:
                    self._recording = False
                    if self.on_error:
                        self.on_error(f"麦克风连接中断：{exc}")
                    return

    def stop(self) -> None:
        if not self._recording:
            return
        self._stopping = True
        self._recording = False
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if self._resampler is not None:
            try:
                self._resampler.clear()
            except Exception:
                pass
        log.info("停止采集")

    def stop_and_collect(self) -> np.ndarray:
        self.stop()
        return self.end_collect() if self._collect_all else self.snapshot()


class Recorder:
    """兼容旧接口：整段录音（设置页麦克风测试使用）。"""

    def __init__(self, device=None, max_duration: float = 60.0, on_max_duration=None) -> None:
        self.device = device
        self.max_duration = max_duration
        self.on_max_duration = on_max_duration
        self._capture: AudioCapture | None = None
        self._timer: threading.Timer | None = None

    @property
    def recording(self) -> bool:
        return bool(self._capture and self._capture.recording)

    @property
    def native_sr(self) -> int:
        return self._capture.native_sr if self._capture else TARGET_SR

    @property
    def level_db(self) -> float:
        return self._capture.level_db if self._capture else -100.0

    def start(self) -> None:
        self._capture = AudioCapture(self.device)
        self._capture.begin_collect()
        self._capture.start()
        if self.max_duration and self.on_max_duration:
            self._timer = threading.Timer(self.max_duration, self.on_max_duration)
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> np.ndarray | None:
        if self._timer:
            self._timer.cancel()
        if not self._capture:
            return None
        data = self._capture.stop_and_collect()
        self._capture = None
        return data if data.size else None
