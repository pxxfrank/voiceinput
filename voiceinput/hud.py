"""悬浮字幕窗。

独立小进程（tkinter 需独占主线程），读取状态文件 ``hud.state`` 渲染：
- 一个状态圆点（红=录音、黄=转写）
- 两行字幕：第一行=已经说过的话，第二行=正在说的话

状态文件由主程序**原子写入**（先写临时文件再替换）；主程序每几秒刷新一次心跳，
一旦主程序退出（文件超 15 秒未更新）本窗自动关闭。窗口可拖动，位置记在 ``hud.pos``。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .config import PROJECT_ROOT

STATE_FILE = PROJECT_ROOT / "hud.state"
POS_FILE = PROJECT_ROOT / "hud.pos"
_STALE_SECONDS = 15.0

_BG = "#1b1b1f"
_FG_PREV = "#9aa0a6"
_FG_CUR = "#ffffff"
_DOT = "#e53935"
_WIDTH = 560

_STATUS_COLOR = {"recording": "#e53935", "processing": "#f9a825", "error": "#c2185b"}
_STATUS_TEXT = {"recording": "录音中", "processing": "转写中", "error": "出错了"}

_DOT_SIZE = (168, 38)


def write_state(obj: dict) -> None:
    """原子写入状态，避免被读到「半个文件」导致字幕窗误判退出。"""
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def clear_state() -> None:
    try:
        STATE_FILE.unlink()
    except Exception:
        pass


def _read_state() -> tuple[dict | None, float]:
    """返回 (状态?, mtime)。文件不存在→(None,0)；内容瞬时不可用→(None,mtime)。"""
    try:
        mtime = STATE_FILE.stat().st_mtime
    except Exception:
        return None, 0.0
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")), mtime
    except Exception:
        return None, mtime


def _load_pos() -> tuple[int, int] | None:
    try:
        x, y = json.loads(POS_FILE.read_text(encoding="utf-8"))
        return int(x), int(y)
    except Exception:
        return None


def _save_pos(x: int, y: int) -> None:
    try:
        POS_FILE.write_text(json.dumps([int(x), int(y)]), encoding="utf-8")
    except Exception:
        pass


def _fit(text: str, limit: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.94)
    except Exception:
        pass
    root.configure(bg=_BG)

    outer = tk.Frame(root, bg=_BG, highlightthickness=1, highlightbackground="#34343a")
    outer.pack(fill="both", expand=True)

    head = tk.Frame(outer, bg=_BG)
    head.pack(fill="x", padx=14, pady=(8, 0))
    dot = tk.Label(head, text="●", fg=_DOT, bg=_BG, font=("Segoe UI", 11))
    dot.pack(side="left")
    status_lbl = tk.Label(head, text="", fg=_FG_PREV, bg=_BG, font=("Microsoft YaHei", 9))
    status_lbl.pack(side="left", padx=(6, 0))

    body = tk.Frame(outer, bg=_BG)
    body.pack(fill="x", padx=14, pady=(2, 10))
    line1 = tk.Label(body, text="", fg=_FG_PREV, bg=_BG, anchor="w")
    line1.pack(fill="x")
    line2 = tk.Label(body, text="", fg=_FG_CUR, bg=_BG, anchor="w")
    line2.pack(fill="x")

    pos = {"xy": _load_pos()}
    shown = {"visible": False, "layout": None, "font": None, "lim1": 40, "lim2": 34}
    drag = {"dx": 0, "dy": 0, "active": False}

    def geometry_for(size: tuple[int, int]) -> None:
        w, h = size
        if pos["xy"] and not drag["active"]:
            x, y = pos["xy"]
        else:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = (sw - w) // 2
            y = sh - h - 96
            if pos["xy"]:  # 用户拖动过后，尺寸变化时保持其水平位置
                x = pos["xy"][0]
        root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

    def on_press(event) -> None:
        drag["active"] = True
        drag["dx"] = event.x_root - root.winfo_x()
        drag["dy"] = event.y_root - root.winfo_y()

    def on_motion(event) -> None:
        if not drag["active"]:
            return
        x = event.x_root - drag["dx"]
        y = event.y_root - drag["dy"]
        pos["xy"] = (x, y)
        root.geometry(f"+{x}+{y}")

    def on_release(_event) -> None:
        if drag["active"]:
            drag["active"] = False
            pos["xy"] = (root.winfo_x(), root.winfo_y())
            _save_pos(*pos["xy"])

    root.bind_all("<ButtonPress-1>", on_press)
    root.bind_all("<B1-Motion>", on_motion)
    root.bind_all("<ButtonRelease-1>", on_release)

    def tick() -> None:
        state, mtime = _read_state()
        if mtime == 0.0 or (time.time() - mtime) > _STALE_SECONDS:
            root.destroy()  # 主程序已退出
            return
        if state is None:  # 瞬时读取问题：保留上一帧，继续
            root.after(120, tick)
            return

        mode = state.get("mode", "show")
        status = state.get("status", "idle")

        if mode == "off" or status not in _STATUS_COLOR:
            if shown["visible"]:
                root.withdraw()
                shown["visible"] = False
            root.after(120, tick)
            return

        dot.config(fg=_STATUS_COLOR.get(status, _DOT))
        status_lbl.config(text=_STATUS_TEXT.get(status, ""))

        if mode == "dot":
            if shown["layout"] != "dot":
                body.pack_forget()
                head.pack_configure(pady=(9, 9))
                geometry_for(_DOT_SIZE)
                shown["layout"], shown["font"] = "dot", None
        else:
            size = max(10, min(40, int(state.get("font_size", 15) or 15)))
            if shown["layout"] != "show" or shown["font"] != size:
                head.pack_configure(pady=(8, 0))
                body.pack(fill="x", padx=14, pady=(2, 10))
                line1.config(font=("Microsoft YaHei", max(9, size - 3)))
                line2.config(font=("Microsoft YaHei", size))
                shown["lim1"] = max(8, int((_WIDTH - 40) / max(9, size - 3)))
                shown["lim2"] = max(8, int((_WIDTH - 40) / size))
                geometry_for((_WIDTH, max(84, int((size - 3) * 1.9 + size * 1.9 + 46))))
                shown["layout"], shown["font"] = "show", size
            line1.config(text=_fit(state.get("line1", ""), shown["lim1"]))
            text2 = _fit(state.get("line2", ""), shown["lim2"])
            if status == "processing" and not text2:
                text2 = "…"
            line2.config(text=text2)

        if not shown["visible"]:
            root.deiconify()
            root.lift()
            shown["visible"] = True
        root.after(120, tick)

    root.withdraw()
    root.after(120, tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
