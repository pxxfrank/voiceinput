"""悬浮字幕窗（半透明圆角浮层）。

独立小进程（tkinter 需独占主线程），读取状态文件 ``hud.state`` 渲染：
- 顶部：状态圆点（红=录音、黄=转写）+ 说明
- 中部：第一行=已经说过的上一句（灰），第二行=正在说的话（白）
- 底部：提示当前按什么键可以停止/取消

字幕按面板宽度**自动换行**（一句话过长则多行呈现），面板高度自适应；
即使当前句很长，上一句也会一直保留在最上面。

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
_HEAD_H = 22
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

    canvas = tk.Canvas(root, bg=_MAGIC, highlightthickness=0, bd=0, width=_WIDTH, height=120)
    canvas.pack(fill="both", expand=True)

    items: dict[str, int] = {}
    pos = {"xy": _load_pos()}
    ui = {"visible": False, "layout": None, "font": None, "h": 0}
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

    def build_show(size: int) -> None:
        canvas.delete("all")
        items.clear()
        size = max(10, min(40, size))
        f1 = max(9, size - 3)
        usable = _WIDTH - 2 * _PAD
        items["dot"] = canvas.create_oval(_PAD, _PAD + 5, _PAD + 13, _PAD + 17, fill=_DOT, outline="")
        items["status"] = canvas.create_text(
            _PAD + 22, _PAD + 11, anchor="w", text="", fill=_STATUS, font=("Microsoft YaHei", 10)
        )
        # 上一句（灰，较小）——始终保留
        items["line1"] = canvas.create_text(
            _PAD, _PAD + _HEAD_H, anchor="nw", text="", fill=_FG_PREV,
            font=("Microsoft YaHei", f1), width=usable,
        )
        # 当前句（白，较大）——过长自动换行
        items["line2"] = canvas.create_text(
            _PAD, _PAD + _HEAD_H, anchor="nw", text="", fill=_FG_CUR,
            font=("Microsoft YaHei", size), width=usable,
        )
        items["hint"] = canvas.create_text(
            _WIDTH - _PAD, 0, anchor="ne", text="", fill=_HINT, font=("Microsoft YaHei", 9)
        )
        items["panel"] = round_rect(0, 0, _WIDTH, 120, 18, fill=_PANEL, outline=_BORDER)
        canvas.tag_lower(items["panel"])
        ui.update(layout="show", font=size, h=0)

    def build_dot() -> None:
        canvas.delete("all")
        items.clear()
        w, h = _DOT_SIZE
        items["panel"] = round_rect(0, 0, w, h, min(h // 2, 20), fill=_PANEL, outline=_BORDER)
        items["dot"] = canvas.create_oval(_PAD, 13, _PAD + 13, 26, fill=_DOT, outline="")
        items["status"] = canvas.create_text(
            _PAD + 22, 20, anchor="w", text="", fill=_STATUS, font=("Microsoft YaHei", 10)
        )
        ui.update(layout="dot", font=None, h=h)

    def layout_show(t1: str, t2: str, hint: str) -> None:
        y = _PAD + _HEAD_H
        if t1:
            canvas.itemconfig(items["line1"], text=t1, state="normal")
            canvas.coords(items["line1"], _PAD, y)
            box = canvas.bbox(items["line1"])
            y = (box[3] if box else y) + 6
        else:
            canvas.itemconfig(items["line1"], text="", state="hidden")

        canvas.itemconfig(items["line2"], text=t2, state="normal")
        canvas.coords(items["line2"], _PAD, y)
        box = canvas.bbox(items["line2"])
        y = (box[3] if box else y) + 8

        if hint:
            canvas.itemconfig(items["hint"], text=hint, state="normal")
            canvas.coords(items["hint"], _WIDTH - _PAD, y)
            y += 16
        else:
            canvas.itemconfig(items["hint"], text="", state="hidden")

        total = int(y + _PAD)
        if total != ui["h"]:
            ui["h"] = total
            canvas.delete(items["panel"])
            items["panel"] = round_rect(0, 0, _WIDTH, total, 18, fill=_PANEL, outline=_BORDER)
            canvas.tag_lower(items["panel"])
            geometry_for(_WIDTH, total)

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
                build_dot()
                geometry_for(*_DOT_SIZE)
            canvas.itemconfig(items["dot"], fill=_DOT_COLOR.get(status, _DOT))
            canvas.itemconfig(items["status"], text=_STATUS_TEXT.get(status, ""))
        else:
            size = max(10, min(40, int(state.get("font_size", 15) or 15)))
            if ui["layout"] != "show" or ui["font"] != size:
                build_show(size)
            canvas.itemconfig(items["dot"], fill=_DOT_COLOR.get(status, _DOT))
            canvas.itemconfig(items["status"], text=_STATUS_TEXT.get(status, ""))
            t1 = str(state.get("line1", "") or "").strip()
            t2 = str(state.get("line2", "") or "").strip()
            if status == "processing" and not t2:
                t2 = "…"
            layout_show(t1, t2, str(state.get("hint", "") or ""))

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
