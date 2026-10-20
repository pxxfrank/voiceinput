"""临时 UI 演示：独立打开精修面板，便于截图检查布局。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from voiceinput.config import load_config
from voiceinput.overlay import ReviewWindow
from voiceinput.refinement import Segment


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    window = ReviewWindow(root, load_config(), lambda action, payload: print(action, payload))
    segments = [
        Segment(id="s1", index=1, raw_asr="嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。"),
        Segment(id="s2", index=2, raw_asr="第二部分讲 harness 和 session 的关系，可能下周完成。"),
    ]
    for seg in segments:
        seg.reviewed_asr = seg.raw_asr
        seg.normalized = seg.raw_asr
        seg.refined = seg.raw_asr
        seg.duration = 3.2
    window.show(segments, model_status="LLM 已加载 · Qwen3.5-2B", status="可编辑、重新识别或重新精修")
    root.update_idletasks()
    if window.win is not None:
        import ctypes

        hwnd = int(window.win.winfo_id())
        user32 = ctypes.windll.user32
        for _ in range(8):
            parent = user32.GetParent(hwnd)
            if not parent:
                break
            hwnd = parent
        from pathlib import Path

        Path("tests/review_hwnd.txt").write_text(str(hwnd), encoding="ascii")
    root.after(8000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
