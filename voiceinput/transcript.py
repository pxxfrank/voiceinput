"""字幕窗口：显示本次会话的**全部字幕**（实时 + 历史），窗口可自由缩放。

独立进程，读取与悬浮字幕同一个状态文件 ``hud.state``：
- 历史（已经说过）用一种颜色，实时（正在说）用另一种颜色；
- 窗口大小 / 位置会被记住（``transcript.geom``）；主程序退出后自动关闭。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .config import PROJECT_ROOT
from .hud import _STALE_SECONDS, _read_state

GEOM_FILE = PROJECT_ROOT / "transcript.geom"


def _load_geom():
    try:
        w, h, x, y = json.loads(GEOM_FILE.read_text(encoding="utf-8"))
        return int(w), int(h), int(x), int(y)
    except Exception:
        return None


def _save_geom(w, h, x, y) -> None:
    try:
        GEOM_FILE.write_text(json.dumps([int(w), int(h), int(x), int(y)]), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("voiceinput · 字幕")
    root.configure(bg="#ffffff")
    geom = _load_geom()
    if geom:
        root.geometry(f"{geom[0]}x{geom[1]}+{geom[2]}+{geom[3]}")
    else:
        root.geometry("580x400")

    header = tk.Frame(root, bg="#ffffff")
    header.pack(fill="x", padx=14, pady=(10, 4))
    status_lbl = tk.Label(header, text="", bg="#ffffff", fg="#c96442", font=("Microsoft YaHei", 11, "bold"))
    status_lbl.pack(side="left")
    hint_lbl = tk.Label(header, text="", bg="#ffffff", fg="#8a857a", font=("Microsoft YaHei", 9))
    hint_lbl.pack(side="left", padx=10)

    body = tk.Frame(root, bg="#ffffff")
    body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
    scroll = ttk.Scrollbar(body)
    scroll.pack(side="right", fill="y")
    text = tk.Text(
        body, wrap="word", bd=0, highlightthickness=1, highlightbackground="#e7e5dd",
        bg="#ffffff", fg="#1f1e1c", padx=12, pady=10, font=("Microsoft YaHei", 13),
        yscrollcommand=scroll.set, spacing1=2, spacing3=4,
    )
    text.pack(side="left", fill="both", expand=True)
    scroll.config(command=text.yview)
    text.tag_configure("history", foreground="#55534e")
    text.tag_configure("current", foreground="#c96442")
    text.tag_configure("placeholder", foreground="#b7b3aa")
    text.config(state="disabled")

    ui = {"key": None, "geom": geom}

    def on_configure(_event=None):
        try:
            if root.state() != "normal":
                return
            g = (root.winfo_width(), root.winfo_height(), root.winfo_x(), root.winfo_y())
            if g != ui["geom"]:
                ui["geom"] = g
                _save_geom(*g)
        except Exception:
            pass

    root.bind("<Configure>", on_configure)

    def poll():
        state, mtime = _read_state()
        if mtime == 0.0 or (time.time() - mtime) > _STALE_SECONDS:
            root.destroy()  # 主程序已退出
            return
        if state is not None:
            status = state.get("status", "idle")
            hist = str(state.get("history", "") or "")
            cur = str(state.get("current", "") or "")
            status_lbl.config(
                text={"recording": "● 录音中", "processing": "◌ 转写中", "error": "出错了"}.get(status, "")
            )
            hint_lbl.config(text=str(state.get("hint", "") or ""))
            if (hist, cur) != ui["key"]:
                ui["key"] = (hist, cur)
                text.config(state="normal")
                text.delete("1.0", "end")
                if not hist and not cur:
                    text.insert("end", "（按快捷键开始说话，字幕会实时显示在这里）", "placeholder")
                else:
                    if hist:
                        text.insert("end", hist, "history")
                    if cur:
                        text.insert("end", cur, "current")
                text.config(state="disabled")
                text.see("end")
        root.after(150, poll)

    root.after(150, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
