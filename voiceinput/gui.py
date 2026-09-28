"""图形化配置界面（tkinter，无第三方依赖）。

设计目标：干净、安静、分区清晰的单页式设置（不分顶部页签）；只暴露最常用的几项，
其余参数使用内置最佳默认值。整体配色参考 Claude 的暖色调。

用法：
    python -m voiceinput.gui      # 单独打开
    voiceinput.exe --settings     # 打包版
"""

from __future__ import annotations

import copy
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from . import autostart
from .config import (
    DEFAULT_CONFIG_PATH,
    SETTINGS_RESTART_EXIT,
    load_config,
    resolve_model_dir,
    save_config,
)

# ---- 配色（Claude 风格：暖白背景 + 陶土色强调） ----
_BG = "#f5f4ef"
_CARD = "#ffffff"
_BORDER = "#e7e5dd"
_FG = "#1f1e1c"
_MUTED = "#8a857a"
_ACCENT = "#c96442"
_ACCENT_HOVER = "#b8573a"


def _input_devices() -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = [("（系统默认）", None)]
    try:
        import sounddevice as sd

        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                items.append((f"{idx}: {dev['name']}", idx))
    except Exception:
        pass
    return items


class SettingsWindow:
    def __init__(self, root: tk.Tk, cfg: dict[str, Any]) -> None:
        self.root = root
        self.exit_code = 0
        self._devices = _input_devices()
        self.var: dict[str, tk.Variable] = {}
        self._test_engine = None
        self._test_sig = None
        self._test_audio = None
        self._test_recording = False
        self._test_playing = False

        root.title("voiceinput 设置")
        root.configure(bg=_BG)
        root.geometry("720x660")
        root.minsize(660, 560)
        try:
            root.iconbitmap(default=str(resolve_model_dir(cfg).parent / "voiceinput.ico"))
        except Exception:
            pass

        self._apply_theme()
        self._build()
        self._fill(cfg)

    # ------------------------------------------------------------------ #
    # 主题
    # ------------------------------------------------------------------ #
    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        base_font = ("Microsoft YaHei", 10)
        style.configure(".", background=_BG, foreground=_FG, font=base_font)
        style.configure("TFrame", background=_BG)
        style.configure("Card.TFrame", background=_CARD)
        style.configure("TLabel", background=_BG, foreground=_FG)
        style.configure("Card.TLabel", background=_CARD, foreground=_FG)
        style.configure("Muted.TLabel", background=_CARD, foreground=_MUTED)
        style.configure("Title.TLabel", background=_BG, foreground=_FG, font=("Microsoft YaHei", 17, "bold"))
        style.configure("Sub.TLabel", background=_BG, foreground=_MUTED, font=("Microsoft YaHei", 9))
        style.configure("Section.TLabel", background=_CARD, foreground=_FG, font=("Microsoft YaHei", 11, "bold"))
        style.configure(
            "TEntry",
            fieldbackground="#ffffff", background="#ffffff", foreground=_FG,
            bordercolor=_BORDER, lightcolor=_BORDER, darkcolor=_BORDER, insertcolor=_FG, padding=6,
        )
        style.configure(
            "TCombobox",
            fieldbackground="#ffffff", background="#ffffff", foreground=_FG,
            bordercolor=_BORDER, lightcolor=_BORDER, darkcolor=_BORDER, arrowcolor=_MUTED, padding=4,
        )
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")], foreground=[("readonly", _FG)])
        style.configure("TSpinbox", fieldbackground="#ffffff", background="#ffffff", foreground=_FG, bordercolor=_BORDER, arrowcolor=_MUTED, padding=4)
        style.configure("TButton", background="#fbfbf9", foreground=_FG, bordercolor=_BORDER, focusthickness=0, padding=(12, 6))
        style.map("TButton", background=[("active", "#f0eee7")])
        style.configure("Accent.TButton", background=_ACCENT, foreground="#ffffff", bordercolor=_ACCENT, focusthickness=0, padding=(14, 7))
        style.map("Accent.TButton", background=[("active", _ACCENT_HOVER)])
        style.configure("TCheckbutton", background=_CARD, foreground=_FG)
        style.map("TCheckbutton", background=[("active", _CARD)], foreground=[("active", _FG)])
        style.configure("Vertical.TScrollbar", background="#e3e1d9", troughcolor=_BG, bordercolor=_BG, arrowcolor=_MUTED)
        self.root.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.foreground", _FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", _ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", base_font)

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(16, 8))
        ttk.Label(header, text="voiceinput", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="离线语音输入法 · 设置", style="Sub.TLabel").pack(anchor="w")

        inner = self._scroll_area()

        self._build_shortcuts(inner)
        self._build_microphone(inner)
        self._build_general(inner)
        self._build_test(inner)
        self._build_history(inner)
        self._build_about(inner)

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=20, pady=(4, 14))
        ttk.Button(bar, text="保存并重启", style="Accent.TButton", command=self._save_restart).pack(side="right")
        ttk.Button(bar, text="保存", command=self._save).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="关闭", command=self.root.destroy).pack(side="left")

    def _scroll_area(self) -> ttk.Frame:
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 4))
        canvas = tk.Canvas(container, bg=_BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure("inner", width=e.width))

        def on_wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind_all("<MouseWheel>", on_wheel)
        return inner

    def _card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        outer = tk.Frame(parent, bg=_BORDER)
        outer.pack(fill="x", pady=(0, 12))
        card = tk.Frame(outer, bg=_CARD, padx=16, pady=14)
        card.pack(fill="x", padx=1, pady=1)
        if title:
            tk.Label(card, text=title, bg=_CARD, fg=_FG, font=("Microsoft YaHei", 11, "bold")).pack(anchor="w", pady=(0, 10))
        return card

    def _row(self, card: tk.Frame, label: str) -> tk.Frame:
        row = tk.Frame(card, bg=_CARD)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label, bg=_CARD, fg=_FG, width=16, anchor="w").pack(side="left")
        return row

    def _note(self, card: tk.Frame, text: str) -> None:
        tk.Label(card, text=text, bg=_CARD, fg=_MUTED, justify="left", anchor="w", wraplength=560).pack(
            fill="x", pady=(6, 0)
        )

    def _build_shortcuts(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "快捷键")
        self.var["hotkey"] = tk.StringVar()
        self._hotkey_row(self._row(card, "按住说话热键"), self.var["hotkey"])
        self.var["hotkey_continuous"] = tk.StringVar()
        self._hotkey_row(self._row(card, "连续听写热键"), self.var["hotkey_continuous"])
        self._note(card, "「按住说话」按住录音、松开上屏；「连续听写」按一下开始、再按一下停止。点「捕获按键」后直接按一下你想用的键。")

    def _build_microphone(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "麦克风")
        row = self._row(card, "输入设备")
        ttk.Combobox(
            row, textvariable=self.var.setdefault("device", tk.StringVar()),
            values=[d[0] for d in self._devices], state="readonly", width=34,
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="自动检测", width=10, command=self._auto_detect_mic).pack(side="left", padx=(8, 0))
        self.var["general_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["general_status"], bg=_CARD, fg=_ACCENT, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(8, 0))

    def _build_general(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "常规")
        self.var["autostart"] = tk.BooleanVar()
        ttk.Checkbutton(
            card, text="开机自动启动", variable=self.var["autostart"], command=self._toggle_autostart
        ).pack(anchor="w")

    def _build_test(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "麦克风测试")
        row = self._row(card, "录音时长（秒）")
        self.var["test_seconds"] = tk.StringVar(value="5")
        ttk.Spinbox(row, from_=1, to=30, textvariable=self.var["test_seconds"], width=6).pack(side="left")

        btns = tk.Frame(card, bg=_CARD)
        btns.pack(fill="x", pady=(8, 4))
        self._test_btn = ttk.Button(btns, text="开始录音", command=self._test_toggle)
        self._test_btn.pack(side="left")
        ttk.Button(btns, text="试听", command=self._test_play).pack(side="left", padx=8)
        ttk.Button(btns, text="清空", command=lambda: self._test_text.delete("1.0", "end")).pack(side="left")

        self.var["test_status"] = tk.StringVar(value="点「开始录音」后对着麦克风说话。")
        tk.Label(card, textvariable=self.var["test_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(2, 6))
        self._test_text = tk.Text(card, height=4, wrap="word", bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, padx=8, pady=6, font=("Microsoft YaHei", 10))
        self._test_text.pack(fill="x")

    def _build_history(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "历史")
        self._history_items: list[dict] = []
        self._history_list = tk.Listbox(card, height=6, bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_FG, activestyle="none", font=("Microsoft YaHei", 10), selectbackground=_ACCENT, selectforeground="#ffffff")
        self._history_list.pack(fill="x")
        btns = tk.Frame(card, bg=_CARD)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="复制选中", command=self._history_copy).pack(side="left")
        ttk.Button(btns, text="刷新", command=self._history_refresh).pack(side="left", padx=8)
        ttk.Button(btns, text="清空", command=self._history_clear).pack(side="left")
        self.var["history_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["history_status"], bg=_CARD, fg=_MUTED, anchor="w").pack(fill="x", pady=(6, 0))
        self._history_refresh()

    def _build_about(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "关于")
        self._about_text = tk.Text(card, height=7, wrap="word", bd=0, highlightthickness=1, highlightbackground=_BORDER, bg="#fbfbf9", fg=_MUTED, padx=8, pady=6, font=("Microsoft YaHei", 9))
        self._about_text.insert("1.0", self._about_info())
        self._about_text.config(state="disabled")
        self._about_text.pack(fill="x")
        btns = tk.Frame(card, bg=_CARD)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="检查更新", command=self._check_update).pack(side="left")
        ttk.Button(btns, text="复制信息", command=self._copy_about).pack(side="left", padx=8)
        self.var["about_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["about_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(6, 0))

        model_row = self._row(card, "模型")
        self.var["model_choice"] = tk.StringVar(value=str(load_config().get("engine", "sensevoice")))
        ttk.Combobox(model_row, textvariable=self.var["model_choice"], values=["sensevoice", "paraformer"], state="readonly", width=14).pack(side="left")
        ttk.Button(model_row, text="下载并切换", command=self._download_switch_model).pack(side="left", padx=8)
        self.var["model_status"] = tk.StringVar(value="")
        tk.Label(card, textvariable=self.var["model_status"], bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(6, 0))

    def _hotkey_row(self, row: tk.Frame, var: tk.StringVar) -> None:
        holder = tk.Frame(row, bg=_CARD)
        holder.pack(side="left", fill="x", expand=True)
        ttk.Entry(holder, textvariable=var, state="readonly").pack(side="left", fill="x", expand=True)
        button = ttk.Button(holder, text="捕获按键", width=10)
        button.pack(side="left", padx=(8, 0))
        button.config(command=lambda: self._capture_key(var, button))

    # ------------------------------------------------------------------ #
    # 取值 / 赋值
    # ------------------------------------------------------------------ #
    def _device_label(self, value: Any) -> str:
        for label, val in self._devices:
            if val == value:
                return label
        if value not in (None, ""):
            self._devices.append((str(value), value))
            return str(value)
        return self._devices[0][0]

    def _device_value(self) -> Any:
        label = self.var["device"].get()
        for lbl, val in self._devices:
            if lbl == label:
                return val
        return None

    def _fill(self, cfg: dict[str, Any]) -> None:
        self.var["hotkey"].set(str(cfg["hotkey"]["key"]))
        self.var["hotkey_continuous"].set(str(cfg["hotkey"].get("continuous", "")))
        self.var["device"].set(self._device_label(cfg["audio"]["device"]))
        self.var["autostart"].set(autostart.is_enabled())

    def _collect(self, base: dict[str, Any]) -> dict[str, Any]:
        """只覆盖界面上呈现的项，其余保持原样（即最佳默认值）。"""
        cfg = copy.deepcopy(base)
        hotkey = cfg.setdefault("hotkey", {})
        hotkey["key"] = self.var["hotkey"].get().strip() or "f9"
        hotkey["continuous"] = self.var["hotkey_continuous"].get().strip()
        cfg.setdefault("audio", {})["device"] = self._device_value()
        return cfg

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def _capture_key(self, var: tk.StringVar, button: ttk.Button) -> None:
        button.config(state="disabled", text="请按键…")

        def worker() -> None:
            name = None
            try:
                import keyboard

                name = keyboard.read_event(suppress=True).name
            except Exception:
                pass
            self.root.after(0, lambda: self._on_captured(var, button, name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_captured(self, var: tk.StringVar, button: ttk.Button, name: str | None) -> None:
        button.config(state="normal", text="捕获按键")
        if name:
            var.set(name)

    def _auto_detect_mic(self) -> None:
        if not messagebox.askokcancel(
            "voiceinput", "将同时监听各个麦克风，请在这几秒内对着麦克风连续说几句话。\n\n开始检测？"
        ):
            return
        self.var["general_status"].set("正在检测麦克风… 请说话")

        def worker() -> None:
            from .devices import detect_best_input_device

            try:
                result = detect_best_input_device(seconds=3.0)
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.var["general_status"].set(f"检测失败：{exc}"))
                return
            self.root.after(0, lambda: self._apply_detected(result))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_detected(self, result) -> None:
        if not result:
            self.var["general_status"].set("未检测到可用麦克风。")
            return
        idx, name, _levels = result
        self.var["device"].set(self._device_label(idx))
        self.var["general_status"].set(f"已选择信号最强的麦克风：{name}")

    def _history_refresh(self) -> None:
        from .history import load

        self._history_items = load(limit=300)
        self._history_list.delete(0, "end")
        for item in self._history_items:
            text = str(item.get("text", "")).replace("\n", " ")
            self._history_list.insert("end", f"{item.get('time', '')}  {text}")
        self.var["history_status"].set(f"共 {len(self._history_items)} 条")

    def _history_copy(self) -> None:
        selection = self._history_list.curselection()
        if not selection:
            self.var["history_status"].set("请先选中一条记录。")
            return
        text = str(self._history_items[selection[0]].get("text", ""))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.var["history_status"].set("已复制选中内容到剪贴板。")

    def _history_clear(self) -> None:
        if messagebox.askyesno("voiceinput", "清空全部历史记录？"):
            from .history import clear

            clear()
            self._history_refresh()

    def _toggle_autostart(self) -> None:
        try:
            if self.var["autostart"].get():
                autostart.enable()
            else:
                autostart.disable()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("voiceinput", f"设置开机自启失败：{exc}")
            self.var["autostart"].set(autostart.is_enabled())

    def _save(self) -> dict[str, Any] | None:
        cfg = self._collect(load_config())
        try:
            path = save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("voiceinput", f"保存失败：{exc}")
            return None
        messagebox.showinfo("voiceinput", f"已保存，重启后生效：\n{path}")
        return cfg

    def _save_restart(self) -> None:
        cfg = self._collect(load_config())
        try:
            save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("voiceinput", f"保存失败：{exc}")
            return
        self.exit_code = SETTINGS_RESTART_EXIT
        self.root.destroy()

    # ------------------------------------------------------------------ #
    # 麦克风测试
    # ------------------------------------------------------------------ #
    def _test_toggle(self) -> None:
        if self._test_recording:
            self._test_recording = False
            self._test_btn.config(text="正在结束…", state="disabled")
            return
        self._test_recording = True
        self._test_btn.config(text="停止录音")
        self.var["test_status"].set("录音中… 请对着麦克风说话")
        threading.Thread(target=self._test_record_worker, daemon=True).start()

    def _test_seconds(self) -> int:
        try:
            return max(1, int(float(self.var["test_seconds"].get())))
        except (TypeError, ValueError):
            return 5

    def _test_record_worker(self) -> None:
        from .recorder import Recorder

        seconds = self._test_seconds()
        try:
            rec = Recorder(device=self._device_value(), max_duration=seconds)
            rec.start()
            start = time.time()
            while self._test_recording and (time.time() - start) < seconds:
                time.sleep(0.05)
            data = rec.stop()
        except Exception as exc:  # noqa: BLE001
            self._test_recording = False
            self.root.after(0, lambda: self._test_fail(f"录音失败：{exc}"))
            return
        self._test_recording = False
        if data is None or data.size == 0:
            self.root.after(0, lambda: self._test_fail("没有录到声音，请检查麦克风。"))
            return
        self._test_audio = data
        self.root.after(0, lambda: self._test_transcribe(data))

    def _test_transcribe(self, data) -> None:
        self._test_btn.config(state="disabled", text="识别中…")
        self.var["test_status"].set("正在识别…（首次需加载模型，请稍候）")
        threading.Thread(target=self._test_transcribe_worker, args=(data,), daemon=True).start()

    def _test_transcribe_worker(self, data) -> None:
        from .recorder import TARGET_SR

        try:
            engine = self._get_test_engine()
            text = engine.transcribe(data, TARGET_SR)
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, lambda: self._test_fail(f"识别失败：{exc}"))
            return
        self.root.after(0, lambda: self._test_show(text))

    def _get_test_engine(self):
        from .engines import build_engine

        cfg = self._collect(load_config())
        signature = (cfg["engine"], str(resolve_model_dir(cfg)), cfg["threads"])
        if self._test_engine is not None and self._test_sig == signature:
            return self._test_engine
        engine = build_engine(cfg)
        self._test_engine, self._test_sig = engine, signature
        return engine

    def _test_show(self, text: str) -> None:
        self._test_btn.config(state="normal", text="开始录音")
        self._test_text.delete("1.0", "end")
        self._test_text.insert("1.0", text or "（未识别到内容）")
        self.var["test_status"].set("识别完成" if text else "未识别到内容")

    def _test_fail(self, message: str) -> None:
        self._test_recording = False
        self._test_btn.config(state="normal", text="开始录音")
        self.var["test_status"].set(message)

    def _test_play(self) -> None:
        if self._test_audio is None:
            self.var["test_status"].set("还没有录音可试听，请先录音。")
            return
        if self._test_playing:
            return
        self._test_playing = True
        self.var["test_status"].set("播放中…")

        def worker() -> None:
            from .recorder import TARGET_SR

            import sounddevice as sd

            try:
                sd.play(self._test_audio, TARGET_SR)
                sd.wait()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self._test_fail(f"播放失败：{exc}"))
                return
            self._test_playing = False
            self.root.after(0, lambda: self.var["test_status"].set("就绪"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # 关于 / 更新
    # ------------------------------------------------------------------ #
    def _about_info(self) -> str:
        import platform
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as pkg_version

        from . import __version__

        cfg = load_config()
        model_dir = resolve_model_dir(cfg)
        lines = [
            f"voiceinput {__version__}    Python {platform.python_version()} ({platform.architecture()[0]})",
            f"引擎 {cfg['engine']}    模型目录 {model_dir} [{'存在' if model_dir.exists() else '不存在'}]",
            f"配置文件 {DEFAULT_CONFIG_PATH}",
            "依赖：" + "  ".join(
                f"{p}={pkg_version(p)}"
                for p in ("sherpa-onnx", "sounddevice", "soxr", "faster-whisper")
                if _pkg_ok(p, pkg_version, PackageNotFoundError)
            ),
            "",
            "完全离线：识别全部在本机完成，不产生任何网络请求。",
        ]
        return "\n".join(lines)

    def _copy_about(self) -> None:
        text = self._about_text.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.var["about_status"].set("已复制到剪贴板。")

    def _check_update(self) -> None:
        self.var["about_status"].set("正在检查更新…")

        def worker() -> None:
            import json
            import urllib.request
            from importlib.metadata import PackageNotFoundError
            from importlib.metadata import version as pkg_version

            try:
                with urllib.request.urlopen(
                    "https://pypi.org/pypi/sherpa-onnx/json", timeout=8
                ) as resp:
                    latest = json.load(resp)["info"]["version"]
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.var["about_status"].set(f"无法检查更新（可能无网络）：{exc}"))
                return
            try:
                current = pkg_version("sherpa-onnx")
            except PackageNotFoundError:
                current = "未知"
            message = (
                f"sherpa-onnx 已是最新版本（{current}）。"
                if current == latest
                else f"sherpa-onnx 有新版本：{current} → {latest}\n更新命令：uv pip install -U sherpa-onnx"
            )
            self.root.after(0, lambda: self.var["about_status"].set(message))

        threading.Thread(target=worker, daemon=True).start()

    def _download_switch_model(self) -> None:
        engine = self.var["model_choice"].get()
        self.var["model_status"].set(f"开始下载 {engine} 模型…")

        def worker() -> None:
            from .download_models import download

            cfg = load_config()

            def progress(pct: float) -> None:
                self.root.after(0, lambda: self.var["model_status"].set(f"下载 {engine}：{pct * 100:.0f}%"))

            try:
                download(engine, resolve_model_dir(cfg), progress=progress)
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.var["model_status"].set(f"下载失败：{exc}"))
                return
            cfg["engine"] = engine
            try:
                save_config(cfg)
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.var["model_status"].set(f"保存失败：{exc}"))
                return
            self.root.after(0, lambda: self._after_model_switch(engine))

        threading.Thread(target=worker, daemon=True).start()

    def _after_model_switch(self, engine: str) -> None:
        self.var["model_status"].set(f"已下载并设为 {engine}。")
        if messagebox.askyesno("voiceinput", f"已切换为 {engine}，是否立即重启以生效？"):
            self.exit_code = SETTINGS_RESTART_EXIT
            self.root.destroy()


def _pkg_ok(name: str, version_fn, not_found) -> bool:
    try:
        version_fn(name)
        return True
    except not_found:
        return False


def main() -> int:
    cfg = load_config()
    root = tk.Tk()
    window = SettingsWindow(root, cfg)
    root.mainloop()
    return window.exit_code


if __name__ == "__main__":
    sys.exit(main())
