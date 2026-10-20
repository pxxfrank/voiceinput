from __future__ import annotations

from voiceinput.streaming import StableTextTracker


def test_stable_prefix_grows():
    tracker = StableTextTracker(history=3, min_stable=2)
    tracker.update("今天")
    stable, unstable = tracker.update("今天天气")
    assert stable.startswith("今天")
    assert stable + unstable == "今天天气"


def test_stable_monotonic_on_correction():
    tracker = StableTextTracker(history=2, min_stable=2)
    tracker.update("今天天气很好")
    tracker.update("今天天气很好")
    stable_before = tracker.stable
    tracker.update("今天天气很")  # 结果回退
    assert tracker.stable.startswith(stable_before[:2])
    assert tracker.stable == stable_before


def test_no_half_english_word_stable():
    tracker = StableTextTracker(history=2, min_stable=2)
    tracker.update("hello wor")
    tracker.update("hello world")
    assert not tracker.stable.endswith("wor")
    stable, unstable = tracker.update("hello world")
    assert stable == "hello world"
    assert unstable == ""


def test_flush_sets_full_text():
    tracker = StableTextTracker()
    tracker.update("abc")
    stable, unstable = tracker.flush("abcd")
    assert stable == "abcd"
    assert unstable == ""
