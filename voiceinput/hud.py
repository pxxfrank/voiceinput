"""悬浮字幕窗（半透明圆角浮层）。

独立小进程（tkinter 需独占主线程），读取状态文件 ``hud.state`` 渲染：
- 顶部：状态圆点（红=录音、黄=转写）+ 说明
- 中部：两行字幕（第一行=已经说过、第二行=正在说）
- 底部：提示当前按什么键可以停止/取消

状态文件由主程序**原子写入**；主程序每几秒刷新心跳，文件超 15 秒未更新则本窗自动关闭。
窗口可拖动，位置记在 ``hud.pos``。
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

_MAGIC = "#0b0c0d"  # 作为窗口透明键色，使圆角外区域完全透明
_PANEL = "#16171a"
_BORDER = "#33343a"
_FG_PREV = "#9aa0a6"
_FG_CUR = "#ffffff"
_STATUS = "#8b8b93"
_HINT = "#77777f"
_DOT = "#e53935"

_DOT_COLOR = {"recording": "#ff5a4d", "processing": "#f9b23c", "error": "#c2185b"}
_STATUS_TEXT = {"recording": "录音中", "processing": "转写中", "error": "出错了"}

_WIDTH = 660
_PAD = 18
_DOT_SIZE = (180, 40)


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
    root.configure(bg=_MAGIC)
    try:
        root.attributes("-transparentcolor", _MAGIC)
    except Exception:
        pass
    try:
        root.attributes("-alpha", 0.86)
    except Exception:
        pass

    canvas = tk.Canvas(root, bg=_MAGIC, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)

    items: dict[str, int] = {}
    pos = {"xy": _load_pos()}
    ui = {"visible": False, "layout": None, "font": None, "lim1": 40, "lim2": 34}
    drag = {"dx": 0, "dy": 0, "active": False}

    def round_rect(x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(pts, smooth=True, **kw)

    def geometry_for(w, h):
        if pos["xy"] and not drag["active"]:
            x, y = pos["xy"]
        else:
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            x = (sw - w) // 2
            y = sh - h - 96
            if pos["xy"]:
                x = pos["xy"][0]
        root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")

    def build_show(size: int):
        canvas.delete("all")
        items.clear()
        size = max(10, min(40, size))
        f1 = max(9, size - 3)
        head_h, hint_h = 22, 18
        l1_h, l2_h = int(f1 * 1.7), int(size * 1.7)
        w = _WIDTH
        h = _PAD + head_h + l1_h + l2_h + hint_h + _PAD
        items["panel"] = round_rect(0, 0, w, h, 18, fill=_PANEL, outline=_BORDER)
        items["dot"] = canvas.create_oval(_PAD, _PAD + 5, _PAD + 13, _PAD + 17, fill=_DOT, outline="")
        items["status"] = canvas.create_text(
            _PAD + 22, _PAD + 11, anchor="w", text="", fill=_STATUS, font=("Microsoft YaHei", 10)
        )
        y1 = _PAD + head_h
        items["line1"] = canvas.create_text(
            _PAD, y1 + l1_h // 2, anchor="w", text="", fill=_FG_PREV, font=("Microsoft YaHei", f1)
        )
        y2 = y1 + l1_h
        items["line2"] = canvas.create_text(
            _PAD, y2 + l2_h // 2, anchor="w", text="", fill=_FG_CUR, font=("Microsoft YaHei", size)
        )
        items["hint"] = canvas.create_text(
            w - _PAD, h - _PAD + 4, anchor="se", text="", fill=_HINT, font=("Microsoft YaHei", 9)
        )
        usable = w - 2 * _PAD
        return w, h, max(6, int(usable / size)), max(6, int(usable / f1))

    def build_dot():
        canvas.delete("all")
        items.clear()
        w, h = _DOT_SIZE
        items["panel"] = round_rect(0, 0, w, h, min(h // 2, 20), fill=_PANEL, outline=_BORDER)
        items["dot"] = canvas.create_oval(_PAD, 13, _PAD + 13, 26, fill=_DOT, outline="")
        items["status"] = canvas.create_text(
            _PAD + 22, 20, anchor="w", text="", fill=_STATUS, font=("Microsoft YaHei", 10)
        )
        return w, h

    def on_press(event):
        drag["active"] = True
        drag["dx"] = event.x_root - root.winfo_x()
        drag["dy"] = event.y_root - root.winfo_y()

    def on_motion(event):
        if not drag["active"]:
            return
        x = event.x_root - drag["dx"]
        y = event.y_root - drag["dy"]
        pos["xy"] = (x, y)
        root.geometry(f"+{x}+{y}")

    def on_release(_event):
        if drag["active"]:
            drag["active"] = False
            pos["xy"] = (root.winfo_x(), root.winfo_y())
            _save_pos(*pos["xy"])

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_motion)
    canvas.bind("<ButtonRelease-1>", on_release)

    def tick():
        state, mtime = _read_state()
        if mtime == 0.0 or (time.time() - mtime) > _STALE_SECONDS:
            root.destroy()  # 主程序已退出
            return
        if state is None:  # 瞬时读取问题：保留上一帧
            root.after(120, tick)
            return

        mode = state.get("mode", "show")
        status = state.get("status", "idle")

        if mode == "off" or status not in _DOT_COLOR:
            if ui["visible"]:
                root.withdraw()
                ui["visible"] = False
            root.after(120, tick)
            return

        if mode == "dot":
            if ui["layout"] != "dot":
                w, h = build_dot()
                geometry_for(w, h)
                ui.update(layout="dot", font=None)
            canvas.itemconfig(items["dot"], fill=_DOT_COLOR.get(status, _DOT))
            canvas.itemconfig(items["status"], text=_STATUS_TEXT.get(status, ""))
        else:
            size = max(10, min(40, int(state.get("font_size", 15) or 15)))
            if ui["layout"] != "show" or ui["font"] != size:
                w, h, lim2, lim1 = build_show(size)
                geometry_for(w, h)
                ui.update(layout="show", font=size, lim2=lim2, lim1=lim1)
            canvas.itemconfig(items["dot"], fill=_DOT_COLOR.get(status, _DOT))
            canvas.itemconfig(items["status"], text=_STATUS_TEXT.get(status, ""))
            canvas.itemconfig(items["line1"], text=_fit(state.get("line1", ""), ui["lim1"]))
            text2 = _fit(state.get("line2", ""), ui["lim2"])
            if status == "processing" and not text2:
                text2 = "…"
            canvas.itemconfig(items["line2"], text=text2)
            canvas.itemconfig(items["hint"], text=str(state.get("hint", "") or ""))

        if not ui["visible"]:
            root.deiconify()
            root.lift()
            ui["visible"] = True
        root.after(120, tick)

    root.withdraw()
    root.after(120, tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
