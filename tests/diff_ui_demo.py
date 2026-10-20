"""临时 UI 演示：独立打开差异对照面板，便于截图检查布局。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from voiceinput.config import load_config
from voiceinput.overlay import DiffWindow
from voiceinput.refinement import Segment


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    window = DiffWindow(root, load_config(), lambda action, payload: print(action, payload))
    seg = Segment(id="s1", index=1, raw_asr="嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。")
    seg.reviewed_asr = seg.raw_asr
    seg.normalized = "嗯那个我们今天呢主要是讨论一下 Agent Memory 的设计方案。"
    seg.refined = "今天主要讨论 Agent Memory 的设计方案。"
    seg.edits = [
        {"source": "嗯那个", "replacement": "", "reason": "删除口头禅"},
        {"source": "我们", "replacement": "", "reason": "精简主语"},
    ]
    segment = seg
    window.show(segment)
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
        (Path(__file__).parent / "diff_hwnd.txt").write_text(str(hwnd), encoding="ascii")
    root.after(8000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
