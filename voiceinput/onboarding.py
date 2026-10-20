"""首次使用引导：麦克风 → 热键 → 试听测试 → 默认模式。可跳过，可从设置重开。"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from . import paths
from .audio import Recorder, TARGET_SR, list_input_devices
from .config import load_config, save_config
from .storage import Storage

_BG = "#f6f6f7"
_CARD = "#ffffff"
_FG = "#1c1d20"
_MUTED = "#71727a"
_ACCENT = "#2563eb"


class Onboarding:
    def __init__(self, root: tk.Tk, cfg: dict[str, Any], config_path: str | None = None) -> None:
        self.root = root
        self.cfg = cfg
        self.config_path = config_path
        self.storage = Storage()
        self.step = 0
        self.devices = list_input_devices()
        self.test_audio = None
        self.test_engine = None
        self._busy = False
        self.exit_code = 0

        root.title("欢迎使用本地语音输入")
        root.geometry("640x500")
        root.minsize(600, 460)
        root.configure(bg=_BG)
        try:
            root.attributes("-topmost", True)
            root.after(1200, lambda: root.attributes("-topmost", False))
        except Exception:
            pass
        root.lift()
        root.focus_force()
        self._style()
        self.container = tk.Frame(root, bg=_BG, padx=28, pady=22)
        self.container.pack(fill="both", expand=True)
        self._render()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=_BG, foreground=_FG, font=("Microsoft YaHei", 10))
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", background=_ACCENT, foreground="#ffffff", padding=(14, 7))
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("TCombobox", padding=5)

    # ------------------------------------------------------------------ #
    def _clear(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def _title(self, text: str, subtitle: str = "") -> None:
        tk.Label(self.container, text=text, bg=_BG, fg=_FG, font=("Microsoft YaHei", 18, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(self.container, text=subtitle, bg=_BG, fg=_MUTED, justify="left", anchor="w", wraplength=560).pack(fill="x", pady=(6, 14))
        else:
            tk.Frame(self.container, bg=_BG, height=14).pack(fill="x")

    def _card(self) -> tk.Frame:
        frame = tk.Frame(self.container, bg=_CARD, padx=18, pady=16, highlightthickness=1, highlightbackground="#e4e4e7")
        frame.pack(fill="both", expand=True)
        return frame

    def _nav(self, back: bool = True, next_text: str = "下一步", next_cmd=None, skip: bool = True) -> None:
        bar = tk.Frame(self.container, bg=_BG)
        bar.pack(fill="x", pady=(14, 0))
        if skip:
            ttk.Button(bar, text="跳过引导", command=self._skip).pack(side="left")
        ttk.Button(bar, text=next_text, style="Accent.TButton", command=next_cmd or self._next).pack(side="right")
        if back and self.step > 0:
            ttk.Button(bar, text="上一步", command=self._back).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------ #
    def _render(self) -> None:
        self._clear()
        if self.step == 0:
            self._step_welcome()
        elif self.step == 1:
            self._step_mic()
        elif self.step == 2:
            self._step_hotkey()
        elif self.step == 3:
            self._step_test()
        elif self.step == 4:
            self._step_mode()

    def _step_welcome(self) -> None:
        self._title("本地语音输入", "全部语音识别与文本精修都在本机完成，不联网、不上传录音。")
        card = self._card()
        for text in (
            "1. 选择一个麦克风",
            "2. 设置你的快捷键",
            "3. 试一段语音，确认识别效果",
            "4. 选择默认输入模式",
        ):
            tk.Label(card, text=text, bg=_CARD, fg=_FG, font=("Microsoft YaHei", 11), anchor="w").pack(fill="x", pady=4)
        tk.Label(
            card, text=f"程序版本 {paths.VERSION}\n数据目录：{paths.data_root()}",
            bg=_CARD, fg=_MUTED, justify="left", anchor="w", font=("Microsoft YaHei", 9), wraplength=520,
        ).pack(fill="x", pady=(14, 0))
        self._nav(back=False, next_text="开始")

    def _step_mic(self) -> None:
        self._title("选择麦克风", "程序使用 Windows 共享模式录音，不会改变系统默认设备或音量。")
        card = self._card()
        row = tk.Frame(card, bg=_CARD)
        row.pack(fill="x")
        tk.Label(row, text="输入设备", bg=_CARD, fg=_FG, width=10, anchor="w").pack(side="left")
        names = [f"{d['id']}: {d['name']}" for d in self.devices] or ["（未检测到麦克风）"]
        self.mic_var = tk.StringVar(value=names[0])
        combo = ttk.Combobox(row, textvariable=self.mic_var, values=names, state="readonly", width=42)
        combo.pack(side="left", fill="x", expand=True)
        self.mic_status = tk.StringVar(value="点击「检查麦克风」，对着麦克风说一句话。")
        tk.Label(card, textvariable=self.mic_status, bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=520).pack(fill="x", pady=(14, 6))
        ttk.Button(card, text="检查麦克风", command=self._check_mic).pack(anchor="w")
        self._nav(next_text="下一步")

    def _device_id(self) -> int | None:
        text = self.mic_var.get()
        try:
            return int(text.split(":", 1)[0])
        except Exception:
            return None

    def _check_mic(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.mic_status.set("正在检查… 请说话（2 秒）")
        device = self._device_id()

        def worker() -> None:
            try:
                rec = Recorder(device=device, max_duration=2.5)
                rec.start()
                time.sleep(2.0)
                data = rec.stop()
            except Exception as exc:
                self.root.after(0, lambda: self._mic_done(None, f"无法打开麦克风：{exc}\n请在 Windows 设置 → 隐私和安全性 → 麦克风中允许桌面应用访问。"))
                return
            self.root.after(0, lambda: self._mic_done(data, None))

        threading.Thread(target=worker, daemon=True).start()

    def _mic_done(self, data, error: str | None) -> None:
        self._busy = False
        if error:
            self.mic_status.set(error)
            return
        if data is None or len(data) == 0:
            self.mic_status.set("没有录到音频。请检查麦克风是否被其他程序占用。")
            return
        import numpy as np

        rms = float(np.sqrt(np.mean(np.asarray(data, dtype=np.float64) ** 2)))
        db = 20 * np.log10(rms + 1e-12)
        if db > -45:
            self.mic_status.set(f"检测到声音（{db:.0f} dB），麦克风工作正常。")
        else:
            self.mic_status.set(f"麦克风已打开，但几乎没有声音（{db:.0f} dB）。请靠近麦克风或检查系统输入音量。")

    def _step_hotkey(self) -> None:
        self._title("设置快捷键", "按住说话、松开结束。推荐使用 F9 或右侧 Ctrl，避免与常用软件冲突。")
        card = self._card()
        self.hotkey_var = tk.StringVar(value=str(self.cfg.get("hotkey", {}).get("key", "f9")))
        row = tk.Frame(card, bg=_CARD)
        row.pack(fill="x")
        tk.Label(row, text="按住说话", bg=_CARD, fg=_FG, width=10, anchor="w").pack(side="left")
        ttk.Entry(row, textvariable=self.hotkey_var, state="readonly", width=18).pack(side="left")
        ttk.Button(row, text="捕获按键", command=self._capture_hotkey).pack(side="left", padx=8)
        tk.Label(card, text="提示：点「捕获按键」后直接按下你想要的键。", bg=_CARD, fg=_MUTED, anchor="w").pack(fill="x", pady=(14, 0))
        self._nav(next_text="下一步")

    def _capture_hotkey(self) -> None:
        if self._busy:
            return
        self._busy = True

        def worker() -> None:
            name = None
            try:
                import keyboard

                name = keyboard.read_event(suppress=True).name
            except Exception:
                pass
            self.root.after(0, lambda: self._hotkey_done(name))

        threading.Thread(target=worker, daemon=True).start()

    def _hotkey_done(self, name: str | None) -> None:
        self._busy = False
        if name:
            self.hotkey_var.set(name)

    def _step_test(self) -> None:
        self._title("试一段语音", "录制 3 秒并调用本机模型识别。首次加载模型可能需要几秒。")
        card = self._card()
        self.test_status = tk.StringVar(value="点击「开始测试」，然后说一句话。")
        tk.Label(card, textvariable=self.test_status, bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=520).pack(fill="x")
        self.test_text = tk.Text(card, height=5, wrap="word", bd=0, highlightthickness=1, highlightbackground="#e4e4e7", bg="#fbfbfc", fg=_FG, padx=10, pady=8, font=("Microsoft YaHei", 10))
        self.test_text.pack(fill="both", expand=True, pady=(10, 8))
        ttk.Button(card, text="开始测试（3 秒）", command=self._run_test).pack(anchor="w")
        self._nav(next_text="下一步")

    def _run_test(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.test_status.set("录音中… 请说话")
        device = self._device_id()

        def worker() -> None:
            try:
                rec = Recorder(device=device, max_duration=3.5)
                rec.start()
                time.sleep(3.0)
                data = rec.stop()
                if data is None or len(data) == 0:
                    raise RuntimeError("没有录到声音")
                self.root.after(0, lambda: self.test_status.set("正在加载模型并识别…"))
                from .engines import OfflineReviewer

                if self.test_engine is None:
                    self.test_engine = OfflineReviewer(self.cfg)
                text = self.test_engine.review(data, timeout=30.0) or ""
                self.root.after(0, lambda: self._test_done(text, None))
            except Exception as exc:
                self.root.after(0, lambda: self._test_done("", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _test_done(self, text: str, error: str | None) -> None:
        self._busy = False
        if error:
            self.test_status.set(f"测试失败：{error}\n可先跳过，安装完成后再在设置中测试。")
            return
        self.test_text.delete("1.0", "end")
        self.test_text.insert("1.0", text or "（未识别到内容）")
        self.test_status.set("识别完成" if text else "未识别到内容，请检查麦克风或说话音量。")

    def _step_mode(self) -> None:
        self._title("默认输入模式", "之后可以随时在托盘或设置中切换。")
        card = self._card()
        self.mode_var = tk.StringVar(value=str(self.cfg.get("mode", "auto")))
        for value, label, desc in (
            ("fast", "极速输入", "说完立刻插入，不调用大模型；适合聊天、搜索、短文本。"),
            ("smart", "智能精修", "在面板中对照原文与精修结果，确认后插入；适合长口述。"),
            ("auto", "自动", "短句极速插入；长时间输入自动转为精修确认，不自动改写风格。"),
        ):
            row = tk.Frame(card, bg=_CARD)
            row.pack(fill="x", pady=6)
            tk.Radiobutton(row, text=label, variable=self.mode_var, value=value, bg=_CARD, fg=_FG, activebackground=_CARD, selectcolor=_CARD, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w")
            tk.Label(row, text=desc, bg=_CARD, fg=_MUTED, anchor="w", justify="left", wraplength=500, font=("Microsoft YaHei", 9)).pack(fill="x", padx=(24, 0))
        self._nav(next_text="完成", next_cmd=self._finish)

    def _save(self) -> None:
        hot = self.cfg.setdefault("hotkey", {})
        if hasattr(self, "hotkey_var") and self.hotkey_var.get().strip():
            hot["key"] = self.hotkey_var.get().strip()
        if hasattr(self, "mic_var"):
            device = self._device_id()
            if device is not None:
                self.cfg.setdefault("audio", {})["device"] = device
        if hasattr(self, "mode_var"):
            self.cfg["mode"] = self.mode_var.get()
        save_config(self.cfg, self.config_path)
        self.storage.mark_onboarded(True)

    def _next(self) -> None:
        if self.step == 3:
            self._save()
        self.step = min(4, self.step + 1)
        self._render()

    def _back(self) -> None:
        self.step = max(0, self.step - 1)
        self._render()

    def _finish(self) -> None:
        self._save()
        if self.test_engine is not None:
            try:
                self.test_engine.close()
            except Exception:
                pass
        self.exit_code = 42
        self.root.destroy()

    def _skip(self) -> None:
        self.storage.mark_onboarded(True)
        self.exit_code = 42
        self.root.destroy()


def main(config_path: str | None = None) -> int:
    cfg = load_config(config_path)
    root = tk.Tk()
    window = Onboarding(root, cfg, config_path)
    root.mainloop()
    return window.exit_code


if __name__ == "__main__":
    sys.exit(main())
