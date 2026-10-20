"""E2E 测试目标程序：一个真实的 Win32/Tk 文本输入窗口。

用法：python tests/target_app.py <状态文件> [标题]
状态文件 JSON：{"pid":..., "hwnd":..., "text":"..."}
"""

from __future__ import annotations

import json
import sys
import time
import tkinter as tk
from pathlib import Path

state_path = Path(sys.argv[1])
title = sys.argv[2] if len(sys.argv) > 2 else "VoiceInput E2E Target"


def top_hwnd(root: tk.Tk) -> int:
    import ctypes

    hwnd = int(root.winfo_id())
    user32 = ctypes.windll.user32
    for _ in range(8):
        parent = user32.GetParent(hwnd)
        if not parent:
            break
        hwnd = parent
    return hwnd


def main() -> int:
    root = tk.Tk()
    root.title(title)
    root.geometry("640x360+120+120")
    text = tk.Text(root, undo=True, font=("Microsoft YaHei", 14), wrap="word")
    text.pack(fill="both", expand=True)
    text.focus_set()
    root.attributes("-topmost", True)
    root.lift()
    root.after(200, lambda: (root.focus_force(), text.focus_set()))

    def keep_front() -> None:
        try:
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            text.focus_set()
        except Exception:
            pass
        root.after(400, keep_front)

    root.after(400, keep_front)

    def dump() -> None:
        try:
            content = text.get("1.0", "end-1c")
            state_path.write_text(
                json.dumps(
                    {
                        "pid": root.winfo_id(),
                        "hwnd": top_hwnd(root),
                        "text": content,
                        "ready": True,
                        "ts": time.time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
        root.after(150, dump)

    dump()
    root.after(120000, root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
