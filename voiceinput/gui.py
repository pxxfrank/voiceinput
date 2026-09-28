"""图形化配置界面（tkinter，无第三方依赖）。

本着「大多数人不该被配置项淹没」的原则，这里只暴露最常用的几项：
热键、麦克风、开机自启。其余参数一律使用内置最佳默认值、不在此呈现；
确有需要的高级用户可直接编辑 config.yaml。

用法：
    python -m voiceinput.gui      # 单独打开
    voiceinput.exe --settings     # 打包版
托盘菜单「设置…」也会打开本窗口；点「保存并重启」会通知主程序重启以应用新配置。
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


def _input_devices() -> list[tuple[str, Any]]:
    """返回 [(显示名, 配置值)]，第一项为系统默认设备。"""
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
        root.resizable(False, False)
        try:
            root.iconbitmap(default=str(resolve_model_dir(cfg).parent / "voiceinput.ico"))
        except Exception:
            pass

        self._build()
        self._fill(cfg)

    # ------------------------------------------------------------------ #
    # 构建界面
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        self._build_general(nb.add(ttk.Frame(nb), text=" 常规 "))
        self._build_test(nb.add(ttk.Frame(nb), text=" 麦克风测试 "))
        self._build_history(nb.add(ttk.Frame(nb), text=" 历史 "))
        self._build_about(nb.add(ttk.Frame(nb), text=" 关于 "))

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="保存并重启", command=self._save_restart).pack(side="right")
        ttk.Button(bottom, text="保存", command=self._save).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="关闭", command=self.root.destroy).pack(side="left")

    def _add_row(self, parent, row: int, label: str, widget: tk.Widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(12, 12), pady=6)
        widget.grid(row=row, column=1, sticky="ew", pady=6, padx=(0, 12))

    def _frame(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        return f

    def _build_general(self, tab: ttk.Frame) -> None:
        f = self._frame(tab)

        self.var["hotkey"] = tk.StringVar()
        self._add_row(f, 0, "按住说话热键", self._hotkey_row(f, self.var["hotkey"]))

        self.var["hotkey_continuous"] = tk.StringVar()
        self._add_row(f, 1, "连续听写热键", self._hotkey_row(f, self.var["hotkey_continuous"]))

        self.var["device"] = tk.StringVar()
        mic = ttk.Frame(f)
        mic.columnconfigure(0, weight=1)
        ttk.Combobox(
            mic, textvariable=self.var["device"], values=[d[0] for d in self._devices], state="readonly"
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(mic, text="自动检测", command=self._auto_detect_mic, width=10).grid(
            row=0, column=1, padx=(6, 0)
        )
        self._add_row(f, 2, "麦克风", mic)

        self.var["autostart"] = tk.BooleanVar()
        self._add_row(
            f, 3, "开机自启", ttk.Checkbutton(f, variable=self.var["autostart"], command=self._toggle_autostart)
        )

        self.var["general_status"] = tk.StringVar(value="")
        ttk.Label(
            f, textvariable=self.var["general_status"], foreground="#357", wraplength=440, justify="left"
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))

        ttk.Label(
            f,
            text="「按住说话热键」按住录音、松开上屏；「连续听写热键」按一下开始、再按一下停止。其余参数已用最佳默认值。",
            foreground="#888",
            wraplength=440,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 4))

    def _hotkey_row(self, parent, var: tk.StringVar) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        ttk.Entry(frame, textvariable=var, state="readonly", width=22).grid(row=0, column=0, sticky="ew")
        button = ttk.Button(frame, text="捕获按键", width=10)
        button.grid(row=0, column=1, padx=(6, 0))
        button.config(command=lambda: self._capture_key(var, button))
        return frame

    def _build_test(self, tab: ttk.Frame) -> None:
        f = self._frame(tab)
        ttk.Label(f, text="麦克风").grid(row=0, column=0, sticky="w", padx=(12, 12), pady=5)
        ttk.Combobox(
            f,
            textvariable=self.var["device"],
            values=[d[0] for d in self._devices],
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", pady=5, padx=(0, 12))

        self.var["test_seconds"] = tk.StringVar(value="5")
        ttk.Label(f, text="录音时长（秒）").grid(row=1, column=0, sticky="w", padx=(12, 12), pady=5)
        ttk.Spinbox(f, from_=1, to=30, textvariable=self.var["test_seconds"], width=8).grid(
            row=1, column=1, sticky="w", pady=5, padx=(0, 12)
        )

        btns = ttk.Frame(f)
        btns.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 2))
        self._test_btn = ttk.Button(btns, text="开始录音", command=self._test_toggle)
        self._test_btn.pack(side="left")
        ttk.Button(btns, text="试听", command=self._test_play).pack(side="left", padx=6)
        ttk.Button(btns, text="清空", command=lambda: self._test_text.delete("1.0", "end")).pack(side="left")

        self.var["test_status"] = tk.StringVar(value="点「开始录音」后对着麦克风说话。")
        ttk.Label(f, textvariable=self.var["test_status"], foreground="#555", wraplength=440, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 4)
        )

        self._test_text = tk.Text(f, height=8, wrap="word")
        self._test_text.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        f.rowconfigure(4, weight=1)

    def _build_history(self, tab: ttk.Frame) -> None:
        f = self._frame(tab)
        self._history_items: list[dict] = []
        self._history_list = tk.Listbox(f, height=12, activestyle="none")
        self._history_list.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=12, pady=(12, 6))
        f.rowconfigure(0, weight=1)

        btns = ttk.Frame(f)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6))
        ttk.Button(btns, text="复制选中", command=self._history_copy).pack(side="left")
        ttk.Button(btns, text="刷新", command=self._history_refresh).pack(side="left", padx=6)
        ttk.Button(btns, text="清空", command=self._history_clear).pack(side="left")

        self.var["history_status"] = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.var["history_status"], foreground="#555").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12)
        )
        self._history_refresh()

    def _build_about(self, tab: ttk.Frame) -> None:
        f = self._frame(tab)
        self._about_text = tk.Text(f, height=12, wrap="word")
        self._about_text.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=12, pady=(12, 6))
        self._about_text.insert("1.0", self._about_info())
        self._about_text.config(state="disabled")
        f.rowconfigure(0, weight=1)

        btns = ttk.Frame(f)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6))
        ttk.Button(btns, text="检查更新", command=self._check_update).pack(side="left")
        ttk.Button(btns, text="复制信息", command=self._copy_about).pack(side="left", padx=6)

        self.var["about_status"] = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.var["about_status"], foreground="#555", wraplength=460, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12)
        )

        model_box = ttk.LabelFrame(f, text=" 模型 ")
        model_box.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 4))
        row = ttk.Frame(model_box)
        row.pack(fill="x")
        self.var["model_choice"] = tk.StringVar(value=str(load_config().get("engine", "sensevoice")))
        ttk.Combobox(
            row, textvariable=self.var["model_choice"], values=["sensevoice", "paraformer"],
            state="readonly", width=14,
        ).pack(side="left", padx=(10, 6), pady=8)
        ttk.Button(row, text="下载并切换", command=self._download_switch_model).pack(side="left", pady=8)
        ttk.Label(
            model_box,
            text="sensevoice：中/英/日/韩/粤，精度高（约 1GB）；paraformer：中文，体积小（约 230MB）",
            foreground="#888", wraplength=440, justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 8))
        self.var["model_status"] = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.var["model_status"], foreground="#357", wraplength=460, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12)
        )

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
            "voiceinput",
            "将同时监听各个麦克风，请在这几秒内对着麦克风连续说几句话。\n\n开始检测？",
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
            self._test_recording = False  # 让录音循环提前结束
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
        """按当前配置构建 / 复用测试用引擎。"""
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
            f"voiceinput 版本    {__version__}",
            f"Python             {platform.python_version()} ({platform.architecture()[0]})",
            f"识别引擎           {cfg['engine']}",
            f"模型目录           {model_dir}  [{'存在' if model_dir.exists() else '不存在'}]",
            f"配置文件           {DEFAULT_CONFIG_PATH}",
            "",
            "依赖版本：",
        ]
        for pkg in ("sherpa-onnx", "sounddevice", "soxr", "faster-whisper"):
            try:
                lines.append(f"  {pkg:16}{pkg_version(pkg)}")
            except PackageNotFoundError:
                pass
        lines += [
            "",
            "本工具为完全离线的语音输入法，除首次下载模型和手动「检查更新」外不访问网络。",
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
            if current == latest:
                message = f"sherpa-onnx 已是最新版本（{current}）。"
            else:
                message = (
                    f"sherpa-onnx 有新版本：{current} → {latest}\n"
                    "更新命令：uv pip install -U sherpa-onnx\n"
                    "（voiceinput 本身为本地工具，无独立在线版本）"
                )
            self.root.after(0, lambda: self.var["about_status"].set(message))

        threading.Thread(target=worker, daemon=True).start()

    def _download_switch_model(self) -> None:
        engine = self.var["model_choice"].get()
        self.var["model_status"].set(f"开始下载 {engine} 模型…")

        def worker() -> None:
            from .download_models import download

            cfg = load_config()
            model_dir = resolve_model_dir(cfg)

            def progress(pct: float) -> None:
                self.root.after(
                    0, lambda: self.var["model_status"].set(f"下载 {engine}：{pct * 100:.0f}%")
                )

            try:
                download(engine, model_dir, progress=progress)
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


def main() -> int:
    cfg = load_config()
    root = tk.Tk()
    window = SettingsWindow(root, cfg)
    root.mainloop()
    return window.exit_code


if __name__ == "__main__":
    sys.exit(main())
