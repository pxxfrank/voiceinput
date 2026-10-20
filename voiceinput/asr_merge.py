"""流式结果与离线复核结果的合并。

复核结果不是「更正确」的同义词：只有相似度足够高、且没有丢失数字/受保护术语时
才采用复核文本；冲突时保留流式结果并标记，交由用户确认。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .normalizer import ascii_words, numbers_in, strip_for_compare


@dataclass
class MergeResult:
    text: str
    source: str  # streaming | review
    similarity: float
    conflict: bool = False
    note: str = ""

    @property
    def requires_review(self) -> bool:
        return self.conflict


def similarity(a: str, b: str) -> float:
    sa, sb = strip_for_compare(a), strip_for_compare(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return SequenceMatcher(None, sa, sb).ratio()


def merge_stream_review(
    streaming_text: str,
    review_text: str | None,
    *,
    protected_terms: tuple[str, ...] | list[str] = (),
    min_similarity: float = 0.75,
    conflict_similarity: float = 0.45,
) -> MergeResult:
    stream = (streaming_text or "").strip()
    review = (review_text or "").strip()
    if not review:
        return MergeResult(stream, "streaming", 1.0)
    if not stream:
        return MergeResult(review, "review", 1.0)

    sim = similarity(stream, review)
    if sim < conflict_similarity:
        return MergeResult(
            stream,
            "streaming",
            sim,
            conflict=True,
            note="复核结果与流式结果差异较大，保留流式结果",
        )

    # 数字必须全部保留
    stream_numbers = numbers_in(stream)
    missing_numbers = [n for n in stream_numbers if n not in review]
    if missing_numbers:
        return MergeResult(
            stream,
            "streaming",
            sim,
            conflict=True,
            note=f"复核结果丢失数字：{', '.join(missing_numbers[:3])}",
        )

    # 中英混排时，英文词不一致说明至少一个模型听错；保守保留流式并标记复核
    stream_words = {w.casefold() for w in ascii_words(stream)}
    review_words = {w.casefold() for w in ascii_words(review)}
    if stream_words != review_words:
        return MergeResult(
            stream,
            "streaming",
            sim,
            conflict=True,
            note="复核与流式识别的英文词不一致，保留流式结果",
        )

    # 受保护术语必须保留
    for term in protected_terms:
        if term and term in stream and term not in review:
            return MergeResult(
                stream,
                "streaming",
                sim,
                conflict=True,
                note=f"复核结果丢失受保护术语：{term}",
            )

    if sim < min_similarity:
        return MergeResult(
            stream,
            "streaming",
            sim,
            conflict=True,
            note="复核结果与流式结果存在分歧，保留流式结果",
        )

    # 长度异常（复核过短）视为可疑
    if len(review) < len(stream) * 0.55:
        return MergeResult(
            stream,
            "streaming",
            sim,
            conflict=True,
            note="复核结果明显短于流式结果，保留流式结果",
        )

    return MergeResult(review, "review", sim)
