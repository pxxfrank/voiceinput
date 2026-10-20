"""流式 ASR：sherpa-onnx OnlineRecognizer + VAD 端点 + 稳定/未稳定文本。

设计要点：
- 模型只加载一次，会话内复用；每段语音使用独立 stream，端点后 reset。
- 解码在专用线程，麦克风回调只做有界入队，绝不阻塞采集。
- 稳定文本单调增长，未稳定文本允许回退；避免界面抖动。
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from . import modelstore
from .audio import TARGET_SR
from .vad import EndpointTracker, EnergyVad, VadConfig

log = logging.getLogger("voiceinput.streaming")


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    return str(getattr(result, "text", "") or "").strip()


class StreamingAsr:
    """加载并持有 sherpa-onnx 流式识别器。"""

    def __init__(self, cfg: dict[str, Any]) -> None:
        import sherpa_onnx

        model_dir = modelstore.find_streaming_dir(cfg)
        if model_dir is None:
            raise FileNotFoundError(
                "未找到流式 ASR 模型。请确认安装目录 models/streaming-asr 下存在 encoder/decoder/joiner 与 tokens.txt。"
            )
        encoders = sorted(model_dir.glob("encoder*.onnx"))
        if not encoders:
            raise FileNotFoundError(f"流式模型缺少 encoder onnx：{model_dir}")
        encoder = next((p for p in encoders if ".int8." in p.name), encoders[0])
        decoder = model_dir / "decoder.onnx"
        joiner = next(
            (p for p in sorted(model_dir.glob("joiner*.onnx")) if ".int8." in p.name),
            model_dir / "joiner.onnx",
        )
        tokens = model_dir / "tokens.txt"
        for path in (encoder, decoder, joiner, tokens):
            if not path.exists():
                raise FileNotFoundError(f"流式模型文件缺失：{path}")

        threads = int(cfg.get("streaming", {}).get("threads", 4))
        log.info("加载流式模型：%s（threads=%d）", model_dir.name, threads)
        t0 = time.time()
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            num_threads=threads,
            sample_rate=TARGET_SR,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=False,
            debug=False,
        )
        self.model_dir = model_dir
        self.model_name = model_dir.name
        self.load_seconds = time.time() - t0
        log.info("流式模型加载完成：%.2fs", self.load_seconds)

    def create_stream(self):
        return self.recognizer.create_stream()

    def accept(self, stream, samples: np.ndarray) -> None:
        if samples is not None and samples.size:
            stream.accept_waveform(TARGET_SR, np.ascontiguousarray(samples, dtype=np.float32))

    def decode(self, stream) -> str:
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return _result_text(self.recognizer.get_result(stream))

    def finish(self, stream) -> str:
        stream.accept_waveform(TARGET_SR, np.zeros(int(TARGET_SR * 0.3), dtype=np.float32))
        stream.input_finished()
        return self.decode(stream)


class StableTextTracker:
    """根据连续 partial 的公共前缀计算稳定文本。

    稳定文本只增不减；英文单词未输完时不会把半个单词标为稳定。
    """

    def __init__(self, history: int = 3, min_stable: int = 2) -> None:
        self.history = max(1, int(history))
        self.min_stable = max(1, int(min_stable))
        self._texts: list[str] = []
        self._stable = ""

    def reset(self) -> None:
        self._texts = []
        self._stable = ""

    @property
    def stable(self) -> str:
        return self._stable

    def update(self, text: str) -> tuple[str, str]:
        text = (text or "").strip()
        if not text:
            return self._stable, ""
        self._texts.append(text)
        if len(self._texts) > self.history:
            self._texts = self._texts[-self.history :]
        if len(self._texts) < 2:
            # 单次结果不足以判定稳定，全部视为未稳定
            return self._stable, text
        prefix = self._texts[0]
        for item in self._texts[1:]:
            n = 0
            limit = min(len(prefix), len(item))
            while n < limit and prefix[n] == item[n]:
                n += 1
            prefix = prefix[:n]
        candidate = prefix if len(prefix) >= self.min_stable else self._stable
        if candidate.startswith(self._stable):
            if len(candidate) > len(self._stable) and not self._ends_mid_word(candidate, text):
                self._stable = candidate
        else:
            # 新结果与已稳定文本冲突：保持已稳定部分，避免界面回退
            pass
        unstable = text[len(self._stable) :] if text.startswith(self._stable) else text
        return self._stable, unstable

    @staticmethod
    def _ends_mid_word(stable: str, full: str) -> bool:
        if len(stable) >= len(full) or not stable:
            return False
        last, nxt = stable[-1], full[len(stable)]
        if last.isascii() and last.isalpha() and nxt.isascii() and nxt.isalpha():
            return True
        return False

    def flush(self, text: str) -> tuple[str, str]:
        text = (text or "").strip()
        self._stable = text
        return self._stable, ""


@dataclass
class SegmentEvent:
    audio: np.ndarray
    text: str
    duration: float
    reason: str


class StreamingSession:
    """一次热键会话内的持续流式识别。

    事件通过 ``on_event(dict)`` 回调发出：
    - ``partial``: stable / unstable / text
    - ``level``: db / peak
    - ``speech_start``
    - ``segment``: SegmentEvent
    - ``error``: message
    - ``stopped``
    """

    def __init__(
        self,
        asr: StreamingAsr,
        cfg: dict[str, Any],
        on_event: Callable[[dict], None],
        *,
        min_segment_s: float = 0.4,
        max_segment_s: float = 20.0,
    ) -> None:
        self.asr = asr
        self.cfg = cfg
        self.on_event = on_event
        self.min_segment_s = float(min_segment_s)
        self.max_segment_s = float(max_segment_s)
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=240)
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._stream = None
        self._tracker = StableTextTracker()
        self._segment_frames: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._all_frames: list[np.ndarray] = []
        self._vad_residue = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._started_at = 0.0
        self._dropped = 0
        self._last_partial_at = 0.0
        self._last_level_at = 0.0
        self._last_text = ""
        self.segments = 0
        self.decode_seconds = 0.0
        self.first_partial_ms: float | None = None
        self._speech_started_at: float | None = None

        audio_cfg = cfg.get("audio", {})
        vad_cfg = audio_cfg.get("vad", {}) or {}
        self.vad = EnergyVad(
            VadConfig(
                threshold_db=float(vad_cfg.get("threshold_db", -45.0)),
                adaptive=bool(vad_cfg.get("adaptive", True)),
                speech_start_ms=int(vad_cfg.get("speech_start_ms", 60)),
                endpoint_ms=int(vad_cfg.get("endpoint_ms", 650)),
            )
        )
        self.endpoint = EndpointTracker(self.vad, self.max_segment_s)
        self.partial_interval = float((cfg.get("streaming", {}) or {}).get("partial_interval", 0.08))

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self._stream = self.asr.create_stream()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="streaming-asr", daemon=True)
        self._thread.start()

    def feed(self, samples: np.ndarray) -> None:
        if samples is None or not len(samples):
            return
        try:
            self._queue.put_nowait(np.asarray(samples, dtype=np.float32))
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(np.asarray(samples, dtype=np.float32))
            except Exception:
                pass
            self._dropped += 1

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stopping.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("流式识别线程未在 %.1fs 内结束", timeout)

    @property
    def total_seconds(self) -> float:
        return max(0.0, time.time() - self._started_at)

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        try:
            while True:
                stopping = self._stopping.is_set()
                if stopping and self._queue.empty():
                    break
                try:
                    chunk = self._queue.get(timeout=0.08)
                except queue.Empty:
                    chunk = None
                if chunk is not None:
                    self._process(chunk, final=False)
                if stopping:
                    continue
        except Exception as exc:  # pragma: no cover - 防御
            log.exception("流式识别异常")
            self.on_event({"type": "error", "message": f"流式识别异常：{exc}"})
        finally:
            try:
                self._finalize(reason="stop")
            except Exception:
                log.exception("收尾失败")
            self.on_event({"type": "stopped"})

    def _process(self, chunk: np.ndarray, final: bool) -> None:
        t_decode = time.perf_counter()
        self.asr.accept(self._stream, chunk)
        text = self.asr.decode(self._stream)
        self.decode_seconds += time.perf_counter() - t_decode
        now = time.time()
        if text and (now - self._last_partial_at >= self.partial_interval or final):
            stable, unstable = self._tracker.update(text)
            self._last_partial_at = now
            if self.first_partial_ms is None and self._speech_started_at:
                self.first_partial_ms = round((now - self._speech_started_at) * 1000, 1)
            if (stable, unstable) != self._last_text:
                self._last_text = (stable, unstable)
                self.on_event(
                    {"type": "partial", "stable": stable, "unstable": unstable, "text": text}
                )

        level = float(np.sqrt(np.mean(np.square(chunk.astype(np.float64))) + 1e-12))
        db = 20.0 * float(np.log10(level + 1e-12))
        if now - self._last_level_at >= 0.05:
            self._last_level_at = now
            self.on_event({"type": "level", "db": db})

        # VAD 按 20ms 帧处理（保留不足一帧的尾部，跨块拼接）
        frame_len = int(TARGET_SR * 0.02)
        buffer = np.concatenate((self._vad_residue, chunk)).astype(np.float32) if self._vad_residue.size else chunk
        usable = (len(buffer) // frame_len) * frame_len
        self._vad_residue = buffer[usable:].copy()
        for i in range(0, usable, frame_len):
            frame = buffer[i : i + frame_len]
            self._all_frames.append(frame)
            if len(self._all_frames) > 1500:  # 30s 上限
                self._all_frames = self._all_frames[-1500:]
            self._preroll.append(frame)
            if len(self._preroll) > 25:
                self._preroll = self._preroll[-25:]
            event = self.endpoint.process(frame)
            if event == "start":
                self._in_speech = True
                self._segment_frames = list(self._preroll)
                self._speech_started_at = time.time()
                self.on_event({"type": "speech_start"})
            elif event in ("end", "force_end"):
                self._in_speech = False
                self._finalize(reason=event)
                self._segment_frames = []
                self._all_frames = []
                self.endpoint.reset()
                self._preroll = []
                self._tracker.reset()
                self._last_text = ""
            elif self._in_speech:
                self._segment_frames.append(frame)

    def _finalize(self, reason: str) -> None:
        if self._stream is None:
            return
        text = self.asr.finish(self._stream)
        if not self._segment_frames:
            # 没有任何 VAD 片段（例如音量很低或极短音频）：用最近 30s 音频兜底
            frames = list(self._all_frames[-int(self.max_segment_s * 50) :]) or list(self._preroll)
        else:
            frames = list(self._segment_frames)
        audio = np.concatenate(frames).astype(np.float32) if frames else np.zeros(0, dtype=np.float32)
        duration = audio.size / TARGET_SR
        if not text:
            text = self._last_text[0] + self._last_text[1] if self._last_text else ""
        self._stream = self.asr.create_stream()
        self._tracker.reset()
        self._last_text = ""

        if text.strip():
            self.segments += 1
            event = SegmentEvent(
                audio=audio,
                text=text.strip(),
                duration=duration,
                reason=reason,
            )
            self.on_event({"type": "segment", "segment": event})
