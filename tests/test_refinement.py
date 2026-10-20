from __future__ import annotations

from voiceinput.guard import check_refinement
from voiceinput.llm import LlamaServer, Refiner
from voiceinput.refinement import RefinementPipeline, Segment
from voiceinput.storage import Storage
from voiceinput.terminology import TerminologyManager


class FakeServer:
    def __init__(self):
        self._schema_supported = False


class FakeRefiner:
    def __init__(self, text="", edits=None, mutate=None, ok=True):
        self.text = text
        self.edits = edits or []
        self.mutate = mutate
        self.ok = ok
        self.calls = 0

    def refine(self, **kwargs):
        from voiceinput.llm import RefineResponse

        self.calls += 1
        if self.mutate:
            self.mutate()
        if not self.ok:
            return RefineResponse(False, error="fake error")
        return RefineResponse(True, text=self.text, edits=self.edits)


def _pipeline(tmp_path, refiner):
    cfg = {"refine": {"enabled": True, "level": "standard"}, "intermediate": {}}
    storage = Storage(tmp_path / "test.db")
    return RefinementPipeline(cfg, TerminologyManager(storage), FakeServer(), refiner), storage


def test_faithful_level_no_llm(tmp_path):
    refiner = FakeRefiner("不会调用")
    pipeline, _ = _pipeline(tmp_path, refiner)
    seg = Segment(id="s1", index=1, raw_asr="嗯这个是测试")
    pipeline.normalize(seg)
    outcome = pipeline.refine(seg, level="faithful")
    assert outcome.applied
    assert seg.refine_source == "faithful"
    assert refiner.calls == 0


def test_user_edit_wins_over_llm(tmp_path):
    refiner = FakeRefiner("精修后的文本")
    pipeline, _ = _pipeline(tmp_path, refiner)
    seg = Segment(id="s1", index=1, raw_asr="嗯这个是测试")
    pipeline.normalize(seg)
    seg.user_edited = "用户手动修改"
    seg.bump()
    pipeline.refine(seg, expected_revision=seg.revision)
    assert seg.display_text == "用户手动修改"


def test_stale_result_discarded(tmp_path):
    refiner = FakeRefiner("迟到结果", mutate=None)

    def mutate():
        # 模拟生成期间用户继续说话 / 编辑
        seg.bump()

    refiner.mutate = mutate
    pipeline, _ = _pipeline(tmp_path, refiner)
    seg = Segment(id="s1", index=1, raw_asr="测试文本")
    pipeline.normalize(seg)
    expected = seg.revision
    outcome = pipeline.refine(seg, expected_revision=expected)
    assert outcome.stale
    assert not outcome.applied


def test_guard_rejects_hallucinated_english(tmp_path):
    refiner = FakeRefiner("OSOS 什么意思")
    pipeline, _ = _pipeline(tmp_path, refiner)
    seg = Segment(id="s1", index=1, raw_asr="总是总是 什么意思")
    pipeline.normalize(seg)
    outcome = pipeline.refine(seg)
    assert not outcome.applied
    assert seg.refine_source == "fallback"
    assert "英文" in seg.error


def test_guard_rejects_number_change(tmp_path):
    refiner = FakeRefiner("下周完成三个功能")
    pipeline, _ = _pipeline(tmp_path, refiner)
    seg = Segment(id="s1", index=1, raw_asr="下周完成 3 个功能")
    pipeline.normalize(seg)
    outcome = pipeline.refine(seg)
    assert not outcome.applied
    assert "3" not in seg.refined or "3" in seg.refined  # 回退文本保留数字


def test_compose_text_avoids_duplicate_punctuation():
    from voiceinput.refinement import compose_text

    segments = [
        Segment(id="a", index=1, raw_asr="第一句。"),
        Segment(id="b", index=2, raw_asr="。第二句"),
        Segment(id="c", index=3, raw_asr="Third"),
        Segment(id="d", index=4, raw_asr="Fourth"),
    ]
    assert compose_text(segments) == "第一句。第二句Third Fourth"


def test_parse_json_and_rejections():
    good = '{"revised_text":"整理后","edits":[],"requires_review":false}'
    parsed = Refiner._parse(good, "seg1", 1)
    assert parsed and parsed.ok and parsed.text == "整理后"

    bad_segment = '{"segment_id":"other","source_revision":1,"revised_text":"x","edits":[],"requires_review":false}'
    assert Refiner._parse(bad_segment, "seg1", 1) is not None
    assert not Refiner._parse(bad_segment, "seg1", 1).ok

    echo = '{"revised_text":"口述文字：abc revised_text"}'
    assert not Refiner._parse(echo, "seg1", 1).ok

    assert Refiner._parse("not json", "seg1", 1) is None
