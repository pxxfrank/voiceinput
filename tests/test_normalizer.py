from __future__ import annotations

from voiceinput.normalizer import normalize_text, numbers_in


def test_canonical_english_terms():
    text = normalize_text("我们用 agent memory 和 harness 做 session 管理，调用 llm api")
    assert "Agent Memory" in text
    assert "Harness" in text
    assert "Session" in text
    assert "LLM" in text
    assert "API" in text


def test_chinese_english_spacing():
    text = normalize_text("使用Python写代码然后调用API")
    assert "Python" in text
    assert "API" in text
    assert "使用 Python" in text
    assert "调用 API" in text


def test_chinese_punctuation_conversion():
    text = normalize_text("第一点,第二点;第三点?好的!")
    assert "，" in text and "," not in text
    assert "；" in text and ";" not in text
    assert "？" in text and "?" not in text
    assert "！" in text and "!" not in text


def test_terminal_punctuation_added_for_chinese_only():
    assert normalize_text("这是一句话").endswith("。")
    assert normalize_text("hello world") == "hello world"


def test_numbers_preserved():
    text = normalize_text("版本 3.14 在 2026 年 10 月发布，准确率 98.5%")
    assert "3.14" in text
    assert "2026" in text
    assert "98.5%" in text
    assert numbers_in(text) == ["3.14", "2026", "10", "98.5%"]


def test_replacements_applied():
    text = normalize_text("我们讨论未来汽车", replacements={"未来": "蔚来"})
    assert "蔚来" in text
    assert "未来" not in text


def test_protected_term_case_not_changed():
    text = normalize_text("使用 Agent 框架", protected_terms=("Agent",))
    assert "Agent" in text


def test_repeated_punctuation_collapsed():
    text = normalize_text("你好，，，世界。。。")
    assert "，，" not in text
    assert "。。" not in text


def test_empty():
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""
