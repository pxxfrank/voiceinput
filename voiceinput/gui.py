"""图形化设置界面（tkinter，无第三方 UI 依赖）。

八个分区：常规 / 麦克风与音频 / 语音识别 / 智能精修 / 专业词库 / 快捷键 /
历史记录 / 性能与诊断。保存后写用户目录配置；「保存并重启」通知主程序重启。
"""

from __future__ import annotations

import csv
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import autostart, modelstore, paths
from .audio import Recorder, list_input_devices
from .config import load_config, save_config
from .diagnostics import collect, format_text
from .storage import Storage

_BG = "#f5f4ef"
_CARD = "#ffffff"
_BORDER = "#e5e3db"
_FG = "#1f1e1c"
_MUTED = "#8a857a"
_ACCENT = "#c96442"
_ACCENT_HOVER = "#b8573a"


def _input_device_items() -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = [("（系统默认）", None)]
    for dev in list_input_devices():
        items.append((f"{dev['id']}: {dev['name']}", dev["id"]))
    return items


class SettingsApp:
    def __init__(self, root: tk.Tk, cfg: dict[str, Any], config_path: str | None = None) -> None:
        self.root = root
        self.cfg = cfg
        self.config_path = config_path
        self.storage = Storage()
        self.exit_code = 0
        self.var: dict[str, tk.Variable] = {}
        self._devices = _input_device_items()
        self._reviewer = None
        self._llm_server = None
        self._busy = False

        root.title("本地语音输入 · 设置")
        root.geometry("860x660")
        root.minsize(780, 580)
        root.configure(bg=_BG)
        try:
            root.attributes("-topmost", True)
            root.after(900, lambda: root.attributes("-topmost", False))
        except Exception:
            pass
        root.lift()
        root.focus_force()
        self._style()
        self._build()
        self._fill()

    # ------------------------------------------------------------------ #
    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        base = ("Microsoft YaHei", 10)
        style.configure(".", background=_BG, foreground=_FG, font=base)
        style.configure("TFrame", background=_BG)
        style.configure("TLabel", background=_BG, foreground=_FG)
        style.configure("Muted.TLabel", background=_CARD, foreground=_MUTED, font=("Microsoft YaHei", 9))
        style.configure("Title.TLabel", background=_BG, foreground=_FG, font=("Microsoft YaHei", 17, "bold"))
        style.configure("Sub.TLabel", background=_BG, foreground=_MUTED, font=("Microsoft YaHei", 9))
        style.configure("TNotebook", background=_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=_BG, foreground=_MUTED, padding=(14, 7), font=base)
        style.map("TNotebook.Tab", background=[("selected", _CARD)], foreground=[("selected", _FG)])
        style.configure("TEntry", padding=5, fieldbackground="#ffffff")
        style.configure("TCombobox", padding=4)
        style.configure("TSpinbox", padding=4)
        style.configure("TButton", padding=(12, 6), background="#fbfbf9")
        style.map("TButton", background=[("active", "#f0eee7")])
        style.configure("Accent.TButton", background=_ACCENT, foreground="#ffffff", padding=(14, 7))
        style.map("Accent.TButton", background=[("active", _ACCENT_HOVER)])
        style.configure("TCheckbutton", background=_CARD, foreground=_FG)
        style.configure("TRadiobutton", background=_CARD, foreground=_FG)
        style.configure("Treeview", background=_CARD, fieldbackground=_CARD, foreground=_FG, rowheight=26)
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 9, "bold"))

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        header = tk.Frame(self.root, bg=_BG, padx=22, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="本地语音输入", bg=_BG, fg=_FG, font=("Microsoft YaHei", 18, "bold")).pack(anchor="w")
        tk.Label(header, text=f"v{paths.VERSION} · 全部离线 · 数据目录 {paths.data_root()}", bg=_BG, fg=_MUTED, font=("Microsoft YaHei", 9)).pack(anchor="w")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(4, 6))
        self._tab_general()
        self._tab_audio()
        self._tab_asr()
        self._tab_refine()
        self._tab_terms()
        self._tab_hotkeys()
        self._tab_history()
        self._tab_diagnostics()

        footer = tk.Frame(self.root, bg=_BG, padx=20, pady=12)
        footer.pack(fill="x")
        ttk.Button(footer, text="关闭", command=self.root.destroy).pack(side="left")
        self.var["footer_status"] = tk.StringVar(value="")
        tk.Label(footer, textvariable=self.var["footer_status"], bg=_BG, fg=_MUTED, font=("Microsoft YaHei", 9)).pack(side="left", padx=14)
        ttk.Button(footer, text="保存并重启", style="Accent.TButton", command=lambda: self._save(restart=True)).pack(side="right")
        ttk.Button(footer, text="保存", command=self._save).pack(side="right", padx=(0, 8))

    def _scrollable(self, parent) -> tk.Frame:
        canvas = tk.Canvas(parent, bg=_BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=_BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure("inner", width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        return inner

    def _page(self, title: str) -> tk.Frame:
        outer = tk.Frame(self.notebook, bg=_BG)
        self.notebook.add(outer, text=title)
        inner = self._scrollable(outer)
        frame = tk.Frame(inner, bg=_BG, padx=8, pady=10)
        frame.pack(fill="both", expand=True)
        return frame

    def _card(self, parent, title: str = "") -> tk.Frame:
        outer = tk.Frame(parent, bg=_BORDER)
        outer.pack(fill="x", pady=(0, 12))
        card = tk.Frame(outer, bg=_CARD, padx=16, pady=14)
        card.pack(fill="x", padx=1, pady=1)
        if title:
            tk.Label(card, text=title, bg=_CARD, fg=_FG, font=("Microsoft YaHei", 11, "bold")).pack(anchor="w", pady=(0, 8))
        return card

    def _row(self, card, label: str, hint: str = "") -> tk.Frame:
        row = tk.Frame(card, bg=_CARD)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=_CARD, fg=_FG, width=18, anchor="w").pack(side="left")
        holder = tk.Frame(row, bg=_CARD)
        holder.pack(side="left", fill="x", expand=True)
        if hint:
            tk.Label(row, text=hint, bg=_CARD, fg=_MUTED, font=("Microsoft YaHei", 8)).pack(side="right")
        return holder

    def _note(self, card, text: str) -> None:
        tk.Label(card, text=text, bg=_CARD, fg=_MUTED, justify="left", anchor="w", wraplength=700, font=("Microsoft YaHei", 9)).pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------------ #
    def _tab_general(self) -> None:
        page = self._page("常规")
        card = self._card(page, "输入模式")
        self.var["mode"] = tk.StringVar()
        box = self._row(card, "默认模式")
        ttk.Combobox(
            box, textvariable=self.var["mode"], state="readonly", width=18,
            values=["极速输入", "智能精修", "自动"],
        ).pack(side="left")
        self._note(card, "极速：说完立即上屏，不调用 LLM；精修：面板确认后插入；自动：短句极速，长时自动转精修确认（不会自动改写风格）。")

        card = self._card(page, "外观与启动")
        self.var["autostart"] = tk.BooleanVar()
        ttk.Checkbutton(card, text="开机自动启动", variable=self.var["autostart"], command=self._toggle_autostart).pack(anchor="w")
        self.var["theme"] = tk.StringVar()
        box = self._row(card, "主题")
        ttk.Combobox(box, textvariable=self.var["theme"], state="readonly", width=12, values=["dark", "light", "system"]).pack(side="left")
        self.var["overlay"] = tk.StringVar()
        box = self._row(card, "悬浮窗")
        ttk.Combobox(box, textvariable=self.var["overlay"], state="readonly", width=14, values=["show", "off"]).pack(side="left")
        self.var["width"] = tk.StringVar()
        box = self._row(card, "悬浮窗宽度")
        ttk.Spinbox(box, from_=420, to=1200, textvariable=self.var["width"], width=8).pack(side="left")
        self.var["font_size"] = tk.StringVar()
        box = self._row(card, "字幕字号")
        ttk.Spinbox(box, from_=10, to=32, textvariable=self.var["font_size"], width=8).pack(side="left")

    def _tab_audio(self) -> None:
        page = self._page("麦克风与音频")
        card = self._card(page, "输入设备")
        self.var["device"] = tk.StringVar()
        box = self._row(card, "麦克风")
        ttk.Combobox(box, textvariable=self.var["device"], values=[x[0] for x in self._devices], state="readonly", width=42).pack(side="left", fill="x", expand=True)
        ttk.Button(card, text="自动检测", command=self._detect_mic).pack(anchor="w", pady=(8, 0))
        self.var["audio_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["audio_status"], bg=_CARD, fg=_ACCENT, anchor="w", justify="left", wraplength=700).pack(fill="x", pady=(8, 0))

        card = self._card(page, "端点与静音")
        self.var["endpoint_ms"] = tk.StringVar()
        box = self._row(card, "句末静音（毫秒）")
        ttk.Spinbox(box, from_=200, to=3000, increment=50, textvariable=self.var["endpoint_ms"], width=8).pack(side="left")
        self.var["min_segment"] = tk.StringVar()
        box = self._row(card, "最短片段（秒）")
        ttk.Spinbox(box, from_=0.2, to=3.0, increment=0.1, textvariable=self.var["min_segment"], width=8).pack(side="left")
        self.var["max_segment"] = tk.StringVar()
        box = self._row(card, "最长片段（秒）")
        ttk.Spinbox(box, from_=5, to=60, textvariable=self.var["max_segment"], width=8).pack(side="left")
        self.var["silence_timeout"] = tk.StringVar()
        box = self._row(card, "无语音自动停止（秒）")
        ttk.Spinbox(box, from_=0, to=300, textvariable=self.var["silence_timeout"], width=8).pack(side="left")
        self._note(card, "句末静音只结束当前片段，不会结束整个输入会话；短暂停顿可以继续说。")

        card = self._card(page, "麦克风测试")
        self.var["mic_test_status"] = tk.StringVar(value="录 4 秒并调用本机识别模型。")
        tk.Label(card, textvariable=self.var["mic_test_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=700).pack(fill="x")
        self.mic_test_text = tk.Text(card, height=4, wrap="word", bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, padx=8, pady=6, font=("Microsoft YaHei", 10))
        self.mic_test_text.pack(fill="x", pady=(8, 6))
        bar = tk.Frame(card, bg=_CARD)
        bar.pack(fill="x")
        self.mic_test_btn = ttk.Button(bar, text="开始录音测试", command=self._test_mic)
        self.mic_test_btn.pack(side="left")

    def _tab_asr(self) -> None:
        page = self._page("语音识别")
        card = self._card(page, "流式主模型")
        self.var["stream_model"] = tk.StringVar(value=str(modelstore.find_streaming_dir(self.cfg) or "未找到"))
        tk.Label(card, textvariable=self.var["stream_model"], bg=_CARD, fg=_MUTED, anchor="w", wraplength=700, font=("Microsoft YaHei", 9)).pack(fill="x")
        self.var["threads"] = tk.StringVar()
        box = self._row(card, "推理线程")
        ttk.Spinbox(box, from_=1, to=16, textvariable=self.var["threads"], width=8).pack(side="left")

        card = self._card(page, "识别复核（非流式）")
        self.var["review_enabled"] = tk.BooleanVar()
        ttk.Checkbutton(card, text="启用复核模型（SenseVoice）", variable=self.var["review_enabled"]).pack(anchor="w")
        self.var["review_mode"] = tk.StringVar()
        box = self._row(card, "复核策略")
        ttk.Combobox(box, textvariable=self.var["review_mode"], state="readonly", width=14, values=["off", "auto", "always"]).pack(side="left")
        self.var["review_min"] = tk.StringVar()
        box = self._row(card, "最短复核时长（秒）")
        ttk.Spinbox(box, from_=0.5, to=15, increment=0.5, textvariable=self.var["review_min"], width=8).pack(side="left")
        self.var["review_timeout"] = tk.StringVar()
        box = self._row(card, "复核超时（秒）")
        ttk.Spinbox(box, from_=0.5, to=10, increment=0.5, textvariable=self.var["review_timeout"], width=8).pack(side="left")
        self._note(card, "复核结果不会无条件覆盖流式结果：数字/术语丢失或相似度过低时保留流式结果并标记。")

        card = self._card(page, "模型检查")
        self.var["asr_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["asr_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=700).pack(fill="x")
        ttk.Button(card, text="校验模型文件", command=self._verify_models).pack(anchor="w", pady=(8, 0))

    def _tab_refine(self) -> None:
        page = self._page("智能精修")
        card = self._card(page, "本地 LLM")
        self.var["refine_enabled"] = tk.BooleanVar()
        ttk.Checkbutton(card, text="启用 LLM 精修（关闭后只用忠实转录）", variable=self.var["refine_enabled"]).pack(anchor="w")
        self.var["refine_level"] = tk.StringVar()
        box = self._row(card, "精修档位")
        ttk.Combobox(box, textvariable=self.var["refine_level"], state="readonly", width=14, values=["faithful", "standard", "deep"]).pack(side="left")
        self.var["preload"] = tk.BooleanVar()
        ttk.Checkbutton(card, text="启动时预加载模型（首用更快，占用内存）", variable=self.var["preload"]).pack(anchor="w", pady=(4, 0))
        self.var["refine_threads"] = tk.StringVar()
        box = self._row(card, "推理线程（0=自动）")
        ttk.Spinbox(box, from_=0, to=16, textvariable=self.var["refine_threads"], width=8).pack(side="left")
        self.var["refine_timeout"] = tk.StringVar()
        box = self._row(card, "超时（秒）")
        ttk.Spinbox(box, from_=2, to=60, textvariable=self.var["refine_timeout"], width=8).pack(side="left")
        self.var["idle_unload"] = tk.StringVar()
        box = self._row(card, "空闲卸载（秒，0=不卸载）")
        ttk.Spinbox(box, from_=0, to=3600, increment=60, textvariable=self.var["idle_unload"], width=8).pack(side="left")
        self.var["llm_model"] = tk.StringVar(value=str(modelstore.find_llm_model(self.cfg) or "未找到"))
        tk.Label(card, textvariable=self.var["llm_model"], bg=_CARD, fg=_MUTED, anchor="w", wraplength=700, font=("Microsoft YaHei", 9)).pack(fill="x", pady=(8, 0))

        card = self._card(page, "精修测试")
        self.var["refine_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["refine_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=700).pack(fill="x")
        self.refine_test_text = tk.Text(card, height=4, wrap="word", bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, padx=8, pady=6, font=("Microsoft YaHei", 10))
        self.refine_test_text.pack(fill="x", pady=(8, 6))
        ttk.Button(card, text="运行精修测试", command=self._test_refine).pack(anchor="w")
        self._note(card, "精修不阻塞录音与流式识别；模型不可用时自动回退到规则处理，并在界面显示状态。")

    def _tab_terms(self) -> None:
        page = self._page("专业词库")
        card = self._card(page, "术语与纠错")
        cols = ("wrong", "correct", "protected")
        self.term_tree = ttk.Treeview(card, columns=cols, show="headings", height=8)
        for col, title, width in (("wrong", "识别到的词", 200), ("correct", "正确写法", 200), ("protected", "受保护", 80)):
            self.term_tree.heading(col, text=title)
            self.term_tree.column(col, width=width, anchor="w")
        self.term_tree.pack(fill="x")
        self.term_tree.bind("<<TreeviewSelect>>", self._term_selected)

        form = tk.Frame(card, bg=_CARD)
        form.pack(fill="x", pady=(10, 0))
        self.var["term_wrong"] = tk.StringVar()
        self.var["term_correct"] = tk.StringVar()
        self.var["term_protected"] = tk.BooleanVar(value=False)
        ttk.Entry(form, textvariable=self.var["term_wrong"], width=20).pack(side="left", padx=(0, 6))
        tk.Label(form, text="→", bg=_CARD, fg=_MUTED).pack(side="left")
        ttk.Entry(form, textvariable=self.var["term_correct"], width=20).pack(side="left", padx=6)
        ttk.Checkbutton(form, text="受保护", variable=self.var["term_protected"]).pack(side="left", padx=6)
        ttk.Button(form, text="添加/更新", command=self._term_add).pack(side="left")
        ttk.Button(form, text="删除", command=self._term_delete).pack(side="left", padx=6)
        ttk.Button(form, text="导入 CSV", command=self._term_import).pack(side="left")
        ttk.Button(form, text="导出 CSV", command=self._term_export).pack(side="left", padx=6)
        self.var["term_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["term_status"], bg=_CARD, fg=_MUTED, anchor="w").pack(fill="x", pady=(6, 0))
        self._terms_refresh()

    def _tab_hotkeys(self) -> None:
        page = self._page("快捷键")
        card = self._card(page, "按键")
        self.var["hotkey"] = tk.StringVar()
        self._hotkey_row(card, "按住说话", self.var["hotkey"])
        self.var["hotkey_mode"] = tk.StringVar()
        box = self._row(card, "触发方式")
        ttk.Combobox(box, textvariable=self.var["hotkey_mode"], state="readonly", width=12, values=["hold", "toggle"]).pack(side="left")
        self.var["continuous"] = tk.StringVar()
        self._hotkey_row(card, "连续听写", self.var["continuous"])
        self.var["commit_key"] = tk.StringVar()
        self._hotkey_row(card, "提交/确认", self.var["commit_key"])
        self.var["undo_key"] = tk.StringVar()
        self._hotkey_row(card, "撤销上屏", self.var["undo_key"])
        self.var["cancel_key"] = tk.StringVar()
        self._hotkey_row(card, "取消输入", self.var["cancel_key"])
        self.var["hotkey_status"] = tk.StringVar(value="捕获按键后会做一次注册测试；热键在保存并重启后生效。")
        tk.Label(card, textvariable=self.var["hotkey_status"], bg=_CARD, fg=_MUTED, anchor="w", wraplength=700, justify="left").pack(fill="x", pady=(10, 0))
        self._note(card, "点「捕获按键」后直接按下目标键。热键在保存并重启后生效。")

    def _hotkey_row(self, card, label: str, var: tk.StringVar) -> None:
        row = self._row(card, label)
        ttk.Entry(row, textvariable=var, state="readonly", width=20).pack(side="left")
        btn = ttk.Button(row, text="捕获按键", width=9)
        btn.pack(side="left", padx=6)
        btn.configure(command=lambda v=var, b=btn: self._capture(v, b))

    def _tab_history(self) -> None:
        page = self._page("历史记录")
        card = self._card(page, "转录历史")
        self.var["history_enabled"] = tk.BooleanVar()
        ttk.Checkbutton(card, text="保存历史（仅本地数据库）", variable=self.var["history_enabled"]).pack(anchor="w")
        self.var["history_max"] = tk.StringVar()
        box = self._row(card, "最多保留条数")
        ttk.Spinbox(box, from_=50, to=5000, increment=50, textvariable=self.var["history_max"], width=8).pack(side="left")
        self.history_list = tk.Listbox(card, height=12, bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, font=("Microsoft YaHei", 9), selectbackground=_ACCENT, selectforeground="#ffffff", activestyle="none")
        self.history_list.pack(fill="both", expand=True, pady=(8, 6))
        bar = tk.Frame(card, bg=_CARD)
        bar.pack(fill="x")
        ttk.Button(bar, text="复制选中", command=self._history_copy).pack(side="left")
        ttk.Button(bar, text="刷新", command=self._history_refresh).pack(side="left", padx=6)
        ttk.Button(bar, text="清空历史", command=self._history_clear).pack(side="left")
        self.var["history_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["history_status"], bg=_CARD, fg=_MUTED, anchor="w").pack(fill="x", pady=(6, 0))
        self._history_refresh()

    def _tab_diagnostics(self) -> None:
        page = self._page("性能与诊断")
        card = self._card(page, "运行信息")
        self.diag_text = tk.Text(card, height=16, wrap="word", bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, padx=10, pady=8, font=("Consolas", 9))
        self.diag_text.pack(fill="both", expand=True)
        bar = tk.Frame(card, bg=_CARD)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="刷新", command=self._diag_refresh).pack(side="left")
        ttk.Button(bar, text="检查更新", command=self._check_update).pack(side="left", padx=6)
        ttk.Button(bar, text="加载测试", command=self._diag_load_test).pack(side="left", padx=6)
        ttk.Button(bar, text="校验模型", command=self._verify_models).pack(side="left")
        ttk.Button(bar, text="复制报告", command=self._diag_copy).pack(side="left", padx=6)
        ttk.Button(bar, text="打开数据目录", command=lambda: os.startfile(str(paths.data_root()))).pack(side="left")
        ttk.Button(bar, text="打开日志", command=lambda: os.startfile(str(paths.logs_dir()))).pack(side="left", padx=6)
        self.var["diag_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["diag_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=700).pack(fill="x", pady=(6, 0))
        self._diag_refresh()

    # ------------------------------------------------------------------ #
    def _fill(self) -> None:
        cfg = self.cfg
        self.var["mode"].set({"fast": "极速输入", "smart": "智能精修", "auto": "自动"}.get(cfg.get("mode", "auto"), "自动"))
        self.var["autostart"].set(autostart.is_enabled())
        ui = cfg.get("ui", {})
        self.var["theme"].set(ui.get("theme", "dark"))
        self.var["overlay"].set(ui.get("overlay", "show"))
        self.var["width"].set(str(ui.get("width", 720)))
        self.var["font_size"].set(str(ui.get("font_size", 14)))
        self.var["device"].set(self._device_label(cfg.get("audio", {}).get("device")))
        audio = cfg.get("audio", {})
        vad = audio.get("vad", {})
        self.var["endpoint_ms"].set(str(int(vad.get("endpoint_ms", 650))))
        self.var["min_segment"].set(str(vad.get("min_segment_s", 0.4)))
        self.var["max_segment"].set(str(vad.get("max_segment_s", 20.0)))
        self.var["silence_timeout"].set(str(audio.get("silence_timeout", 30.0)))
        self.var["threads"].set(str(cfg.get("streaming", {}).get("threads", 4)))
        review = cfg.get("review", {})
        self.var["review_enabled"].set(bool(review.get("enabled", True)))
        self.var["review_mode"].set(str(review.get("mode", "auto")))
        self.var["review_min"].set(str(review.get("min_segment_s", 2.5)))
        self.var["review_timeout"].set(str(review.get("timeout_s", 2.0)))
        refine = cfg.get("refine", {})
        self.var["refine_enabled"].set(bool(refine.get("enabled", True)))
        self.var["refine_level"].set(str(refine.get("level", "standard")))
        self.var["preload"].set(bool(refine.get("preload", True)))
        self.var["refine_threads"].set(str(refine.get("threads", 0)))
        self.var["refine_timeout"].set(str(refine.get("timeout_s", 12.0)))
        self.var["idle_unload"].set(str(refine.get("idle_unload_s", 900)))
        hist = cfg.get("history", {})
        self.var["history_enabled"].set(bool(hist.get("enabled", True)))
        self.var["history_max"].set(str(hist.get("max", 500)))
        hot = cfg.get("hotkey", {})
        self.var["hotkey"].set(str(hot.get("key", "f9")))
        self.var["hotkey_mode"].set(str(hot.get("mode", "hold")))
        self.var["continuous"].set(str(hot.get("continuous", "")))
        self.var["commit_key"].set(str(hot.get("commit", "")))
        self.var["undo_key"].set(str(hot.get("undo", "")))
        self.var["cancel_key"].set(str(hot.get("cancel", "esc")))

    def _device_label(self, value: Any) -> str:
        for label, val in self._devices:
            if val == value:
                return label
        if value not in (None, ""):
            self._devices.append((f"{value}", value))
            return f"{value}"
        return self._devices[0][0]

    def _device_value(self) -> Any:
        label = self.var["device"].get()
        for lbl, val in self._devices:
            if lbl == label:
                return val
        return None

    # ------------------------------------------------------------------ #
    def _collect(self) -> dict[str, Any]:
        cfg = load_config(self.config_path)
        cfg["mode"] = {"极速输入": "fast", "智能精修": "smart", "自动": "auto"}.get(self.var["mode"].get(), "auto")
        ui = cfg.setdefault("ui", {})
        ui["theme"] = self.var["theme"].get()
        ui["overlay"] = self.var["overlay"].get()
        try:
            ui["width"] = max(420, min(1200, int(float(self.var["width"].get()))))
            ui["font_size"] = max(10, min(32, int(float(self.var["font_size"].get()))))
        except ValueError:
            pass
        audio = cfg.setdefault("audio", {})
        audio["device"] = self._device_value()
        vad = audio.setdefault("vad", {})
        for key, var in (("endpoint_ms", "endpoint_ms"), ("min_segment_s", "min_segment"), ("max_segment_s", "max_segment"), ("silence_timeout", "silence_timeout")):
            try:
                value = float(self.var[var].get())
                if key == "silence_timeout":
                    audio[key] = value
                else:
                    vad[key] = value
            except ValueError:
                pass
        cfg.setdefault("streaming", {})["threads"] = max(1, min(16, int(float(self.var["threads"].get() or 4))))
        review = cfg.setdefault("review", {})
        review["enabled"] = bool(self.var["review_enabled"].get())
        review["mode"] = self.var["review_mode"].get()
        try:
            review["min_segment_s"] = float(self.var["review_min"].get())
            review["timeout_s"] = float(self.var["review_timeout"].get())
        except ValueError:
            pass
        refine = cfg.setdefault("refine", {})
        refine["enabled"] = bool(self.var["refine_enabled"].get())
        refine["level"] = self.var["refine_level"].get()
        refine["preload"] = bool(self.var["preload"].get())
        try:
            refine["threads"] = int(float(self.var["refine_threads"].get() or 0))
            refine["timeout_s"] = float(self.var["refine_timeout"].get())
            refine["idle_unload_s"] = float(self.var["idle_unload"].get())
        except ValueError:
            pass
        hist = cfg.setdefault("history", {})
        hist["enabled"] = bool(self.var["history_enabled"].get())
        try:
            hist["max"] = int(float(self.var["history_max"].get()))
        except ValueError:
            pass
        hot = cfg.setdefault("hotkey", {})
        hot["key"] = self.var["hotkey"].get().strip() or "f9"
        hot["mode"] = self.var["hotkey_mode"].get() or "hold"
        hot["continuous"] = self.var["continuous"].get().strip()
        hot["commit"] = self.var["commit_key"].get().strip()
        hot["undo"] = self.var["undo_key"].get().strip()
        hot["cancel"] = self.var["cancel_key"].get().strip() or "esc"
        return cfg

    def _save(self, restart: bool = False) -> None:
        try:
            cfg = self._collect()
            save_config(cfg, self.config_path)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.var["footer_status"].set(f"已保存 {time.strftime('%H:%M:%S')}")
        if restart:
            self.exit_code = 42
            self.root.destroy()
        else:
            messagebox.showinfo("已保存", "设置已保存；热键、模型等需要重启程序后生效。")

    # ------------------------------------------------------------------ #
    def _capture(self, var: tk.StringVar, button: ttk.Button) -> None:
        button.configure(state="disabled", text="请按键…")

        def worker() -> None:
            name = None
            try:
                import keyboard

                event = keyboard.read_event(suppress=True)
                name = event.name
            except Exception:
                pass
            self.root.after(0, lambda: self._captured(var, button, name))

        threading.Thread(target=worker, daemon=True).start()

    def _captured(self, var: tk.StringVar, button: ttk.Button, name: str | None) -> None:
        button.configure(state="normal", text="捕获按键")
        if not name:
            self.var["hotkey_status"].set("没有捕获到按键，请重试")
            return
        var.set(name)
        if "hotkey_status" not in self.var:
            return
        try:
            import keyboard

            handler = keyboard.add_hotkey(name, lambda: None)
            keyboard.remove_hotkey(handler)
            self.var["hotkey_status"].set(f"已捕获 {name.upper()}，注册测试通过")
        except Exception as exc:
            self.var["hotkey_status"].set(f"已捕获 {name.upper()}，但可能被占用：{exc}")

    def _toggle_autostart(self) -> None:
        try:
            if self.var["autostart"].get():
                autostart.enable()
            else:
                autostart.disable()
        except Exception as exc:
            messagebox.showerror("开机自启", str(exc))
            self.var["autostart"].set(autostart.is_enabled())

    def _detect_mic(self) -> None:
        if not messagebox.askokcancel("自动检测", "将同时监听各麦克风 3 秒，请对着麦克风说话。"):
            return
        self.var["audio_status"].set("正在检测…")

        def worker() -> None:
            from .devices import detect_best_input_device

            result = detect_best_input_device(seconds=3.0)
            self.root.after(0, lambda: self._detected(result))

        threading.Thread(target=worker, daemon=True).start()

    def _detected(self, result) -> None:
        if not result:
            self.var["audio_status"].set("未检测到可用麦克风。")
            return
        idx, name, _levels = result
        self.var["device"].set(self._device_label(idx))
        self.var["audio_status"].set(f"已选择信号最强的麦克风：{name}")

    # ------------------------------------------------------------------ #
    def _test_mic(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.mic_test_btn.configure(state="disabled")
        self.var["mic_test_status"].set("录音 4 秒… 请说话")
        device = self._device_value()

        def worker() -> None:
            try:
                rec = Recorder(device=device, max_duration=5.0)
                rec.start()
                time.sleep(4.0)
                data = rec.stop()
                if data is None or len(data) == 0:
                    raise RuntimeError("没有录到声音")
                self.root.after(0, lambda: self.var["mic_test_status"].set("正在加载复核模型并识别…"))
                if self._reviewer is None:
                    from .engines import OfflineReviewer

                    self._reviewer = OfflineReviewer(load_config(self.config_path))
                text = self._reviewer.review(data, timeout=30.0) or ""
                self.root.after(0, lambda: self._mic_done(text, None))
            except Exception as exc:
                self.root.after(0, lambda: self._mic_done("", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _mic_done(self, text: str, error: str | None) -> None:
        self._busy = False
        self.mic_test_btn.configure(state="normal")
        if error:
            self.var["mic_test_status"].set(f"测试失败：{error}")
            return
        self.mic_test_text.delete("1.0", "end")
        self.mic_test_text.insert("1.0", text or "（未识别到内容）")
        self.var["mic_test_status"].set("识别完成" if text else "未识别到内容")

    def _test_refine(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.var["refine_status"].set("正在加载本地 LLM…（首次约 10 秒）")

        def worker() -> None:
            from .llm import LlamaServer, Refiner

            try:
                cfg = load_config(self.config_path)
                if self._llm_server is None:
                    self._llm_server = LlamaServer(cfg)
                self._llm_server.start()
                refiner = Refiner(cfg, self._llm_server)
                text = "嗯那个我们今天呢主要是讨论一下 agent memory 的设计方案。"
                out = refiner.refine(segment_id="settings_test", source_revision=1, text=text, context=[], level="standard")
                self.root.after(0, lambda: self._refine_done(out, None))
            except Exception as exc:
                self.root.after(0, lambda: self._refine_done(None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _refine_done(self, out, error: str | None) -> None:
        self._busy = False
        if error:
            self.var["refine_status"].set(f"精修测试失败：{error}")
            return
        self.refine_test_text.delete("1.0", "end")
        self.refine_test_text.insert("1.0", out.text if out and out.ok else f"失败：{out.error if out else ''}")
        self.var["refine_status"].set(f"完成 · {out.latency_ms:.0f} ms" if out and out.ok else "精修失败，已回退")

    # ------------------------------------------------------------------ #
    def _terms_refresh(self) -> None:
        for item in self.term_tree.get_children():
            self.term_tree.delete(item)
        for row in self.storage.list_terms():
            self.term_tree.insert("", "end", iid=str(row["id"]), values=(row["wrong"], row["correct"], "是" if row["protected"] else ""))
        self.var["term_status"].set(f"共 {len(self.storage.list_terms())} 条")

    def _term_selected(self, _event=None) -> None:
        selection = self.term_tree.selection()
        if not selection:
            return
        values = self.term_tree.item(selection[0], "values")
        self.var["term_wrong"].set(values[0])
        self.var["term_correct"].set(values[1])
        self.var["term_protected"].set(values[2] == "是")

    def _term_add(self) -> None:
        wrong = self.var["term_wrong"].get().strip()
        correct = self.var["term_correct"].get().strip()
        if not wrong or not correct:
            self.var["term_status"].set("请填写识别词与正确写法")
            return
        self.storage.upsert_term(wrong, correct, protected=bool(self.var["term_protected"].get()))
        self._terms_refresh()

    def _term_delete(self) -> None:
        selection = self.term_tree.selection()
        if not selection:
            return
        for item in selection:
            self.storage.delete_term(int(item))
        self._terms_refresh()

    def _term_import(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0].strip():
                        self.storage.upsert_term(row[0], row[1], protected=len(row) > 2 and row[2].strip() in ("1", "true", "是"))
            self._terms_refresh()
            self.var["term_status"].set("导入完成")
        except Exception as exc:
            self.var["term_status"].set(f"导入失败：{exc}")

    def _term_export(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                for row in self.storage.list_terms():
                    writer.writerow([row["wrong"], row["correct"], "1" if row["protected"] else "0"])
            self.var["term_status"].set("导出完成")
        except Exception as exc:
            self.var["term_status"].set(f"导出失败：{exc}")

    # ------------------------------------------------------------------ #
    def _history_refresh(self) -> None:
        items = self.storage.list_history(300)
        self.history_list.delete(0, "end")
        for item in items:
            text = str(item.get("final_text", "")).replace("\n", " ")
            self.history_list.insert("end", f"{item.get('ts', '')}  {text[:80]}")
        self.var["history_status"].set(f"共 {len(items)} 条")

    def _history_copy(self) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        items = self.storage.list_history(300)
        text = items[selection[0]].get("final_text", "")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.var["history_status"].set("已复制")

    def _history_clear(self) -> None:
        if messagebox.askyesno("清空历史", "确定删除全部历史记录？此操作不可恢复。"):
            self.storage.clear_history()
            self._history_refresh()

    # ------------------------------------------------------------------ #
    def _diag_refresh(self) -> None:
        try:
            report = collect(load_config(self.config_path), load_test=False)
            self.diag_text.delete("1.0", "end")
            self.diag_text.insert("1.0", format_text(report))
            self.var["diag_status"].set("已刷新")
        except Exception as exc:
            self.var["diag_status"].set(f"诊断失败：{exc}")

    def _diag_load_test(self) -> None:
        self.var["diag_status"].set("正在加载全部模型（约 20 秒）…")

        def worker() -> None:
            try:
                report = collect(load_config(self.config_path), load_test=True)
                self.root.after(0, lambda: self._diag_loaded(report))
            except Exception as exc:
                self.root.after(0, lambda: self.var["diag_status"].set(f"加载测试失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _diag_loaded(self, report) -> None:
        self.diag_text.delete("1.0", "end")
        self.diag_text.insert("1.0", format_text(report))
        self.var["diag_status"].set("加载测试完成")

    def _diag_copy(self) -> None:
        text = self.diag_text.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.var["diag_status"].set("报告已复制")

    def _check_update(self) -> None:
        from . import update as update_mod

        self.var["diag_status"].set("正在检查更新…")

        def worker() -> None:
            source = str((load_config(self.config_path).get("update", {}) or {}).get("manifest_url", "") or "")
            result = update_mod.check_for_update(source=source)
            self.root.after(0, lambda: self._update_checked(result, update_mod))

        threading.Thread(target=worker, daemon=True).start()

    def _update_checked(self, result, update_mod) -> None:
        self.var["diag_status"].set(result.message)
        if result.status == "available" and result.info:
            messagebox.showinfo(
                "发现新版本",
                f"{result.message}\n\n请在托盘菜单选择「检查更新…」下载并安装；\n或前往：\n{result.info.release_notes_url}",
            )
        elif result.status == "model_mismatch" and result.info and result.info.full_installer_url:
            if messagebox.askyesno("需要完整安装包", result.message + "\n\n是否打开下载页面？"):
                import webbrowser

                webbrowser.open(result.info.full_installer_url)

    def _verify_models(self) -> None:
        self.var["asr_status"].set("正在校验模型文件（SHA-256）…")

        def worker() -> None:
            results = modelstore.verify_manifest()
            bad = [r for r in results if not r["ok"]]
            self.root.after(0, lambda: self._verify_done(results, bad))

        threading.Thread(target=worker, daemon=True).start()

    def _verify_done(self, results, bad) -> None:
        message = f"校验 {len(results)} 个文件，" + ("全部通过" if not bad else f"{len(bad)} 个异常")
        self.var["asr_status"].set(message)
        self.var["diag_status"].set(message)
        if bad:
            messagebox.showwarning("模型校验", "\n".join(f"{r['name']}: {r['path']}" for r in bad[:5]))


def main(config_path: str | None = None) -> int:
    cfg = load_config(config_path)
    root = tk.Tk()
    app = SettingsApp(root, cfg, config_path)
    root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
