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
    from voiceinput.refinement import Segment

    commands = []
    root = tk.Tk()
    root.withdraw()
    try:
        window = ReviewWindow(root, load_config(), lambda action, payload: commands.append(action))
        segment = Segment(id="s1", index=1, raw_asr="测试文本")
        segment.reviewed_asr = "测试文本"
        segment.normalized = "测试文本"
        segment.refined = "测试文本"
        window.show([segment])
        root.update()
        assert window.win is not None
        # 编辑框内容会写入 user_edited，插入时以此为准
        window.editor.delete("1.0", "end")
        window.editor.insert("1.0", "用户修改")
        window._on_edit()
        assert segment.user_edited == "用户修改"
        window.replace_selection("x")  # 无选中时安全无操作
    finally:
        root.destroy()
