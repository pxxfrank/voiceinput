from __future__ import annotations

from voiceinput.asr_merge import merge_stream_review


def test_review_preferred_when_similar():
    result = merge_stream_review("今天讨论 agent memory", "今天讨论 Agent Memory。")
    assert result.source == "review"
    assert result.text.endswith("。")


def test_streaming_kept_when_review_loses_number():
    result = merge_stream_review("下周完成 3 个功能", "下周完成几个功能")
    assert result.source == "streaming"
    assert result.conflict


def test_empty_review_uses_streaming():
    result = merge_stream_review("测试文本", None)
    assert result.text == "测试文本"
    assert result.source == "streaming"


def test_empty_stream_uses_review():
    result = merge_stream_review("", "复核文本")
    assert result.source == "review"
    assert result.text == "复核文本"


def test_low_similarity_conflict():
    result = merge_stream_review("这是完全不同的内容", "另一个毫不相关的句子")
    assert result.source == "streaming"
    assert result.conflict


def test_protected_term_missing_in_review():
    result = merge_stream_review("我用 Agent 框架", "我用代理框架")
    assert result.source == "streaming"
    assert result.conflict


def test_english_word_disagreement_keeps_streaming():
    result = merge_stream_review(
        "第二种叫 always always 什么意思",
        "第二种叫 OSOS 什么意思",
    )
    assert result.source == "streaming"
    assert result.conflict
    assert "always" in result.text
