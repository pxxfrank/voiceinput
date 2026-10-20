"""LLM 输出与精修结果的语义保护规则。

规则只能覆盖部分风险；无法可靠判定的修改标记为 requires_review，交由用户确认。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .normalizer import ascii_words, emails_in, numbers_in, urls_in

NEGATIONS = ("不", "没", "无", "未", "别", "非", "否", "莫", "勿", "从未", "并不")
UNCERTAINTY = ("可能", "似乎", "大概", "也许", "或许", "应该", "大约", "差不多", "未必", "不一定")


@dataclass
class GuardResult:
    ok: bool
    requires_review: bool = False
    hard_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "requires_review": self.requires_review,
            "hard_errors": list(self.hard_errors),
            "warnings": list(self.warnings),
        }


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(text.count(term) for term in terms)


def check_refinement(
    original: str,
    revised: str,
    edits: list[dict[str, Any]] | None,
    *,
    protected_terms: tuple[str, ...] | list[str] = (),
    level: str = "standard",
    max_length_ratio: float = 2.0,
    min_length_ratio: float = 0.45,
) -> GuardResult:
    errors: list[str] = []
    warnings: list[str] = []
    original = (original or "").strip()
    revised = (revised or "").strip()

    if not revised:
        return GuardResult(False, True, ["精修结果为空"], [])

    # 数字：不得丢失、不得新增
    orig_numbers = numbers_in(original)
    new_numbers = numbers_in(revised)
    for num in orig_numbers:
        if num not in revised:
            errors.append(f"数字被改动或丢失：{num}")
    for num in new_numbers:
        if num not in original:
            errors.append(f"出现原文没有的数字：{num}")

    # URL / 邮箱必须原样保留
    for url in urls_in(original):
        if url not in revised:
            errors.append(f"链接被改动：{url}")
    for email in emails_in(original):
        if email not in revised:
            errors.append(f"邮箱被改动：{email}")

    # 不得凭空新增英文词/缩写（防止把 Always 改成 OSOS 这类事实性篡改）
    original_words = {w.casefold() for w in ascii_words(original)}
    for word in ascii_words(revised):
        if word.casefold() not in original_words:
            errors.append(f"出现原文没有的英文词：{word}")

    # 受保护术语必须原样出现
    for term in protected_terms:
        if term and term in original and term.lower() not in revised.lower():
            errors.append(f"受保护术语被改动：{term}")

    # 否定词与不确定性表达：数量减少则要求复核
    neg_before, neg_after = _count_terms(original, NEGATIONS), _count_terms(revised, NEGATIONS)
    if neg_after < neg_before:
        warnings.append("否定词数量减少，语义可能改变")
    unc_before, unc_after = _count_terms(original, UNCERTAINTY), _count_terms(revised, UNCERTAINTY)
    if unc_after < unc_before:
        warnings.append("不确定性表达减少")

    # 长度异常
    if original:
        ratio = len(revised) / max(1, len(original))
        if ratio > max_length_ratio:
            errors.append(f"精修结果异常变长（{ratio:.1f}x）")
        if ratio < min_length_ratio:
            errors.append(f"精修结果异常变短（{ratio:.1f}x）")

    # edits 结构
    for i, edit in enumerate(edits or []):
        if not isinstance(edit, dict):
            warnings.append(f"第 {i + 1} 条修改记录格式不正确")
            continue
        source = str(edit.get("source", "")).strip()
        replacement = str(edit.get("replacement", ""))
        reason = str(edit.get("reason", "")).strip()
        if source and source not in original:
            warnings.append(f"修改记录中的原文不存在：{source[:20]}")
        if not reason:
            warnings.append("修改记录缺少原因")
        if source and replacement and replacement not in revised and replacement not in original:
            warnings.append(f"修改记录与结果不一致：{source[:20]}")

    # 深度整理允许分段/书面化，但仍不放宽数字与术语
    if level == "deep":
        if re.search(r"\n{3,}", revised):
            warnings.append("深度整理产生过多空行")

    ok = not errors
    return GuardResult(
        ok=ok,
        requires_review=bool(warnings) or not ok,
        hard_errors=errors,
        warnings=warnings,
    )
