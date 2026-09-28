"""应用编排：热键 → 录音 → 转写 → 上屏。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

import keyboard

from . import autostart, history, hud
from .config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, SETTINGS_RESTART_EXIT, resolve_model_dir
from .engines import build_engine
from .hotkey import PushToTalk
from .inject import insert_text
from .recorder import TARGET_SR, Recorder, split_long_audio, trim_silence

log = logging.getLogger("voiceinput")

try:
    import winsound
except ImportError:  # pragma: no cover - 非 Windows
    winsound = None

_TERMINATORS = "。！？!?；;\n"


def split_caption(text: str) -> tuple[str, str]:
    """把转写文本切成 (上一句, 当前句) 两行。

    按句末标点断句：倒数第二句放在第一行，最后一段（可能是未说完的半句）放在第二行。
    """
    text = (text or "").strip()
    if not text:
        return "", ""
    parts: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _TERMINATORS:
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return parts[-2], parts[-1]


class VoiceInputApp:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.engine = None
        self._tray = None
        self._lock = threading.Lock()
        self._engine_ready = False
        self._quit = threading.Event()
        self._restart_requested = False
        self._cancel = False
        self._last_insert: Optional[tuple[str, float]] = None
        self._hud_proc = None
        self._status = "idle"
        self._partial_stop = threading.Event()
        caption = cfg.get("caption", {})
        self._caption_mode = str(caption.get("mode", "show"))
        self._caption_font_size = int(caption.get("font_size", 15))
        self._caption_lines = ["", ""]

        self._recording_owner: Optional[str] = None
        self._continuous_last = 0.0

        audio = cfg.get("audio", {})
        self.recorder = Recorder(
            device=audio.get("device"),
            max_duration=float(audio.get("max_duration", 300.0)),
            on_max_duration=self._on_max_duration,
        )
        hotkey = cfg.get("hotkey", {})
        self._ptt = PushToTalk(
            key=str(hotkey.get("key", "f9")),
            on_start=lambda: self._start_recording("primary"),
            on_stop=lambda: self._stop_recording("primary"),
            mode=str(hotkey.get("mode", "hold")),
        )
        self._continuous_key = str(hotkey.get("continuous", "f10") or "").lower()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        # 1) 先注册热键，保证监听尽早生效
        self._ptt.register()

        # 录音中按 Esc 丢弃本次输入
        try:
            keyboard.on_press_key("esc", self._on_esc, suppress=False)
        except Exception:  # pragma: no cover
            pass

        # 连续听写热键：按一下开始持续录音，再按一下停止并上屏
        if self._continuous_key:
            try:
                keyboard.add_hotkey(self._continuous_key, self._toggle_continuous, suppress=False)
            except Exception as exc:  # pragma: no cover
                log.warning("连续听写热键注册失败：%s", exc)

        # 2) 加载模型（耗时，放在后台，避免阻塞托盘/热键）
        threading.Thread(target=self._load_engine, daemon=True).start()

        # 3) 托盘
        if self.cfg.get("feedback", {}).get("tray", True):
            try:
                from .tray import TrayController

                self._tray = TrayController(
                    title="voiceinput - 加载中…",
                    on_quit=self.quit,
                    on_open_settings=self._open_settings,
                    on_open_config=self._open_config,
                    on_open_models=self._open_models,
                    on_toggle_autostart=self._toggle_autostart,
                    is_autostart=autostart.is_enabled,
                    on_restart=self.request_restart,
                    on_set_caption=self.set_caption_mode,
                    caption_mode=lambda: self._caption_mode,
                    on_set_font=self.set_caption_font_size,
                    font_size=lambda: self._caption_font_size,
                )
            except Exception as exc:  # pragma: no cover
                log.warning("系统托盘不可用：%s", exc)
                self._tray = None

        # 4) 字幕窗
        if self._caption_mode != "off":
            self._start_hud()
        threading.Thread(target=self._hud_heartbeat, daemon=True).start()

        # 5) 撤销上屏热键
        undo_key = str(self.cfg.get("hotkey", {}).get("undo", "") or "")
        if undo_key:
            try:
                keyboard.add_hotkey(undo_key, self._undo, suppress=False)
            except Exception as exc:  # pragma: no cover
                log.warning("撤销热键注册失败：%s", exc)

    def _load_engine(self) -> None:
        try:
            self.engine = build_engine(self.cfg)
            self._engine_ready = True
            log.info("模型加载完成：%s（按住 %s 说话）", self.engine.name, self._ptt.key)
            if self._tray:
                info = [
                    f"引擎：{self.engine.name}",
                    f"热键：按住 {self._ptt.key.upper()} 说话",
                ]
                if self._continuous_key:
                    info.append(f"连续听写：{self._continuous_key.upper()} 开始/停止")
                self._tray.set_info(info)
                self._tray.set_status("idle", f"voiceinput - {self.engine.name} 就绪")
        except Exception as exc:
            log.error("模型加载失败：%s", exc)
            if self._tray:
                self._tray.set_status("error", "voiceinput - 模型加载失败")

    def quit(self) -> None:
        self._quit.set()
        self._partial_stop.set()
        if self.recorder.recording:
            self.recorder.stop()
        self._stop_hud()
        if self._tray:
            self._tray.stop()

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    def request_restart(self) -> None:
        self._restart_requested = True
        self.quit()

    def run_console(self) -> None:
        log.info(
            "就绪后：按住「%s」说话，松开自动转写并上屏。按 Ctrl+C 退出。",
            self._ptt.key,
        )
        try:
            self._ptt.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.quit()

    def run_tray(self) -> None:
        if self._tray is None:
            self.run_console()
            return
        self._tray.run()  # 阻塞在主线程

    # ------------------------------------------------------------------ #
    # 热键回调
    # ------------------------------------------------------------------ #
    def _start_recording(self, owner: str) -> None:
        if not self._engine_ready:
            log.warning("模型尚未加载完成，请稍候再试。")
            self._beep("error")
            return
        if self.recorder.recording:
            return
        self._cancel = False
        self._recording_owner = owner
        self._caption_lines = ["", ""]
        self._beep("start")
        self.recorder.start()
        self._set_hud("recording")
        self._start_partial()
        if self._tray:
            self._tray.set_status("recording", "voiceinput - 录音中…")

    def _stop_recording(self, owner: str) -> None:
        # 只有发起本次录音的热键才能停止它，避免两个热键互相干扰
        if not self.recorder.recording:
            return
        if self._recording_owner and self._recording_owner != owner:
            return
        self._finish()

    def _toggle_continuous(self) -> None:
        now = time.time()
        if now - self._continuous_last < 0.35:  # 防按键自动重复
            return
        self._continuous_last = now
        if self.recorder.recording and self._recording_owner == "continuous":
            self._finish()
        elif not self.recorder.recording:
            self._start_recording("continuous")

    def _on_esc(self, _event=None) -> None:
        if self.recorder.recording:
            log.info("已取消本次录音。")
            self._cancel = True
            self._finish()

    def _on_max_duration(self) -> None:
        log.info("达到最长录音时长，自动结束。")
        self._finish()

    def _finish(self) -> None:
        if not self.recorder.recording:
            return
        self._recording_owner = None
        self._partial_stop.set()
        data = self.recorder.stop()
        if self._cancel:
            self._cancel = False
            self._beep("error")
            self._caption_lines = ["", ""]
            self._set_hud("idle")
            if self._tray:
                self._tray.set_status("idle", "voiceinput - 已取消")
            return
        self._beep("stop")
        self._set_hud("processing")
        if self._tray:
            self._tray.set_status("processing", "voiceinput - 转写中…")
        threading.Thread(target=self._transcribe_and_type, args=(data,), daemon=True).start()

    # ------------------------------------------------------------------ #
    # 转写与上屏
    # ------------------------------------------------------------------ #
    def _transcribe_and_type(self, data) -> None:
        try:
            if data is None or data.size == 0:
                return
            audio_cfg = self.cfg.get("audio", {})
            if audio_cfg.get("trim_silence", True):
                data = trim_silence(data)
            duration = data.size / TARGET_SR
            if duration < float(audio_cfg.get("min_duration", 0.3)):
                log.info("录音过短（%.2fs），忽略。", duration)
                return
            if not self._engine_ready:
                log.warning("模型未就绪，丢弃本次录音。")
                return

            segments = split_long_audio(data)
            pieces: list[str] = []
            with self._lock:
                for seg in segments:
                    if seg.size < int(TARGET_SR * 0.2):
                        continue
                    pieces.append(self.engine.transcribe(seg, TARGET_SR) or "")
            text = "".join(piece.strip() for piece in pieces).strip()
            if not text:
                log.info("未识别到有效内容。")
                return
            spoken = self._apply_replacements(text)

            out = self.cfg.get("output", {})
            payload = spoken
            if out.get("append_space", True):
                payload += " "
            if out.get("append_newline", False):
                payload += "\n"

            insert_text(
                payload,
                method=str(out.get("method", "paste")),
                restore_clipboard=bool(out.get("restore_clipboard", True)),
            )
            self._last_insert = (payload, time.time())
            log.info("已上屏：%s", spoken)
            hist = self.cfg.get("history", {})
            if hist.get("enabled", True):
                history.add(spoken, max_entries=int(hist.get("max", 500)))
        except Exception as exc:
            log.exception("转写失败：%s", exc)
            self._beep("error")
        finally:
            self._caption_lines = ["", ""]
            self._set_hud("idle")
            if self._tray:
                self._tray.set_status("idle", "voiceinput - 就绪")

    # ------------------------------------------------------------------ #
    # 字幕窗 / 撤销 / 文本替换
    # ------------------------------------------------------------------ #
    def _state(self) -> dict:
        return {
            "status": self._status,
            "mode": self._caption_mode,
            "font_size": self._caption_font_size,
            "line1": self._caption_lines[0],
            "line2": self._caption_lines[1],
        }

    def _write_state(self) -> None:
        hud.write_state(self._state())

    def _set_hud(self, status: str) -> None:
        self._status = status
        self._write_state()

    def _hud_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--hud"]
        return [sys.executable, "-m", "voiceinput.hud"]

    def _ensure_hud(self) -> None:
        if self._hud_proc is None or self._hud_proc.poll() is not None:
            self._start_hud()

    def _start_hud(self) -> None:
        try:
            self._hud_proc = subprocess.Popen(
                self._hud_command(), cwd=str(PROJECT_ROOT), close_fds=True
            )
        except Exception as exc:  # pragma: no cover
            log.warning("字幕窗启动失败：%s", exc)
            self._hud_proc = None

    def _stop_hud(self) -> None:
        if self._hud_proc and self._hud_proc.poll() is None:
            try:
                self._hud_proc.terminate()
            except Exception:
                pass
        self._hud_proc = None
        hud.clear_state()

    def _hud_heartbeat(self) -> None:
        while not self._quit.is_set():
            self._write_state()
            self._quit.wait(4.0)

    def set_caption_mode(self, mode: str) -> None:
        if mode not in ("show", "dot", "off"):
            return
        self._caption_mode = mode
        self.cfg.setdefault("caption", {})["mode"] = mode
        try:
            from .config import save_config

            save_config(self.cfg)
        except Exception:
            pass
        if mode == "off":
            self._stop_hud()
        else:
            self._ensure_hud()
            self._write_state()

    def set_caption_font_size(self, size: int) -> None:
        try:
            size = max(10, min(40, int(size)))
        except (TypeError, ValueError):
            return
        self._caption_font_size = size
        self.cfg.setdefault("caption", {})["font_size"] = size
        try:
            from .config import save_config

            save_config(self.cfg)
        except Exception:
            pass
        self._write_state()

    # ------------------------------------------------------------------ #
    # 实时字幕（录音中滚动重解码）
    # ------------------------------------------------------------------ #
    def _start_partial(self) -> None:
        if self._caption_mode == "off" or not self._engine_ready:
            return
        self._partial_stop.clear()
        threading.Thread(target=self._partial_loop, daemon=True).start()

    def _partial_loop(self) -> None:
        caption = self.cfg.get("caption", {})
        interval = float(caption.get("interval", 0.5))
        window = int(float(caption.get("window", 25.0)) * TARGET_SR)
        while not self._partial_stop.wait(interval):
            if self._cancel or not self.recorder.recording:
                break
            data = self.recorder.snapshot()
            if data is None or data.size < int(TARGET_SR * 0.4):
                continue
            if data.size > window:
                data = data[-window:]
            try:
                with self._lock:
                    text = self.engine.transcribe(data, TARGET_SR)
            except Exception:
                continue
            line1, line2 = split_caption(text)
            self._caption_lines = [line1, line2]
            self._write_state()

    def _undo(self) -> None:
        if not self._last_insert:
            self._beep("error")
            return
        text, timestamp = self._last_insert
        if time.time() - timestamp > 60:
            self._last_insert = None
            self._beep("error")
            return
        for _ in range(len(text)):
            keyboard.send("backspace")
        self._last_insert = None
        log.info("已撤销上屏（%d 个字符）。", len(text))

    def _apply_replacements(self, text: str) -> str:
        rules = self.cfg.get("replacements") or {}
        if isinstance(rules, dict):
            for src, dst in rules.items():
                if src:
                    text = text.replace(str(src), str(dst))
        return text

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def _beep(self, kind: str) -> None:
        if not self.cfg.get("feedback", {}).get("beep", True) or winsound is None:
            return
        try:
            freq, dur = {
                "start": (900, 90),
                "stop": (600, 90),
                "error": (350, 220),
            }.get(kind, (700, 90))
            winsound.Beep(freq, dur)
        except Exception:
            pass

    def _open_config(self) -> None:
        path = DEFAULT_CONFIG_PATH
        if not path.exists():
            from .config import save_default_config

            save_default_config(path)
        os.startfile(str(path))  # noqa: S606

    def _open_models(self) -> None:
        os.startfile(str(resolve_model_dir(self.cfg)))  # noqa: S606

    def _settings_command(self) -> list[str]:
        # 打包后 exe 不支持 -m，用 --settings 子命令；开发态用 -m
        if getattr(sys, "frozen", False):
            return [sys.executable, "--settings"]
        return [sys.executable, "-m", "voiceinput.gui"]

    def _open_settings(self) -> None:
        try:
            proc = subprocess.Popen(
                self._settings_command(), cwd=str(PROJECT_ROOT), close_fds=True
            )
        except Exception as exc:
            log.error("打开设置窗口失败：%s", exc)
            return

        def watch() -> None:
            if proc.wait() == SETTINGS_RESTART_EXIT:
                log.info("设置已保存，正在重启程序…")
                self.request_restart()

        threading.Thread(target=watch, daemon=True).start()

    def _toggle_autostart(self) -> None:
        if autostart.is_enabled():
            autostart.disable()
            log.info("已关闭开机自启。")
        else:
            try:
                log.info("已开启开机自启：%s", autostart.enable())
            except Exception as exc:
                log.error("设置开机自启失败：%s", exc)
