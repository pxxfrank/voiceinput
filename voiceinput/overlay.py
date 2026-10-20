"""悬浮输入窗与整理结果面板（进程内 Tk，主线程）。

- 悬浮窗置顶、不抢焦点（WS_EX_NOACTIVATE），可拖动、记忆位置。
- 稳定文本与未稳定文本用不同颜色区分；窗口高度固定，避免实时输入时跳动。
- 整理结果面板合并所有片段，提供全文精修、原文对比、编辑、复制/插入。
"""

from __future__ import annotations

import ctypes
import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

log = logging.getLogger("voiceinput.ui")

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

DARK = {
    "bg": "#16171a",
    "card": "#1e1f24",
    "border": "#33343a",
    "fg": "#f2f3f5",
    "muted": "#9aa0a6",
    "accent": "#7aa2f7",
    "danger": "#e5484d",
    "ok": "#46a758",
    "warn": "#f5a524",
    "btn": "#2a2c33",
    "btn_hover": "#363943",
}
LIGHT = {
    "bg": "#f7f7f8",
    "card": "#ffffff",
    "border": "#e3e3e6",
    "fg": "#1c1d20",
    "muted": "#72737a",
    "accent": "#2563eb",
    "danger": "#d92d20",
    "ok": "#15803d",
    "warn": "#b45309",
    "btn": "#f0f0f2",
    "btn_hover": "#e4e4e8",
}


def _system_dark() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except Exception:
        return True


class OverlayWindow:
    def __init__(
        self,
        root: tk.Tk,
        cfg: dict[str, Any],
        on_command: Callable[[str, Any], None],
        on_position: Callable[[int, int], None],
    ) -> None:
        self.root = root
        self.cfg = cfg
        ui = cfg.get("ui", {}) or {}
        theme = ui.get("theme", "dark")
        self.dark = _system_dark() if theme == "system" else theme != "light"
        self.colors = DARK if self.dark else LIGHT
        self.on_command = on_command
        self.on_position = on_position
        self.width = int(ui.get("width", 720))
        self.font_size = int(ui.get("font_size", 14))
        self.opacity = float(ui.get("opacity", 1.0))
        self._drag = {"x": 0, "y": 0, "active": False}
        self._visible = False
        self._state = "idle"
        self._build()
        self._apply_no_activate()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        c = self.colors
        self.root.overrideredirect(True)
        self.root.configure(bg=c["bg"])
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", self.opacity)
        except Exception:
            pass

        self.outer = tk.Frame(self.root, bg=c["bg"], padx=16, pady=12)
        self.outer.pack(fill="both", expand=True)

        header = tk.Frame(self.outer, bg=c["bg"])
        header.pack(fill="x")
        self.dot = tk.Canvas(header, width=12, height=12, bg=c["bg"], highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self._dot_id = self.dot.create_oval(2, 2, 11, 11, fill=c["muted"], outline="")
        self.status = tk.Label(
            header, text="就绪", bg=c["bg"], fg=c["fg"], font=("Microsoft YaHei", 10, "bold")
        )
        self.status.pack(side="left")
        self.mode_label = tk.Label(
            header, text="极速", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9)
        )
        self.mode_label.pack(side="left", padx=(10, 0))
        self.level = tk.Canvas(header, width=110, height=10, bg=c["bg"], highlightthickness=0)
        self.level.pack(side="right")
        self._level_bars = [
            self.level.create_rectangle(i * 6, 2, i * 6 + 4, 8, fill=c["border"], outline="")
            for i in range(18)
        ]

        self.text = tk.Text(
            self.outer,
            height=3,
            wrap="word",
            bg=c["bg"],
            fg=c["fg"],
            insertbackground=c["fg"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=6,
            font=("Microsoft YaHei", self.font_size),
            spacing1=2,
            spacing3=2,
            cursor="arrow",
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("stable", foreground=c["fg"])
        self.text.tag_configure("unstable", foreground=c["muted"])
        self.text.tag_configure("dim", foreground=c["muted"])
        self.text.tag_configure("warn", foreground=c["warn"])
        self.text.configure(state="disabled")

        self.hint = tk.Label(
            self.outer, text="", bg=c["bg"], fg=c["muted"], anchor="w",
            font=("Microsoft YaHei", 9),
        )
        self.hint.pack(fill="x", pady=(2, 6))

        self.buttons = tk.Frame(self.outer, bg=c["bg"])
        self.buttons.pack(fill="x")
        self._button_specs: dict[str, tuple[str, str]] = {}
        self._buttons: dict[str, tk.Button] = {}
        specs = [
            ("stop", "停止"),
            ("commit", "提交"),
            ("refine", "精修"),
            ("cancel", "取消"),
            ("copy", "复制"),
            ("retry", "重试插入"),
        ]
        for key, label in specs:
            btn = tk.Button(
                self.buttons,
                text=label,
                bg=c["btn"],
                fg=c["fg"],
                activebackground=c["btn_hover"],
                activeforeground=c["fg"],
                relief="flat",
                bd=0,
                padx=14,
                pady=5,
                cursor="hand2",
                takefocus=0,
                font=("Microsoft YaHei", 9),
                command=lambda k=key: self.on_command(k, None),
            )
            btn.pack(side="left", padx=(0, 6))
            self._buttons[key] = btn
            self._button_specs[key] = (label, c["btn"])
        self.buttons.pack_forget()

        header.bind("<ButtonPress-1>", self._drag_start)
        header.bind("<B1-Motion>", self._drag_move)
        header.bind("<ButtonRelease-1>", self._drag_end)
        self.status.bind("<ButtonPress-1>", self._drag_start)
        self.status.bind("<B1-Motion>", self._drag_move)
        self.status.bind("<ButtonRelease-1>", self._drag_end)
        self.root.bind("<Escape>", lambda _e: self.on_command("cancel", None))

        self.root.withdraw()

    def _apply_no_activate(self) -> None:
        try:
            self.root.update_idletasks()
            hwnd = int(self.root.winfo_id())
            user32 = ctypes.windll.user32
            parent = user32.GetParent(hwnd)
            targets = [hwnd] + ([parent] if parent else [])
            for h in targets:
                style = user32.GetWindowLongW(h, GWL_EXSTYLE)
                user32.SetWindowLongW(h, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception as exc:
            log.debug("设置悬浮窗不抢焦点失败：%s", exc)

    # ------------------------------------------------------------------ #
    def _drag_start(self, event) -> None:
        self._drag.update(active=True, x=event.x_root - self.root.winfo_x(), y=event.y_root - self.root.winfo_y())

    def _drag_move(self, event) -> None:
        if not self._drag["active"]:
            return
        x = event.x_root - self._drag["x"]
        y = event.y_root - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, _event) -> None:
        if self._drag["active"]:
            self._drag["active"] = False
            self.on_position(self.root.winfo_x(), self.root.winfo_y())

    def _position(self, h: int) -> tuple[int, int]:
        pos = (self.cfg.get("ui", {}) or {}).get("position")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                x, y = int(pos[0]), int(pos[1])
                x = max(0, min(x, sw - self.width))
                y = max(0, min(y, sh - h))
                return x, y
            except Exception:
                pass
        return (sw - self.width) // 2, sh - h - 90

    def _apply_region(self, h: int) -> None:
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
            hwnd = wintypes.HWND(int(self.root.winfo_id()))
            parent = user32.GetParent(hwnd)
            target = parent or hwnd
            rgn = gdi32.CreateRoundRectRgn(0, 0, int(self.width) + 1, int(h) + 1, 18, 18)
            user32.SetWindowRgn(target, rgn, True)
        except Exception:
            pass

    def show(self, state: str = "recording") -> None:
        self._state = state
        if str((self.cfg.get("ui", {}) or {}).get("overlay", "show")) == "off":
            return
        h = 250
        x, y = self._position(h)
        self.root.geometry(f"{self.width}x{h}+{x}+{y}")
        if not self._visible:
            self.root.deiconify()
            self._apply_no_activate()
            self._visible = True
        self.root.lift()
        self.root.attributes("-topmost", True)

    def hide(self) -> None:
        if self._visible:
            self.root.withdraw()
            self._visible = False

    # ------------------------------------------------------------------ #
    def set_state(self, state: str, *, status: str = "", hint: str = "", mode: str = "") -> None:
        self._state = state
        c = self.colors
        colors = {
            "recording": c["danger"],
            "processing": c["warn"],
            "review": c["accent"],
            "error": c["danger"],
            "target_changed": c["warn"],
            "idle": c["muted"],
            "done": c["ok"],
        }
        self.dot.itemconfigure(self._dot_id, fill=colors.get(state, c["muted"]))
        self.status.configure(text=status or {
            "recording": "录音中",
            "processing": "处理中",
            "review": "待确认",
            "error": "出错了",
            "target_changed": "目标已变化",
            "done": "完成",
        }.get(state, "就绪"))
        self.hint.configure(text=hint)
        if mode:
            self.mode_label.configure(text=mode)
        self._update_buttons(state)

    def _update_buttons(self, state: str) -> None:
        visible = {
            "recording": {"stop", "commit", "refine", "cancel"},
            "processing": {"cancel"},
            "target_changed": {"retry", "copy", "cancel"},
            "review": {"commit", "copy", "cancel"},
            "done": set(),
            "idle": set(),
            "error": {"cancel"},
        }.get(state, set())
        for key, btn in self._buttons.items():
            if key in visible:
                btn.pack(side="left", padx=(0, 6))
            else:
                btn.pack_forget()
        if visible:
            self.buttons.pack(fill="x")
        else:
            self.buttons.pack_forget()

    def set_level(self, db: float) -> None:
        c = self.colors
        normalized = max(0.0, min(1.0, (db + 60.0) / 55.0))
        active = int(round(normalized * len(self._level_bars)))
        for i, item in enumerate(self._level_bars):
            color = c["accent"] if i < active else c["border"]
            if i < active and i > len(self._level_bars) - 4:
                color = c["warn"]
            self.level.itemconfigure(item, fill=color)

    def set_text(self, stable: str, unstable: str = "", *, dim: str = "") -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if dim and not stable and not unstable:
            self.text.insert("1.0", dim, "dim")
        else:
            if stable:
                self.text.insert("end", stable, "stable")
            if unstable:
                self.text.insert("end", unstable, "unstable")
        self.text.configure(state="disabled")
        self.text.see("end")

    def set_mode(self, mode: str) -> None:
        self.mode_label.configure(text={"fast": "极速", "smart": "精修", "auto": "自动"}.get(mode, mode))


class ReviewWindow:
    """原文 / 精修对照面板。"""

    def __init__(
        self,
        root: tk.Tk,
        cfg: dict[str, Any],
        on_command: Callable[[str, Any], None],
    ) -> None:
        self.root = root
        self.cfg = cfg
        self.on_command = on_command
        self.colors = DARK if (cfg.get("ui", {}) or {}).get("theme", "dark") != "light" else LIGHT
        self.win: tk.Toplevel | None = None
        self.text = ""
        self.original = ""
        self._dirty = False
        self.compare: CompareWindow | None = None

    def _ensure(self) -> tk.Toplevel:
        if self.win and self.win.winfo_exists():
            return self.win
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("整理结果 - 本地语音输入")
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        width = min(960, max(760, sw - 140))
        height = min(680, max(500, sh - 140))
        win.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")
        win.minsize(760, 500)
        win.configure(bg=c["bg"])
        win.protocol("WM_DELETE_WINDOW", self.hide)

        top = tk.Frame(win, bg=c["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="整理结果", bg=c["bg"], fg=c["fg"], font=("Microsoft YaHei", 14, "bold")).pack(side="left")
        self.model_label = tk.Label(top, text="", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9))
        self.model_label.pack(side="right")

        toolbar = tk.Frame(win, bg=c["bg"], padx=16, pady=0)
        toolbar.pack(fill="x")
        tk.Button(
            toolbar, text="精修全文", bg=c["btn"], fg=c["fg"], activebackground=c["btn_hover"],
            activeforeground=c["fg"], relief="flat", bd=0, padx=12, pady=5,
            cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9),
            command=lambda: self.on_command("review_refine_all", None),
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            toolbar, text="对比原文", bg=c["bg"], fg=c["muted"], activebackground=c["bg"],
            activeforeground=c["fg"], relief="flat", bd=0, padx=8, pady=5,
            cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9), command=self._open_compare,
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            toolbar, text="恢复原文", bg=c["bg"], fg=c["muted"], activebackground=c["bg"],
            activeforeground=c["fg"], relief="flat", bd=0, padx=8, pady=5,
            cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9), command=self._restore_original,
        ).pack(side="left")
        self.info = tk.Label(toolbar, text="", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9))
        self.info.pack(side="right")

        body = tk.Frame(win, bg=c["bg"], padx=16)
        body.pack(fill="both", expand=True)
        self.editor = tk.Text(
            body, wrap="word", bd=0, highlightthickness=1, highlightbackground=c["border"],
            bg=c["card"], fg=c["fg"], padx=14, pady=12, undo=True,
            font=("Microsoft YaHei", 11), spacing1=3, spacing3=3,
        )
        self.editor.tag_configure("base", foreground=c["fg"])
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<KeyRelease>", self._on_edit)

        bottom = tk.Frame(win, bg=c["bg"], padx=16, pady=10)
        bottom.pack(side="bottom", fill="x")
        tk.Button(
            bottom, text="插入到原窗口", bg=c["accent"], fg="#ffffff",
            activebackground=c["btn_hover"], activeforeground="#ffffff", relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9),
            command=lambda: self.on_command("review_insert", None),
        ).pack(side="left", padx=(0, 8))
        for label, action in (("复制", "review_copy"), ("关闭", "review_close")):
            tk.Button(
                bottom, text=label, bg=c["btn"], fg=c["fg"], activebackground=c["btn_hover"],
                activeforeground=c["fg"], relief="flat", bd=0, padx=14, pady=7,
                cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9),
                command=lambda a=action: self.on_command(a, None),
            ).pack(side="left", padx=(0, 8))
        self.status = tk.Label(bottom, text="", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9))
        self.status.pack(side="right")
        bottom.pack_forget()
        bottom.pack(side="bottom", fill="x", before=body)

        self.win = win
        return win

    def show(self, text: str, original: str = "", *, model_status: str = "", status: str = "") -> None:
        self.text = (text or "").strip()
        self.original = (original or "").strip()
        self._dirty = False
        win = self._ensure()
        self.model_label.configure(text=model_status)
        self.status.configure(text=status or "可直接编辑、精修全文、对比原文或复制")
        self._set_editor(self.text)
        self.info.configure(text=f"{len(self.text)} 字")
        win.deiconify()
        win.lift()
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        win.focus_force()

    def update_texts(self, text: str, original: str, *, force: bool = False) -> None:
        """片段更新时刷新合并文本；用户已手动编辑时不覆盖。"""
        self.original = (original or "").strip()
        if not self._dirty or force:
            self.text = (text or "").strip()
            self._set_editor(self.text)
            self._dirty = False
        if self.win and self.win.winfo_exists():
            self.info.configure(text=f"{len(self.get_text())} 字")
            if self.compare:
                self.compare.show(self.original, self.get_text())

    def _set_editor(self, text: str) -> None:
        if not hasattr(self, "editor"):
            return
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text, "base")
        self.editor.configure(fg=self.colors["fg"], insertbackground=self.colors["fg"])

    def get_text(self) -> str:
        if not hasattr(self, "editor"):
            return self.text
        return self.editor.get("1.0", "end-1c").strip()

    def hide(self) -> None:
        if self.compare:
            self.compare.hide()
        if self.win and self.win.winfo_exists():
            self.win.withdraw()

    @property
    def visible(self) -> bool:
        return bool(self.win and self.win.winfo_exists() and self.win.state() != "withdrawn")

    def _on_edit(self, _event=None) -> None:
        self._dirty = True
        self.text = self.get_text()
        self.info.configure(text=f"{len(self.text)} 字")
        self.status.configure(text="已手动修改；插入/复制以此为准")

    def _restore_original(self) -> None:
        self._set_editor(self.original)
        self._dirty = True
        self.text = self.original
        self.info.configure(text=f"{len(self.text)} 字")
        self.status.configure(text="已恢复原文；可继续编辑或复制")

    def _open_compare(self) -> None:
        if self.compare is None:
            self.compare = CompareWindow(self.root, self.cfg)
        self.compare.show(self.original, self.get_text())

    def current_selection(self) -> tuple[str, str, str] | None:
        """返回 (选中文本, 起始索引, 结束索引)；无选中返回 None。"""
        try:
            if self.editor.tag_ranges("sel"):
                start = self.editor.index("sel.first")
                end = self.editor.index("sel.last")
                text = self.editor.get(start, end)
                if text.strip():
                    return text, start, end
        except Exception:
            pass
        return None

    def replace_selection(self, new_text: str) -> None:
        try:
            if not self.editor.tag_ranges("sel"):
                return
            start = self.editor.index("sel.first")
            end = self.editor.index("sel.last")
            self.editor.delete(start, end)
            self.editor.insert(start, new_text)
            self._on_edit()
            self.status.configure(text="已替换选中内容")
        except Exception:
            pass

    def set_status(self, text: str, *, model_status: str | None = None) -> None:
        if self.win and self.win.winfo_exists():
            self.status.configure(text=text)
            if model_status is not None:
                self.model_label.configure(text=model_status)

    def refresh(self) -> None:
        if self.visible:
            self.info.configure(text=f"{len(self.get_text())} 字")


class CompareWindow:
    """只读的原文 / 当前结果对照，不打断主编辑框。"""

    def __init__(self, root: tk.Tk, cfg: dict[str, Any]) -> None:
        self.root = root
        self.cfg = cfg
        self.colors = DARK if (cfg.get("ui", {}) or {}).get("theme", "dark") != "light" else LIGHT
        self.win: tk.Toplevel | None = None
        self.left: tk.Text | None = None
        self.right: tk.Text | None = None

    def _ensure(self) -> tk.Toplevel:
        if self.win and self.win.winfo_exists():
            return self.win
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("对比原文 - 本地语音输入")
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        width, height = min(1000, max(760, sw - 160)), min(620, max(460, sh - 160))
        win.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")
        win.minsize(760, 460)
        win.configure(bg=c["bg"])
        win.protocol("WM_DELETE_WINDOW", self.hide)

        top = tk.Frame(win, bg=c["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="原文 / 当前结果", bg=c["bg"], fg=c["fg"], font=("Microsoft YaHei", 13, "bold")).pack(side="left")
        tk.Button(
            top, text="关闭", bg=c["btn"], fg=c["fg"], activebackground=c["btn_hover"],
            activeforeground=c["fg"], relief="flat", bd=0, padx=12, pady=5,
            cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9), command=self.hide,
        ).pack(side="right")

        body = tk.Frame(win, bg=c["bg"], padx=16, pady=0)
        body.pack(fill="both", expand=True)
        left_frame = tk.Frame(body, bg=c["bg"])
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left_frame, text="原文", bg=c["bg"], fg=c["muted"], anchor="w", font=("Microsoft YaHei", 9)).pack(fill="x")
        self.left = tk.Text(
            left_frame, wrap="word", bd=0, highlightthickness=1, highlightbackground=c["border"],
            bg=c["card"], fg=c["fg"], padx=10, pady=8, font=("Microsoft YaHei", 10),
        )
        self.left.pack(fill="both", expand=True)
        right_frame = tk.Frame(body, bg=c["bg"])
        right_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right_frame, text="当前结果", bg=c["bg"], fg=c["muted"], anchor="w", font=("Microsoft YaHei", 9)).pack(fill="x")
        self.right = tk.Text(
            right_frame, wrap="word", bd=0, highlightthickness=1, highlightbackground=c["border"],
            bg=c["card"], fg=c["fg"], padx=10, pady=8, font=("Microsoft YaHei", 10),
        )
        self.right.pack(fill="both", expand=True)
        for widget in (self.left, self.right):
            widget.configure(state="disabled")
            widget.tag_configure("base", foreground=c["fg"])
            widget.tag_configure("del", foreground="#e5484d", overstrike=True)
            widget.tag_configure("ins", foreground="#46a758", underline=True)
        self.win = win
        return win

    def show(self, original: str, current: str) -> None:
        from .refinement import diff_ops

        win = self._ensure()
        assert self.left is not None and self.right is not None
        self.left.configure(state="normal")
        self.right.configure(state="normal")
        self.left.delete("1.0", "end")
        self.right.delete("1.0", "end")
        for tag, left_text, right_text in diff_ops(original or "", current or ""):
            if left_text:
                self.left.insert("end", left_text, "del" if tag in ("delete", "replace") else "base")
            if right_text:
                self.right.insert("end", right_text, "ins" if tag in ("insert", "replace") else "base")
        self.left.configure(state="disabled")
        self.right.configure(state="disabled")
        win.deiconify()
        win.lift()
        win.focus_force()

    def hide(self) -> None:
        if self.win and self.win.winfo_exists():
            self.win.withdraw()


class DiffWindow:
    """原文 / 精修差异对照，支持逐条接受或拒绝 LLM 修改。"""

    def __init__(self, root: tk.Tk, cfg: dict[str, Any], on_command: Callable[[str, Any], None]) -> None:
        self.root = root
        self.cfg = cfg
        self.on_command = on_command
        self.colors = DARK if (cfg.get("ui", {}) or {}).get("theme", "dark") != "light" else LIGHT
        self.win: tk.Toplevel | None = None
        self.segment: Any = None
        self.decisions: list[bool] = []

    def _ensure(self) -> tk.Toplevel:
        if self.win and self.win.winfo_exists():
            return self.win
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("精修差异对照 - 本地语音输入")
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        width, height = min(1000, max(760, sw - 160)), min(680, max(500, sh - 160))
        win.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")
        win.minsize(760, 500)
        win.configure(bg=c["bg"])
        win.protocol("WM_DELETE_WINDOW", self.hide)

        top = tk.Frame(win, bg=c["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="差异对照", bg=c["bg"], fg=c["fg"], font=("Microsoft YaHei", 14, "bold")).pack(side="left")
        self.info = tk.Label(top, text="", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9))
        self.info.pack(side="right")

        body = tk.Frame(win, bg=c["bg"], padx=16)
        body.pack(fill="both", expand=True)

        panes = tk.Frame(body, bg=c["bg"])
        panes.pack(fill="both", expand=True)
        left_frame = tk.Frame(panes, bg=c["bg"])
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left_frame, text="原文", bg=c["bg"], fg=c["muted"], anchor="w", font=("Microsoft YaHei", 9)).pack(fill="x")
        self.left = tk.Text(
            left_frame, wrap="word", bd=0, highlightthickness=1, highlightbackground=c["border"],
            bg=c["card"], fg=c["fg"], padx=10, pady=8, font=("Microsoft YaHei", 10),
        )
        self.left.pack(fill="both", expand=True)

        right_frame = tk.Frame(panes, bg=c["bg"])
        right_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right_frame, text="精修", bg=c["bg"], fg=c["muted"], anchor="w", font=("Microsoft YaHei", 9)).pack(fill="x")
        self.right = tk.Text(
            right_frame, wrap="word", bd=0, highlightthickness=1, highlightbackground=c["border"],
            bg=c["card"], fg=c["fg"], padx=10, pady=8, font=("Microsoft YaHei", 10),
        )
        self.right.pack(fill="both", expand=True)

        for widget in (self.left, self.right):
            widget.configure(state="disabled")
            widget.tag_configure("base", foreground=c["fg"])
            widget.tag_configure("del", foreground="#e5484d", overstrike=True)
            widget.tag_configure("ins", foreground="#46a758", underline=True)

        list_frame = tk.Frame(win, bg=c["bg"], padx=16, pady=8)
        list_frame.pack(fill="x")
        tk.Label(
            list_frame, text="修改条目（双击切换接受/拒绝）", bg=c["bg"], fg=c["muted"], anchor="w",
            font=("Microsoft YaHei", 9),
        ).pack(fill="x")
        self.tree = ttk.Treeview(
            list_frame, columns=("no", "source", "replacement", "reason", "decision"),
            show="headings", height=5,
        )
        for col, title, width in (
            ("no", "#", 34), ("source", "原文", 220), ("replacement", "修改后", 220),
            ("reason", "原因", 220), ("decision", "状态", 70),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="x")
        self.tree.bind("<Double-1>", lambda _e: self.toggle_selected())

        bar = tk.Frame(win, bg=c["bg"], padx=16, pady=10)
        bar.pack(fill="x")
        for label, command in (
            ("全部接受", lambda: self.set_all(True)),
            ("全部拒绝", lambda: self.set_all(False)),
            ("接受选中", lambda: self.set_selected(True)),
            ("拒绝选中", lambda: self.set_selected(False)),
            ("关闭", self.hide),
        ):
            tk.Button(
                bar, text=label, bg=c["btn"], fg=c["fg"], activebackground=c["btn_hover"],
                activeforeground=c["fg"], relief="flat", bd=0, padx=12, pady=6,
                cursor="hand2", takefocus=0, font=("Microsoft YaHei", 9), command=command,
            ).pack(side="left", padx=(0, 8))
        self.status = tk.Label(bar, text="", bg=c["bg"], fg=c["muted"], font=("Microsoft YaHei", 9))
        self.status.pack(side="right")
        # 先占住底部空间，避免 expand 的正文把按钮挤出窗口
        list_frame.pack_forget()
        bar.pack_forget()
        bar.pack(side="bottom", fill="x", before=body)
        list_frame.pack(side="bottom", fill="x", before=body)
        self.win = win
        return win

    def show(self, segment: Any) -> None:
        if segment is None:
            return
        self.segment = segment
        self.decisions = list(getattr(segment, "edit_decisions", []) or [])
        if len(self.decisions) != len(getattr(segment, "edits", []) or []):
            self.decisions = [True] * len(getattr(segment, "edits", []) or [])
        win = self._ensure()
        self._render()
        win.deiconify()
        win.lift()
        win.focus_force()

    def hide(self) -> None:
        if self.win and self.win.winfo_exists():
            self.win.withdraw()

    @property
    def visible(self) -> bool:
        return bool(self.win and self.win.winfo_exists() and self.win.state() != "withdrawn")

    def refresh(self) -> None:
        if self.segment is not None:
            self._render()

    def _render(self) -> None:
        seg = self.segment
        if seg is None:
            return
        from .refinement import diff_ops

        original = getattr(seg, "faithful_text", "") or ""
        revised = (getattr(seg, "user_edited", "") or getattr(seg, "refined", "") or original).strip()
        self.left.configure(state="normal")
        self.right.configure(state="normal")
        self.left.delete("1.0", "end")
        self.right.delete("1.0", "end")
        for tag, left_text, right_text in diff_ops(original, revised):
            if left_text:
                self.left.insert("end", left_text, "del" if tag in ("delete", "replace") else "base")
            if right_text:
                self.right.insert("end", right_text, "ins" if tag in ("insert", "replace") else "base")
        self.left.configure(state="disabled")
        self.right.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)
        edits = list(getattr(seg, "edits", []) or [])
        for i, edit in enumerate(edits):
            decision = bool(self.decisions[i]) if i < len(self.decisions) else True
            self.tree.insert(
                "", "end", iid=str(i),
                values=(i + 1, edit.get("source", ""), edit.get("replacement", ""), edit.get("reason", ""),
                        "接受" if decision else "拒绝"),
            )
        self.info.configure(text=f"{len(edits)} 条修改 · {getattr(seg, 'refine_ms', 0):.0f} ms")
        self.status.configure(
            text="模型未提供逐条修改，可用“恢复原文”或直接编辑" if not edits else "逐条选择后立即生效"
        )

    def _apply(self) -> None:
        if self.segment is None:
            return
        self.on_command("diff_apply", (self.segment, list(self.decisions)))

    def set_all(self, value: bool) -> None:
        self.decisions = [value] * len(getattr(self.segment, "edits", []) or [])
        self._render()
        self._apply()

    def set_selected(self, value: bool) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        for item in selection:
            index = int(item)
            if index < len(self.decisions):
                self.decisions[index] = value
        self._render()
        self._apply()

    def toggle_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        index = int(item)
        if index < len(self.decisions):
            self.decisions[index] = not self.decisions[index]
        self._render()
        self._apply()
