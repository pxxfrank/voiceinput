"""可重复的性能测试：真实模型、真实 WAV、真实 llama.cpp。

输出 docs/perf-results.json，并打印 P50/P95 等数据。运行时间约 2-4 分钟。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voiceinput import modelstore  # noqa: E402
from voiceinput.asr_merge import merge_stream_review  # noqa: E402
from voiceinput.audio import TARGET_SR, load_wav, resample_to_16k  # noqa: E402
from voiceinput.config import load_config  # noqa: E402
from voiceinput.engines import OfflineReviewer  # noqa: E402
from voiceinput.llm import LlamaServer, Refiner, _http_json, process_memory_mb  # noqa: E402
from voiceinput.streaming import StreamingAsr, StreamingSession  # noqa: E402


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
    return values[k]


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": 0, "p95": 0, "min": 0, "max": 0, "avg": 0}
    return {
        "n": len(values),
        "p50": round(pct(values, 50), 2),
        "p95": round(pct(values, 95), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(statistics.mean(values), 2),
    }


def _wavs() -> list[Path]:
    dirs = [modelstore.find_streaming_dir(), modelstore.find_offline_dir()]
    result: list[Path] = []
    for d in dirs:
        if d and (d / "test_wavs").exists():
            result.extend(sorted((d / "test_wavs").glob("*.wav")))
    return result


def measure_wav(asr: StreamingAsr, reviewer: OfflineReviewer | None, path: Path) -> dict:
    data, sr = load_wav(path)
    if sr != TARGET_SR:
        data = resample_to_16k(data, sr)
    events: list[dict] = []
    t0 = time.time()
    cpu0 = time.process_time()
    session = StreamingSession(asr, load_config(), lambda e: events.append({**e, "t": time.time() - t0}))
    session.start()
    session.feed(np.zeros(TARGET_SR // 3, dtype=np.float32))
    chunk = 1600
    intervals = []
    last_partial = None
    for i in range(0, len(data), chunk):
        session.feed(data[i : i + chunk])
        time.sleep(0.1)
        for e in events:
            if e.get("type") == "partial" and last_partial != e["text"]:
                last_partial = e["text"]
                intervals.append(e["t"])
    session.feed(np.zeros(int(TARGET_SR * 1.2), dtype=np.float32))
    time.sleep(0.4)
    session.stop()
    elapsed = time.time() - t0
    cpu_seconds = time.process_time() - cpu0
    cpu_percent = cpu_seconds / max(0.01, elapsed) * 100
    partials = [e for e in events if e.get("type") == "partial"]
    segments = [e for e in events if e.get("type") == "segment"]
    text = " ".join(s["segment"].text for s in segments).strip()
    first_partial = session.first_partial_ms
    update_intervals = [
        (partials[i]["t"] - partials[i - 1]["t"]) * 1000 for i in range(1, len(partials))
    ]
    review_ms = 0.0
    review_text = ""
    if reviewer:
        t1 = time.time()
        review_text = reviewer.review(data, timeout=30.0) or ""
        review_ms = (time.time() - t1) * 1000
    merge = merge_stream_review(text, review_text)
    decode_s = session.decode_seconds
    return {
        "wav": path.name,
        "duration_s": round(len(data) / TARGET_SR, 2),
        "first_partial_ms": round(first_partial, 1) if first_partial is not None else None,
        "partial_updates": len(partials),
        "update_interval_ms": summary(update_intervals),
        "segments": len(segments),
        "decode_s": round(decode_s, 3),
        "wall_s": round(elapsed, 2),
        "cpu_percent": round(cpu_percent, 1),
        "rtf": round(decode_s / max(0.01, len(data) / TARGET_SR), 3),
        "stream_text": text,
        "review_text": review_text,
        "review_ms": round(review_ms, 1),
        "review_rtf": round(review_ms / 1000.0 / max(0.01, len(data) / TARGET_SR), 3),
        "merge_source": merge.source,
    }


def measure_llm(cfg: dict, texts: list[str]) -> dict:
    server = LlamaServer(cfg)
    t0 = time.time()
    server.start()
    load_ms = (time.time() - t0) * 1000
    server.chat([{"role": "user", "content": "只回复 OK"}], timeout=30, max_tokens=4, temperature=0)
    refiner = Refiner(cfg, server)
    results = []
    for text in texts:
        t0 = time.time()
        out = refiner.refine(segment_id="perf", source_revision=1, text=text, context=[], level="standard")
        latency = (time.time() - t0) * 1000
        results.append({"text": text, "latency_ms": round(latency, 1), "ok": out.ok, "output": out.text})
    # 首 token 延迟（流式请求）
    first_token_ms = None
    try:
        import urllib.request

        payload = {
            "messages": [{"role": "system", "content": Refiner.SYSTEM}, {"role": "user", "content": "口述文字：我们下周把接口和测试补上。"}],
            "temperature": 0.2,
            "max_tokens": 128,
            "stream": True,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{server._port}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        t0 = time.time()
        with opener.open(req, timeout=60) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if line.startswith("data:") and '"content"' in line:
                    first_token_ms = (time.time() - t0) * 1000
                    break
    except Exception as exc:
        print("首 token 测量失败：", exc)
    memory = process_memory_mb(server._proc.pid) if server._proc else 0
    status = server.status()
    server.stop()
    return {
        "load_ms": round(load_ms, 1),
        "first_token_ms": round(first_token_ms, 1) if first_token_ms else None,
        "refines": results,
        "latency": summary([r["latency_ms"] for r in results if r["ok"]]),
        "memory_mb": memory,
        "model": status.get("model"),
        "threads": server.threads,
    }


def run(quick: bool = False) -> dict:
    cfg = load_config()
    if quick:
        cfg["refine"]["threads"] = min(8, cfg["refine"].get("threads") or 8)
    wavs = _wavs()
    if quick:
        wavs = wavs[:2]
    report: dict = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "os": str(sys.getwindowsversion()) if hasattr(sys, "getwindowsversion") else os.name,
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "stream_model": str(modelstore.find_streaming_dir(cfg)),
        "offline_model": str(modelstore.find_offline_dir(cfg)),
        "llm_model": str(modelstore.find_llm_model(cfg)),
        "basic_memory_mb": None,
        "smart_memory_mb": None,
        "wavs": [],
        "llm": None,
    }
    baseline = process_memory_mb(os.getpid())
    t0 = time.time()
    asr = StreamingAsr(cfg)
    asr_load_ms = (time.time() - t0) * 1000
    t0 = time.time()
    reviewer = OfflineReviewer(cfg)
    review_load_ms = (time.time() - t0) * 1000
    basic_memory = process_memory_mb(os.getpid())
    report.update(
        {
            "asr_load_ms": round(asr_load_ms, 1),
            "review_load_ms": round(review_load_ms, 1),
            "baseline_memory_mb": baseline,
            "basic_memory_mb": basic_memory,
        }
    )
    for wav in wavs:
        result = measure_wav(asr, reviewer, wav)
        report["wavs"].append(result)
        print(
            f"{wav.name}: first={result['first_partial_ms']}ms rtf={result['rtf']} "
            f"review={result['review_ms']}ms segments={result['segments']}"
        )
    reviewer.close()
    report["llm"] = measure_llm(
        cfg,
        [
            "嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。",
            "这个功能我可能大概下周能做完，但是还不太确定。",
            "我们先把需求梳理一下然后设计接口再写测试最后上线大概需要三天时间。",
        ],
    )
    report["smart_memory_mb"] = report["llm"]["memory_mb"]
    if report["wavs"]:
        firsts = [w["first_partial_ms"] for w in report["wavs"] if w["first_partial_ms"]]
        rtfs = [w["rtf"] for w in report["wavs"]]
        reviews = [w["review_ms"] for w in report["wavs"] if w["review_ms"]]
        report["aggregate"] = {
            "first_partial_ms": summary(firsts),
            "rtf": summary(rtfs),
            "review_ms": summary(reviews),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--out", default="docs/perf-results.json")
    args = parser.parse_args()
    report = run(args.quick)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.get("aggregate", {}), ensure_ascii=False, indent=2))
    print(f"已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
