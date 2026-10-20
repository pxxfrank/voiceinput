from __future__ import annotations

import numpy as np

from voiceinput.vad import EnergyVad, VadConfig

SR = 16000
FRAME = 320


def _frames(kind: str, seconds: float) -> list[np.ndarray]:
    n = int(seconds * SR / FRAME)
    if kind == "silence":
        rng = np.random.default_rng(1)
        return [rng.normal(0, 0.0005, FRAME).astype(np.float32) for _ in range(n)]
    t = np.arange(FRAME) / SR
    tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return [tone.copy() for _ in range(n)]


def test_speech_start_and_end():
    vad = EnergyVad(VadConfig(threshold_db=-45, adaptive=False, endpoint_ms=300))
    events = []
    for frame in _frames("silence", 0.3) + _frames("tone", 0.8) + _frames("silence", 0.5):
        event = vad.process(frame)
        if event:
            events.append(event)
    assert events == ["start", "end"]


def test_short_pause_does_not_end_segment():
    vad = EnergyVad(VadConfig(threshold_db=-45, adaptive=False, endpoint_ms=650))
    events = []
    seq = _frames("silence", 0.2) + _frames("tone", 0.6) + _frames("silence", 0.3) + _frames("tone", 0.6) + _frames("silence", 0.8)
    for frame in seq:
        event = vad.process(frame)
        if event:
            events.append(event)
    assert events == ["start", "end"]


def test_adaptive_noise_floor():
    vad = EnergyVad(VadConfig(threshold_db=-50, adaptive=True, endpoint_ms=300))
    # 先喂较高噪声底，阈值应随之上移，避免持续误触发
    for frame in _frames("silence", 3.0):
        assert vad.process(frame) is None
    assert vad.state.noise_db > -70


def test_no_speech_no_events():
    vad = EnergyVad(VadConfig(threshold_db=-45, adaptive=False))
    for frame in _frames("silence", 1.0):
        assert vad.process(frame) is None
