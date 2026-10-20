"""离线 ASR 引擎（复核 / 忠实转录）。

复核模型按需调用，有超时与忙闲状态；绝不假设第二模型一定更准确。
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

import numpy as np

from . import modelstore
from .audio import TARGET_SR

log = logging.getLogger("voiceinput.asr")


def _pick_onnx(model_dir: Path) -> Path:
    for name in ("model.int8.onnx", "model.onnx"):
        candidate = model_dir / name
        if candidate.exists():
            return candidate
    for candidate in sorted(model_dir.glob("*.onnx")):
        if "int8" in candidate.name:
            return candidate
    onnx_files = sorted(model_dir.glob("*.onnx"))
    if onnx_files:
        return onnx_files[0]
    raise FileNotFoundError(f"在 {model_dir} 下未找到 .onnx 模型文件。")


class ASREngine(ABC):
    name = "base"

    @abstractmethod
    def transcribe(self, samples: np.ndarray, sample_rate: int = TARGET_SR) -> str:
        ...


class SenseVoiceEngine(ASREngine):
    name = "SenseVoice-Small"

    def __init__(self, cfg: dict[str, Any]) -> None:
        import sherpa_onnx

        model_dir = modelstore.find_offline_dir(cfg)
        if model_dir is None:
            raise FileNotFoundError("未找到离线复核模型（SenseVoice）。")
        model = _pick_onnx(model_dir)
        tokens = model_dir / "tokens.txt"
        if not tokens.exists():
            raise FileNotFoundError(f"缺少 tokens.txt：{model_dir}")
        log.info("加载 SenseVoice：%s", model)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            num_threads=int(cfg.get("streaming", {}).get("threads", 4)),
            use_itn=True,
            language="auto",
            debug=False,
        )
        self.model_dir = model_dir

    def transcribe(self, samples: np.ndarray, sample_rate: int = TARGET_SR) -> str:
        if samples is None or len(samples) == 0:
            return ""
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, np.ascontiguousarray(samples, dtype=np.float32))
        self.recognizer.decode_stream(stream)
        return str(stream.result.text).strip()


class ParaformerEngine(ASREngine):
    name = "Paraformer-zh"

    def __init__(self, cfg: dict[str, Any]) -> None:
        import sherpa_onnx

        model_dir = modelstore.find_offline_dir(cfg)
        if model_dir is None:
            raise FileNotFoundError("未找到 Paraformer 模型。")
        model = _pick_onnx(model_dir)
        tokens = model_dir / "tokens.txt"
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(model),
            tokens=str(tokens),
            num_threads=int(cfg.get("streaming", {}).get("threads", 4)),
            debug=False,
        )
        self.model_dir = model_dir

    def transcribe(self, samples: np.ndarray, sample_rate: int = TARGET_SR) -> str:
        if samples is None or len(samples) == 0:
            return ""
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, np.ascontiguousarray(samples, dtype=np.float32))
        self.recognizer.decode_stream(stream)
        return str(stream.result.text).strip()


class WhisperEngine(ASREngine):
    name = "faster-whisper"

    def __init__(self, cfg: dict[str, Any]) -> None:
        from faster_whisper import WhisperModel

        w = cfg.get("whisper", {}) or {}
        size = str(w.get("model", "large-v3"))
        self.language = w.get("language", "zh") or None
        self.model = WhisperModel(
            size,
            device=str(w.get("device", "cpu")),
            compute_type=str(w.get("compute_type", "int8")),
            download_root=str(modelstore.paths.models_dir() / "whisper"),
        )
        self.model_dir = modelstore.paths.models_dir() / "whisper"

    def transcribe(self, samples: np.ndarray, sample_rate: int = TARGET_SR) -> str:
        segments, _info = self.model.transcribe(
            np.asarray(samples, dtype=np.float32), language=self.language, beam_size=5, vad_filter=True
        )
        return "".join(seg.text for seg in segments).strip()


_ENGINES = {
    "sensevoice": SenseVoiceEngine,
    "paraformer": ParaformerEngine,
    "whisper": WhisperEngine,
}


def build_engine(cfg: dict[str, Any]) -> ASREngine:
    key = str((cfg.get("review") or {}).get("engine") or "sensevoice").lower()
    if key not in _ENGINES:
        key = "sensevoice"
    return _ENGINES[key](cfg)


class OfflineReviewer:
    """带超时、忙闲保护与统计的离线复核器。"""

    def __init__(self, cfg: dict[str, Any], engine: ASREngine | None = None) -> None:
        self.cfg = cfg
        self.enabled = bool((cfg.get("review") or {}).get("enabled", True))
        self.timeout_s = float((cfg.get("review") or {}).get("timeout_s", 2.0))
        self.engine = engine or build_engine(cfg)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-review")
        self._lock = threading.Lock()
        self._busy = False
        self._future: Future | None = None
        self.calls = 0
        self.timeouts = 0
        self.skipped = 0
        self.errors = 0
        self.total_ms = 0.0

    @property
    def busy(self) -> bool:
        return self._busy

    def review(self, samples: np.ndarray, timeout: float | None = None) -> str | None:
        if not self.enabled or samples is None or len(samples) == 0:
            return None
        with self._lock:
            if self._busy:
                self.skipped += 1
                return None
            self._busy = True
            self.calls += 1
            t0 = time.time()
            future = self._executor.submit(self.engine.transcribe, samples, TARGET_SR)
            self._future = future
        try:
            text = future.result(timeout=timeout if timeout is not None else self.timeout_s)
            self.total_ms += (time.time() - t0) * 1000
            return (text or "").strip() or None
        except FutureTimeout:
            self.timeouts += 1
            log.warning("复核超时（%.1fs），回退到流式结果", self.timeout_s)
            return None
        except Exception as exc:
            self.errors += 1
            log.warning("复核失败：%s", exc)
            return None
        finally:
            with self._lock:
                # 超时的 future 仍在运行，等它结束后再释放 _busy
                if future.done():
                    self._busy = False
                else:
                    future.add_done_callback(lambda _f: self._release())

    def _release(self) -> None:
        with self._lock:
            self._busy = False

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "timeouts": self.timeouts,
            "skipped": self.skipped,
            "errors": self.errors,
            "avg_ms": round(self.total_ms / self.calls, 1) if self.calls else 0.0,
            "engine": getattr(self.engine, "name", "unknown"),
            "enabled": self.enabled,
        }
