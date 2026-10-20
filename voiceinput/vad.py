"""语音活动检测（VAD）与语句端点检测。

基于能量的自适应 VAD：区分「有人在说话」与「一句话说完了」。
端点只结束当前语义片段，不结束整个输入会话；短暂停顿不会触发。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class VadConfig:
    threshold_db: float = -45.0
    adaptive: bool = True
    speech_start_ms: int = 100
    endpoint_ms: int = 650
    frame_ms: int = 20


@dataclass
class VadState:
    speech: bool = False
    level_db: float = -100.0
    threshold_db: float = -45.0
    noise_db: float = -60.0
    speech_ms: int = 0
    silence_ms: int = 0


class EnergyVad:
    """逐 20ms 帧处理的能量 VAD。

    返回 ``"start"`` / ``"end"`` / ``None``。端点后自动复位到非语音状态，
    调用方可立即开始下一片段。
    """

    def __init__(self, config: VadConfig | None = None, **kwargs) -> None:
        if config is None:
            config = VadConfig(**kwargs)
        self.config = config
        self.state = VadState(threshold_db=config.threshold_db, noise_db=-60.0)
        self._voiced_run = 0

    def reset(self) -> None:
        self.state.speech = False
        self.state.speech_ms = 0
        self.state.silence_ms = 0
        self.state.level_db = -100.0
        self._voiced_run = 0

    @property
    def threshold(self) -> float:
        if not self.config.adaptive:
            return self.config.threshold_db
        return max(self.config.threshold_db, self.state.noise_db + 8.0)

    def process(self, frame: np.ndarray | list[float]) -> str | None:
        data = np.asarray(frame, dtype=np.float32)
        if data.size == 0:
            return None
        rms = float(np.sqrt(np.mean(np.square(data.astype(np.float64))) + 1e-12))
        db = 20.0 * math.log10(rms + 1e-12)
        self.state.level_db = db
        threshold = self.threshold
        self.state.threshold_db = threshold
        voiced = db > threshold

        if not voiced:
            # 只在非语音段更新噪声底，避免把人声当成噪声
            if not self.state.speech and self.config.adaptive:
                self.state.noise_db = 0.98 * self.state.noise_db + 0.02 * db

        if voiced:
            self._voiced_run += self.config.frame_ms
            self.state.silence_ms = 0
            if not self.state.speech and self._voiced_run >= self.config.speech_start_ms:
                self.state.speech = True
                self.state.speech_ms = 0
                return "start"
        else:
            self._voiced_run = 0
            if self.state.speech:
                self.state.silence_ms += self.config.frame_ms
                if self.state.silence_ms >= self.config.endpoint_ms:
                    self.state.speech = False
                    self.state.silence_ms = 0
                    self._voiced_run = 0
                    return "end"
        if self.state.speech:
            self.state.speech_ms += self.config.frame_ms
        return None


class EndpointTracker:
    """把 VAD 事件转换为会话内片段边界，并限制单段最长时长。"""

    def __init__(self, vad: EnergyVad, max_segment_s: float = 20.0) -> None:
        self.vad = vad
        self.max_segment_s = max_segment_s
        self.segment_ms = 0

    def reset(self) -> None:
        self.vad.reset()
        self.segment_ms = 0

    def process(self, frame: np.ndarray) -> str | None:
        event = self.vad.process(frame)
        self.segment_ms += self.vad.config.frame_ms
        if event == "end":
            return "end"
        if self.vad.state.speech and self.segment_ms >= int(self.max_segment_s * 1000):
            return "force_end"
        return event
