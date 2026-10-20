from __future__ import annotations

from voiceinput.refinement import Segment, apply_edit_decisions, diff_ops


def segment(refined="这是精修后的文本", edits=None):
    seg = Segment(id="s", index=1, raw_asr="这是原文")
    seg.normalized = "这是原文"
    seg.refined = refined
    seg.edits = edits or []
    seg.edit_decisions = [True] * len(seg.edits)
    return seg


def test_apply_all_accept_keeps_refined():
    seg = segment("这是精修后的文本", [{"source": "这是原文", "replacement": "这是精修后的文本", "reason": "x"}])
    apply_edit_decisions(seg, [True])
    assert seg.refined == "这是精修后的文本"
    assert seg.user_edited == ""


def test_apply_reject_reverts_to_original():
    seg = segment("这是精修后的文本", [{"source": "这是原文", "replacement": "这是精修后的文本", "reason": "x"}])
    apply_edit_decisions(seg, [False])
    assert seg.user_edited == "这是原文"


def test_apply_partial_edits():
    seg = segment(
        "A B C",
        [
            {"source": "A", "replacement": "X", "reason": "x"},
            {"source": "B", "replacement": "Y", "reason": "y"},
        ],
    )
    seg.normalized = "A B C"
    apply_edit_decisions(seg, [True, False])
    assert seg.user_edited == "X B C"


def test_diff_ops_cover_text():
    ops = diff_ops("abc", "axc")
    joined_left = "".join(left for _tag, left, _right in ops)
    joined_right = "".join(right for _tag, _left, right in ops)
    assert joined_left == "abc"
    assert joined_right == "axc"
    assert any(tag == "replace" for tag, _l, _r in ops)


def test_diff_empty():
    ops = diff_ops("", "abc")
    assert "".join(r for _t, _l, r in ops) == "abc"
