"""片段版本管理与精修流水线 / 调度器。

- 每个片段保留 RawAsrText / ReviewedAsrText / NormalizedText / RefinedText / UserEditedText
- 用户手动修改优先，异步结果不得覆盖
- 精修任务带版本号，过期结果直接丢弃
- LLM 失败/超时回退到确定性整理结果
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .guard import GuardResult, check_refinement
from .llm import LlamaServer, Refiner
from .normalizer import split_sentences
from .terminology import TerminologyManager

log = logging.getLogger("voiceinput.refine")


@dataclass
class Segment:
    id: str
    index: int
    raw_asr: str
    duration: float = 0.0
    audio: np.ndarray | None = None
    reviewed_asr: str = ""
    normalized: str = ""
    refined: str = ""
    user_edited: str = ""
    revision: int = 1
    commit_status: str = "pending"  # pending | committed | failed | kept | cancelled
    merge_note: str = ""
    requires_review: bool = False
    guard: dict[str, Any] = field(default_factory=dict)
    edits: list[dict[str, Any]] = field(default_factory=list)
    edit_decisions: list[bool] = field(default_factory=list)
    error: str = ""
    refine_source: str = ""
    asr_ms: float = 0.0
    review_ms: float = 0.0
    refine_ms: float = 0.0

    @property
    def original_text(self) -> str:
        return (self.reviewed_asr or self.raw_asr).strip()

    @property
    def faithful_text(self) -> str:
        return (self.normalized or self.reviewed_asr or self.raw_asr).strip()

    @property
    def display_text(self) -> str:
        return (self.user_edited or self.refined or self.faithful_text).strip()

    @property
    def is_edited(self) -> bool:
        return bool(self.user_edited.strip())

    def bump(self) -> int:
        self.revision += 1
        return self.revision


@dataclass
class RefineOutcome:
    segment: Segment
    applied: bool
    stale: bool = False


class RefinementPipeline:
    def __init__(
        self,
        cfg: dict[str, Any],
        terminology: TerminologyManager,
        server: LlamaServer,
        refiner: Refiner,
    ) -> None:
        self.cfg = cfg
        self.terminology = terminology
        self.server = server
        self.refiner = refiner
        self.enabled = bool((cfg.get("refine") or {}).get("enabled", True))
        self.default_level = str((cfg.get("refine") or {}).get("level", "standard"))

    def normalize(self, segment: Segment) -> Segment:
        base = segment.original_text
        segment.normalized = self.terminology.apply(base) if base else ""
        return segment

    def refine(
        self,
        segment: Segment,
        *,
        context: list[str] | None = None,
        level: str | None = None,
        timeout: float | None = None,
        expected_revision: int | None = None,
        allow_llm: bool = True,
    ) -> RefineOutcome:
        expected = segment.revision if expected_revision is None else expected_revision
        level = level or self.default_level
        if not segment.normalized:
            self.normalize(segment)
        base = segment.faithful_text

        if not allow_llm or level == "faithful" or not self.enabled:
            if segment.revision == expected:
                segment.refined = base
                segment.refine_source = "faithful"
                segment.requires_review = False
            return RefineOutcome(segment, applied=True, stale=segment.revision != expected)

        result = self.refiner.refine(
            segment_id=segment.id,
            source_revision=expected,
            text=base,
            context=context,
            level=level,
            protected_terms=self.terminology.protected,
            timeout=timeout,
        )
        if segment.revision != expected:
            log.info("精修结果过期，丢弃：%s", segment.id)
            return RefineOutcome(segment, applied=False, stale=True)

        if not result.ok:
            segment.refined = base
            segment.refine_source = "fallback"
            segment.error = result.error
            segment.requires_review = False
            segment.refine_ms = result.latency_ms
            segment.edits = []
            segment.edit_decisions = []
            return RefineOutcome(segment, applied=False)

        guard: GuardResult = check_refinement(
            base,
            result.text,
            result.edits,
            protected_terms=self.terminology.protected,
            level=level,
        )
        segment.guard = guard.to_dict()
        segment.edits = [e for e in (result.edits or []) if isinstance(e, dict)]
        segment.edit_decisions = [True] * len(segment.edits)
        segment.refine_ms = result.latency_ms
        if not guard.ok:
            segment.refined = base
            segment.refine_source = "fallback"
            segment.requires_review = True
            segment.error = "; ".join(guard.hard_errors)[:300]
            segment.edits = []
            segment.edit_decisions = []
            return RefineOutcome(segment, applied=False)

        segment.refined = result.text
        segment.refine_source = "llm"
        segment.requires_review = bool(result.requires_review or guard.requires_review)
        return RefineOutcome(segment, applied=True)

    def apply_user_edit(self, segment: Segment, text: str) -> None:
        segment.user_edited = (text or "").strip()
        segment.requires_review = False
        segment.bump()


def apply_edit_decisions(segment: Segment, decisions: list[bool]) -> Segment:
    """按逐条接受/拒绝结果重建文本。

    全部接受时保留 LLM 的 refined 文本；有拒绝时从规范化原文出发只应用接受的
    edits，避免把被拒绝的修改留在结果里。
    """
    if not segment.edits:
        segment.edit_decisions = []
        return segment
    decisions = [bool(x) for x in decisions[: len(segment.edits)]]
    if len(decisions) < len(segment.edits):
        decisions.extend([True] * (len(segment.edits) - len(decisions)))
    segment.edit_decisions = decisions
    if all(decisions):
        segment.user_edited = ""
        segment.requires_review = False
        segment.bump()
        return segment

    text = segment.normalized or segment.faithful_text
    for edit, accepted in zip(segment.edits, decisions):
        if not accepted:
            continue
        source = str(edit.get("source", "") or "")
        replacement = str(edit.get("replacement", "") or "")
        if source and source in text:
            text = text.replace(source, replacement, 1)
    segment.user_edited = text.strip()
    segment.requires_review = False
    segment.bump()
    return segment


def diff_ops(original: str, revised: str) -> list[tuple[str, str, str]]:
    """字符级 diff，供精修面板渲染：[(equal/delete/insert/replace, left, right)]。"""
    import difflib

    matcher = difflib.SequenceMatcher(None, original or "", revised or "", autojunk=False)
    result: list[tuple[str, str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        result.append((tag, (original or "")[i1:i2], (revised or "")[j1:j2]))
    return result


def compose_text(segments: list[Segment], *, original: bool = False) -> str:
    """把片段拼成最终文本，避免重复标点/空格。original=True 用识别原文。"""
    parts: list[str] = []
    for seg in segments:
        text = seg.original_text if original else seg.display_text
        if not text:
            continue
        if not parts:
            parts.append(text)
            continue
        prev = parts[-1]
        if prev and prev[-1] in "。！？!?；;…" and text[0] in "。！？!?；;，,":
            text = text[1:].lstrip()
        if not text:
            continue
        if prev and prev[-1].isascii() and prev[-1].isalnum() and text[0].isascii() and text[0].isalnum():
            parts.append(" " + text)
        else:
            parts.append(text)
    return "".join(parts).strip()


def build_context(segments: list[Segment], max_sentences: int = 3) -> list[str]:
    sentences: list[str] = []
    for seg in segments:
        for sentence in split_sentences(seg.display_text):
            if sentence:
                sentences.append(sentence)
    return sentences[-max_sentences:] if max_sentences > 0 else []


class RefinementScheduler:
    """单 worker、最新优先、带版本校验的精修调度器。"""

    def __init__(self, pipeline: RefinementPipeline, max_queue: int = 8) -> None:
        self.pipeline = pipeline
        self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_queue)
        self._lock = threading.Lock()
        self._seq = itertools.count()
        self._generation: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="refine-worker", daemon=True)
        self._thread.start()
        self.dropped = 0
        self.completed = 0

    def submit(
        self,
        segment: Segment,
        *,
        context: list[str],
        level: str | None = None,
        timeout: float | None = None,
        callback: Callable[[RefineOutcome], None] | None = None,
        priority: int = 5,
    ) -> int:
        with self._lock:
            generation = self._generation.get(segment.id, 0) + 1
            self._generation[segment.id] = generation
            expected = segment.revision
        item = (priority, next(self._seq), segment, context, level, timeout, expected, generation, callback)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # 丢掉最旧的低优先级任务
            try:
                self._queue.get_nowait()
                self.dropped += 1
                self._queue.put_nowait(item)
            except Exception:
                self.dropped += 1
        return generation

    def cancel(self, segment_id: str) -> None:
        with self._lock:
            self._generation[segment_id] = self._generation.get(segment_id, 0) + 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            priority, _seq, segment, context, level, timeout, expected, generation, callback = item
            with self._lock:
                if self._generation.get(segment.id, 0) != generation:
                    log.info("精修任务已过期：%s", segment.id)
                    continue
            try:
                outcome = self.pipeline.refine(
                    segment,
                    context=context,
                    level=level,
                    timeout=timeout,
                    expected_revision=expected,
                )
                self.completed += 1
                if callback:
                    callback(outcome)
            except Exception as exc:  # pragma: no cover - 防御
                log.exception("精修任务失败：%s", exc)
                segment.error = str(exc)
                if callback:
                    callback(RefineOutcome(segment, applied=False))

    def pending(self) -> int:
        return self._queue.qsize()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
