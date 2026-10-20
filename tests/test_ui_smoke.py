from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("VOICEINPUT_UI_TESTS") != "1", reason="需要交互式桌面；设置 VOICEINPUT_UI_TESTS=1 运行"
)


def test_overlay_buttons_and_state():
    import tkinter as tk

    from voiceinput.config import load_config
    from voiceinput.overlay import OverlayWindow

    commands = []
    root = tk.Tk()
    root.withdraw()
    try:
        overlay = OverlayWindow(root, load_config(), lambda action, payload: commands.append(action), lambda x, y: None)
        overlay.show("recording")
        overlay.set_state("recording", status="录音中", hint="按住 F9")
        root.update()
        assert overlay._buttons["stop"].winfo_ismapped()
        assert overlay._buttons["cancel"].winfo_ismapped()
        assert overlay._buttons["refine"].winfo_ismapped()
        overlay._buttons["cancel"].invoke()
        root.update()
        assert commands == ["cancel"]
        overlay.set_state("target_changed", status="目标变化")
        root.update()
        assert overlay._buttons["retry"].winfo_ismapped()
    finally:
        root.destroy()


def test_review_window_buttons_and_edit():
    import tkinter as tk

    from voiceinput.config import load_config
    from voiceinput.overlay import ReviewWindow

    commands = []
    root = tk.Tk()
    root.withdraw()
    try:
        window = ReviewWindow(root, load_config(), lambda action, payload: commands.append(action))
        window.show("合并后的完整文本", "原始识别文本")
        root.update()
        assert window.win is not None
        assert window.get_text() == "合并后的完整文本"
        window.editor.delete("1.0", "end")
        window.editor.insert("1.0", "用户修改")
        window._on_edit()
        assert window.get_text() == "用户修改"
        window.update_texts("片段更新", "原始识别文本")
        assert window.get_text() == "用户修改"
        window.update_texts("强制更新", "原始识别文本", force=True)
        assert window.get_text() == "强制更新"
        window._restore_original()
        assert window.get_text() == "原始识别文本"
        window._open_compare()
        root.update()
        assert window.compare is not None
        assert window.compare.win is not None
        window.replace_selection("x")  # 无选中时安全无操作
    finally:
        root.destroy()


def test_diff_window_renders_edits():
    import tkinter as tk

    from voiceinput.config import load_config
    from voiceinput.overlay import DiffWindow
    from voiceinput.refinement import Segment

    commands = []
    root = tk.Tk()
    root.withdraw()
    try:
        window = DiffWindow(root, load_config(), lambda action, payload: commands.append(action))
        segment = Segment(id="s1", index=1, raw_asr="原文 A")
        segment.normalized = "原文 A"
        segment.refined = "原文 X"
        segment.edits = [{"source": "A", "replacement": "X", "reason": "test"}]
        segment.edit_decisions = [True]
        window.show(segment)
        root.update()
        assert len(window.tree.get_children()) == 1
        assert window.left.get("1.0", "end-1c").strip() == "原文 A"
        window.set_all(False)
        root.update()
        assert commands and commands[-1] == "diff_apply"
    finally:
        root.destroy()

