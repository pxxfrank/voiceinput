"""自检：用真实音频验证流式 ASR / 复核 ASR / LLM（不依赖麦克风）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import modelstore
from .audio import TARGET_SR, load_wav, resample_to_16k
from .config import load_config
from .engines import OfflineReviewer
from .streaming import StreamingAsr, StreamingSession


def _sample_wavs() -> list[Path]:
    dirs = [modelstore.find_streaming_dir(), modelstore.find_offline_dir()]
    wavs: list[Path] = []
    for d in dirs:
        if d:
            wavs.extend(sorted((d / "test_wavs").glob("*.wav"))[:2])
    return wavs


def run(wav: str | None = None, *, llm: bool = False, json_out: bool = False) -> int:
    cfg = load_config()
    files = [Path(wav)] if wav else _sample_wavs()
    if not files:
        print("未找到测试音频，请传入 WAV 路径")
        return 2
    results = []
    print("加载流式模型…")
    t0 = time.time()
    streaming = StreamingAsr(cfg)
    print(f"  流式加载 {time.time() - t0:.2f}s：{streaming.model_name}")
    reviewer = None
    try:
        t0 = time.time()
        reviewer = OfflineReviewer(cfg)
        print(f"  复核加载 {time.time() - t0:.2f}s：{reviewer.engine.name}")
    except Exception as exc:
        print(f"  复核不可用：{exc}")

    for path in files:
        data, sr = load_wav(path)
        if sr != TARGET_SR:
            data = resample_to_16k(data, sr)
        print(f"\n=== {path.name} ({len(data) / TARGET_SR:.2f}s) ===")
        t0 = time.time()
        segments: list[str] = []
        events: list[dict] = []

        def on_event(event: dict) -> None:
            events.append(event)
            if event.get("type") == "segment":
                segments.append(event["segment"].text)

        session = StreamingSession(streaming, cfg, on_event)
        session.start()
        session.feed(np.zeros(TARGET_SR // 3, dtype=np.float32))
        for i in range(0, len(data), 1600):
            session.feed(data[i : i + 1600])
        session.feed(np.zeros(TARGET_SR, dtype=np.float32))
        session.stop()
        elapsed = time.time() - t0
        stream_text = " ".join(segments).strip()
        partials = [e for e in events if e.get("type") == "partial"]
        print(f"流式: {stream_text!r}")
        print(
            f"  耗时 {elapsed:.2f}s  RTF={elapsed / max(0.001, len(data) / TARGET_SR):.3f}"
            f" 片段={len(segments)} partial={len(partials)}"
        )
        review_text = ""
        review_time = 0.0
        if reviewer:
            t0 = time.time()
            review_text = reviewer.review(data, timeout=30.0) or ""
            review_time = time.time() - t0
            print(f"复核: {review_text!r}  ({review_time:.2f}s)")
        results.append(
            {
                "wav": str(path),
                "duration": round(len(data) / TARGET_SR, 3),
                "streaming": stream_text,
                "review": review_text,
                "stream_seconds": round(elapsed, 3),
                "review_seconds": round(review_time, 3),
                "segments": len(segments),
            }
        )

    if llm:
        from .llm import LlamaServer, Refiner

        print("\n加载本地 LLM…")
        server = LlamaServer(cfg)
        t0 = time.time()
        server.start()
        print(f"  LLM 加载 {time.time() - t0:.2f}s")
        refiner = Refiner(cfg, server)
        for text in (
            "嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。",
            "这个功能我可能大概下周能做完，但是还不太确定。",
        ):
            t0 = time.time()
            out = refiner.refine(
                segment_id="selftest", source_revision=1, text=text, context=[], level="standard"
            )
            print(f"  精修 {time.time() - t0:.2f}s ok={out.ok} -> {out.text!r} err={out.error}")
        server.stop()
    if reviewer:
        reviewer.close()
    if json_out:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", nargs="?")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run(args.wav, llm=args.llm, json_out=args.json)


if __name__ == "__main__":
    sys.exit(main())
