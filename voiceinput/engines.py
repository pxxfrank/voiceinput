"""离线 ASR 引擎封装（基于 sherpa-onnx，可选 faster-whisper）。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np

from .config import PROJECT_ROOT, resolve_model_dir

log = logging.getLogger("voiceinput.asr")


class ASREngine(ABC):
    name = "base"

    @abstractmethod
    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """把单声道 float32 音频转写为文本。"""


# --------------------------------------------------------------------------- #
# 模型文件定位
# --------------------------------------------------------------------------- #
def _find_model_dir(root: Path, *keywords: str) -> Path:
    if not root.exists():
        raise FileNotFoundError(
            f"模型目录不存在：{root}\n请先运行 `python -m voiceinput.download_models` 下载模型。"
        )
    for child in sorted(root.iterdir()):
        if child.is_dir() and all(k in child.name for k in keywords):
            return child
    raise FileNotFoundError(
        f"在 {root} 下未找到名称包含 {keywords} 的模型目录，请先下载模型。"
    )


def _pick_onnx(model_dir: Path) -> Path:
    for name in ("model.int8.onnx", "model.onnx"):
        candidate = model_dir / name
        if candidate.exists():
            return candidate
    onnx_files = sorted(model_dir.glob("*.onnx"))
    if onnx_files:
        return onnx_files[0]
    raise FileNotFoundError(f"在 {model_dir} 下未找到 .onnx 模型文件。")


# --------------------------------------------------------------------------- #
# sherpa-onnx 引擎
# --------------------------------------------------------------------------- #
class SenseVoiceEngine(ASREngine):
    name = "SenseVoice-Small"

    def __init__(self, cfg: dict[str, Any]) -> None:
        import sherpa_onnx

        model_dir = _find_model_dir(resolve_model_dir(cfg), "sense-voice")
        model = _pick_onnx(model_dir)
        tokens = model_dir / "tokens.txt"
        if not tokens.exists():
            raise FileNotFoundError(f"缺少 tokens.txt：{model_dir}")

        sv = cfg.get("sensevoice", {})
        log.info("加载 SenseVoice：%s", model.name)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            num_threads=int(cfg.get("threads", 4)),
            use_itn=bool(sv.get("use_itn", True)),
            language=str(sv.get("language", "auto")),
            debug=False,
        )

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()


class ParaformerEngine(ASREngine):
    name = "Paraformer-zh"

    def __init__(self, cfg: dict[str, Any]) -> None:
        import sherpa_onnx

        model_dir = _find_model_dir(resolve_model_dir(cfg), "paraformer")
        model = _pick_onnx(model_dir)
        tokens = model_dir / "tokens.txt"
        if not tokens.exists():
            raise FileNotFoundError(f"缺少 tokens.txt：{model_dir}")

        log.info("加载 Paraformer：%s", model.name)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(model),
            tokens=str(tokens),
            num_threads=int(cfg.get("threads", 4)),
            debug=False,
        )

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()


class WhisperEngine(ASREngine):
    """可选：基于 faster-whisper（需额外安装 ``faster-whisper``）。"""

    name = "faster-whisper"

    def __init__(self, cfg: dict[str, Any]) -> None:
        from faster_whisper import WhisperModel

        w = cfg.get("whisper", {})
        model_size = str(w.get("model", "large-v3"))
        self.language = w.get("language", "zh") or None
        self.model_name = f"Whisper-{model_size}"
        log.info("加载 faster-whisper %s ...", model_size)
        self.model = WhisperModel(
            model_size,
            device=str(w.get("device", "cpu")),
            compute_type=str(w.get("compute_type", "int8")),
            download_root=str(PROJECT_ROOT / "models" / "whisper"),
        )

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        segments, _info = self.model.transcribe(
            samples.astype(np.float32),
            language=self.language,
            beam_size=5,
            vad_filter=True,
        )
        return "".join(seg.text for seg in segments).strip()


_ENGINES = {
    "sensevoice": SenseVoiceEngine,
    "paraformer": ParaformerEngine,
    "whisper": WhisperEngine,
}


def build_engine(cfg: dict[str, Any]) -> ASREngine:
    key = str(cfg.get("engine", "sensevoice")).lower()
    if key not in _ENGINES:
        raise ValueError(f"未知引擎：{key!r}，可选：{', '.join(_ENGINES)}")
    return _ENGINES[key](cfg)
