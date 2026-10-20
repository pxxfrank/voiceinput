from __future__ import annotations

from voiceinput.guard import check_refinement


def test_numbers_must_be_preserved():
    result = check_refinement("下周完成 3 个功能，预算 2000 元", "下周完成三个功能，预算两千元", [])
    assert not result.ok
    assert any("数字" in e for e in result.hard_errors)


def test_no_new_numbers():
    result = check_refinement("下周完成功能", "下周完成 5 个功能", [])
    assert not result.ok


def test_negation_removed_requires_review():
    result = check_refinement("这个方案不太可行", "这个方案可行", [])
    assert result.ok
    assert result.requires_review
    assert any("否定" in w for w in result.warnings)


def test_uncertainty_removed_requires_review():
    result = check_refinement("他可能会来", "他会来", [])
    assert result.requires_review


def test_hallucinated_english_term_rejected():
    result = check_refinement("总是总是 什么意思", "OSOS 什么意思", [])
    assert not result.ok
    assert any("英文" in e for e in result.hard_errors)


def test_protected_term_preserved():
    result = check_refinement("Agent Memory 的设计", "代理记忆的设计", [], protected_terms=["Agent Memory"])
    assert not result.ok


def test_length_explosion_rejected():
    result = check_refinement("你好", "你好" * 20, [])
    assert not result.ok


def test_minor_punctuation_change_ok():
    result = check_refinement("我们今天讨论这个问题", "我们今天讨论这个问题。", [])
    assert result.ok
    assert not result.requires_review
