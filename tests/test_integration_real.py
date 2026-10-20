"""真实模型集成测试（需显式开启，避免每次单元测试都加载 2 GB 模型）。

运行：
    $env:VOICEINPUT_RUN_INTEGRATION="1"; python -m pytest tests/test_integration_real.py -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VOICEINPUT_RUN_INTEGRATION") != "1",
    reason="需要真实模型；设置 VOICEINPUT_RUN_INTEGRATION=1",
)

ROOT = Path(__file__).resolve().parent.parent


def test_streaming_and_review_real_audio():
    from voiceinput.audio import TARGET_SR, load_wav, resample_to_16k
    from voiceinput.config import load_config
    from voiceinput.engines import OfflineReviewer
    from voiceinput.modelstore import find_offline_dir, find_streaming_dir
    from voiceinput.streaming import StreamingAsr, StreamingSession

    cfg = load_config()
    stream_dir = find_streaming_dir(cfg)
    offline_dir = find_offline_dir(cfg)
    assert stream_dir and offline_dir
    wav = sorted((stream_dir / "test_wavs").glob("*.wav"))[0]
    data, sr = load_wav(wav)
    if sr != TARGET_SR:
        data = resample_to_16k(data, sr)

    asr = StreamingAsr(cfg)
    events: list[dict] = []
    session = StreamingSession(asr, cfg, events.append)
    import time
    import numpy as np

    session.start()
    session.feed(np.zeros(TARGET_SR // 3, dtype=np.float32))
    for i in range(0, len(data), 1600):
        session.feed(data[i : i + 1600])
        time.sleep(0.02)
    session.feed(np.zeros(TARGET_SR, dtype=np.float32))
    session.stop()
    text = " ".join(e["segment"].text for e in events if e.get("type") == "segment").strip()
    assert text, "流式识别结果为空"
    assert any("\u4e00" <= ch <= "\u9fff" for ch in text)

    reviewer = OfflineReviewer(cfg)
    reviewed = reviewer.review(data, timeout=30.0) or ""
    reviewer.close()
    assert reviewed, "复核结果为空"


def test_llm_real_refine():
    from voiceinput.config import load_config
    from voiceinput.llm import LlamaServer, Refiner

    cfg = load_config()
    server = LlamaServer(cfg)
    server.start()
    try:
        refiner = Refiner(cfg, server)
        result = refiner.refine(
            segment_id="it",
            source_revision=1,
            text="嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。",
            context=[],
            level="standard",
        )
        assert result.ok, result.error
        assert result.text
        assert "Agent" in result.text or "agent" in result.text
    finally:
        server.stop()
