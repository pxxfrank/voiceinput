"""应用编排：双模式语音输入、流式 ASR、复核、精修、安全上屏。"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import keyboard

from . import clipboard, paths
from .asr_merge import merge_stream_review
from .audio import TARGET_SR, AudioCapture
from .config import load_config, save_config
from .paths import SETTINGS_RESTART_EXIT
from .engines import OfflineReviewer
from .hotkey import PushToTalk
from .inject import InputTransaction, TextInsertionService
from .llm import LlamaServer, Refiner
from .overlay import OverlayWindow, ReviewWindow
from .refinement import (
    RefinementPipeline,
    RefinementScheduler,
    Segment,
    build_context,
    compose_text,
)
from .storage import Storage
from .streaming import StreamingAsr, StreamingSession
from .target import WindowTarget, capture_target
from .terminology import TerminologyManager

log = logging.getLogger("voiceinput.app")


@dataclass
class Session:
    id: str
    requested_mode: str
    target: WindowTarget | None
    started_at: float
    effective_smart: bool = False
    segments: list[Segment] = field(default_factory=list)
    transactions: list[InputTransaction] = field(default_factory=list)
    inserted_text: str = ""
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    executor: ThreadPoolExecutor | None = None
    last_partial: tuple[str, str] = ("", "")

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at


class VoiceInputApp:
    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        config_path: str | None = None,
        feed_wav: str | None = None,
        feed_speed: float = 1.0,
        exit_after_session: bool = False,
        auto_commit: bool = False,
        skip_onboarding: bool = False,
        session_delay: float = 0.0,
    ) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.feed_wav = feed_wav
        self.feed_speed = max(0.0, float(feed_speed))
        self.exit_after_session = exit_after_session
        self.auto_commit = auto_commit
        self.skip_onboarding = skip_onboarding
        self.session_delay = max(0.0, float(session_delay))
        self.storage = Storage()
        self.terminology = TerminologyManager(self.storage)
        self.insertion = TextInsertionService(cfg)
        self.llm_server = LlamaServer(cfg)
        self.refiner = Refiner(cfg, self.llm_server)
        self.pipeline = RefinementPipeline(cfg, self.terminology, self.llm_server, self.refiner)
        self.scheduler = RefinementScheduler(self.pipeline)
        self.streaming: StreamingAsr | None = None
        self.reviewer: OfflineReviewer | None = None
        self.session: Session | None = None
        self.state = "idle"
        self.events: queue.Queue = queue.Queue()
        self.root: tk.Tk | None = None
        self.overlay: OverlayWindow | None = None
        self.review_ui: ReviewWindow | None = None
        self.tray = None
        self._capture: AudioCapture | None = None
        self._feed_stop = threading.Event()
        self._feeder: threading.Thread | None = None
        self._stream: StreamingSession | None = None
        self._quit = threading.Event()
        self._restart = False
        self._ptt: PushToTalk | None = None
        self._last_insert: InputTransaction | None = None
        self._model_errors: list[str] = []
        self._llm_state = "idle"
        self._review_state = "idle"
        self._continuous_last = 0.0
        self._pending_text = ""
        self._last_voice_at = 0.0
        self._hide_after_id = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def run(self) -> int:
        self.root = tk.Tk()
        self.root.withdraw()
        self._setup_dpi()
        self.overlay = OverlayWindow(
            self.root, self.cfg, self._on_ui_command, self._on_position
        )
        self.review_ui = ReviewWindow(self.root, self.cfg, self._on_ui_command)
        self._register_hotkeys()
        self._start_tray()
        threading.Thread(target=self._load_models, name="model-loader", daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(50, self._pump)
        try:
            self.root.mainloop()
        finally:
            self._cleanup()
        return 0

    def _setup_dpi(self) -> None:
        try:
            ctypes = __import__("ctypes")
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes = __import__("ctypes")
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        try:
            assert self.root is not None
            dpi = self.root.winfo_fpixels("1i")
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

    def _register_hotkeys(self) -> None:
        hot = self.cfg.get("hotkey", {}) or {}
        self._ptt = PushToTalk(
            key=str(hot.get("key", "f9")),
            on_start=lambda: self._post("hotkey_start"),
            on_stop=lambda: self._post("hotkey_stop"),
            mode=str(hot.get("mode", "hold")),
        )
        try:
            self._ptt.register()
        except Exception as exc:
            self._model_errors.append(f"全局热键注册失败：{exc}")
            log.error("热键注册失败：%s", exc)

        try:
            cancel_key = str(hot.get("cancel", "esc") or "esc").strip() or "esc"
            keyboard.on_press_key(cancel_key, self._on_esc)
        except Exception:
            pass

        continuous = str(hot.get("continuous", "") or "").strip()
        if continuous:
            try:
                keyboard.add_hotkey(continuous, lambda: self._post("toggle_continuous"))
            except Exception as exc:
                log.warning("连续听写热键注册失败：%s", exc)
        commit = str(hot.get("commit", "") or "").strip()
        if commit:
            try:
                keyboard.add_hotkey(commit, lambda: self._post("commit_hotkey"))
            except Exception as exc:
                log.warning("提交热键注册失败：%s", exc)
        undo = str(hot.get("undo", "") or "").strip()
        if undo:
            try:
                keyboard.add_hotkey(undo, lambda: self._post("undo"))
            except Exception as exc:
                log.warning("撤销热键注册失败：%s", exc)

    def _start_tray(self) -> None:
        if not self.cfg.get("feedback", {}).get("tray", True):
            return
        try:
            from .tray import TrayController

            self.tray = TrayController(
                title="本地语音输入 - 加载中…",
                on_quit=lambda: self._post("quit"),
                on_open_settings=lambda: self._post("open_settings"),
                on_set_mode=lambda m: self._post("set_mode", mode=m),
                mode=lambda: str(self.cfg.get("mode", "auto")),
                on_open_panel=lambda: self._post("open_panel"),
                on_open_onboarding=lambda: self._post("open_onboarding"),
                on_undo=lambda: self._post("undo"),
                on_restart=lambda: self._post("restart"),
            )
            threading.Thread(target=self.tray.run, name="tray", daemon=True).start()
        except Exception as exc:
            log.warning("系统托盘不可用：%s", exc)
            self.tray = None

    def _cleanup(self) -> None:
        self._quit.set()
        self._feed_stop.set()
        if self._capture:
            try:
                self._capture.stop()
            except Exception:
                pass
        if self._stream:
            try:
                self._stream.stop(timeout=2.0)
            except Exception:
                pass
        if self.session and self.session.executor:
            self.session.executor.shutdown(wait=False, cancel_futures=True)
        if self._tray_safe():
            try:
                self.tray.stop()
            except Exception:
                pass
        self.scheduler.close()
        if self.reviewer:
            self.reviewer.close()
        self.llm_server.stop()

    def _tray_safe(self) -> bool:
        return self.tray is not None

    def quit(self) -> None:
        self._quit.set()
        self._feed_stop.set()
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass

    def request_restart(self) -> None:
        self._restart = True
        self.quit()

    @property
    def restart_requested(self) -> bool:
        return self._restart

    # ------------------------------------------------------------------ #
    # 模型加载
    # ------------------------------------------------------------------ #
    def _load_models(self) -> None:
        self._post("status", state="loading", text="正在加载语音识别模型…")
        try:
            self.streaming = StreamingAsr(self.cfg)
            self._post("status", state="loading", text="流式模型就绪，正在加载复核模型…")
        except Exception as exc:
            log.exception("流式模型加载失败")
            self._model_errors.append(str(exc))
            self._post("fatal_model", text=f"流式 ASR 模型加载失败：{exc}")
            return

        try:
            self.reviewer = OfflineReviewer(self.cfg)
            self._review_state = "ready"
        except Exception as exc:
            log.warning("复核模型不可用：%s", exc)
            self._review_state = "error"
            self._model_errors.append(f"复核模型不可用：{exc}")

        self._post("models_ready")
        if self.cfg.get("refine", {}).get("enabled", True) and self.cfg.get("refine", {}).get("preload", True):
            if self.llm_server.available:
                self._post("llm_status", text="LLM 加载中…")
                self.llm_server.preload()
                self._llm_state = "ready" if self.llm_server.running else "error"
                self._post("llm_status", text="LLM 就绪" if self._llm_state == "ready" else "LLM 不可用")
            else:
                self._llm_state = "missing"
                self._post("llm_status", text="未找到本地 LLM 模型")

        if not self.storage.onboarded and not self.skip_onboarding and not self.feed_wav:
            self._post("onboarding")

    def _post(self, kind: str, **data) -> None:
        self.events.put({"type": kind, **data})

    # ------------------------------------------------------------------ #
    # 事件循环
    # ------------------------------------------------------------------ #
    def _pump(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                try:
                    self._dispatch(event)
                except Exception:
                    log.exception("处理事件失败：%s", event.get("type"))
        except queue.Empty:
            pass
        self._check_session_limits()
        if self.root:
            self.root.after(40, self._pump)

    def _check_session_limits(self) -> None:
        session = self.session
        if self.state != "recording" or session is None:
            return
        now = time.time()
        audio_cfg = self.cfg.get("audio", {}) or {}
        silence_timeout = float(audio_cfg.get("silence_timeout", 30.0) or 0.0)
        if silence_timeout > 0 and self._last_voice_at and now - self._last_voice_at > silence_timeout:
            log.info("连续 %.0f 秒无语音输入，自动停止。", silence_timeout)
            self.finish_session()
            return
        max_duration = float(audio_cfg.get("max_duration", 600.0) or 0.0)
        if max_duration > 0 and session.elapsed > max_duration:
            log.info("达到最长录音时长 %.0f 秒，自动结束。", max_duration)
            self.finish_session()

    def _dispatch(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "hotkey_start":
            self.start_session("primary")
        elif kind == "hotkey_stop":
            self.finish_session()
        elif kind == "toggle_continuous":
            self._toggle_continuous()
        elif kind == "cancel":
            self.cancel_session()
        elif kind == "commit_hotkey":
            if self.state == "review":
                self.commit_review()
            elif self.state == "recording":
                self.finish_session()
        elif kind == "undo":
            self._undo()
        elif kind == "stream":
            self._handle_stream(event.get("event") or {})
        elif kind == "session_stopped":
            self._on_session_stopped(event)
        elif kind == "cancelled_session":
            self._on_cancelled_session(event)
        elif kind == "wav_done":
            self.finish_session()
        elif kind == "segment_done":
            self._on_segment_done(event)
        elif kind == "target_changed":
            self._on_target_changed(event)
        elif kind == "status":
            self._set_status(event.get("text", ""), event.get("state"))
        elif kind == "models_ready":
            self._on_models_ready()
        elif kind == "fatal_model":
            self._set_status(event.get("text", "模型不可用"), "error", error=True)
        elif kind == "llm_status":
            self._set_status(event.get("text", ""), "info")
        elif kind == "onboarding":
            self.open_onboarding()
        elif kind == "review_refresh":
            if self.review_ui:
                self.review_ui.refresh()
        elif kind == "review_committed":
            self._on_review_committed(event.get("text", ""))
        elif kind == "review_failed":
            self._on_review_failed(event.get("error", "插入失败"))
        elif kind == "selection_refined":
            if self.review_ui:
                self.review_ui.replace_selection(event.get("text", ""))
        elif kind == "set_mode":
            self.set_mode(str(event.get("mode", "auto")))
        elif kind == "open_settings":
            self.open_settings()
        elif kind == "open_panel":
            self.open_review()
        elif kind == "open_onboarding":
            self.open_onboarding()
        elif kind == "quit":
            self.quit()
        elif kind == "restart":
            self.request_restart()

    def _on_models_ready(self) -> None:
        errors = self._model_errors
        if errors:
            log.error("模型/热键问题：%s", errors[0])
        if self.tray:
            try:
                self.tray.set_status(
                    "idle",
                    "本地语音输入 - 就绪" if not errors else "本地语音输入 - 需要检查",
                    info=[
                        f"模式：{self._mode_text()}",
                        f"热键：{self._ptt.key.upper() if self._ptt else 'F9'}",
                        f"LLM：{'就绪' if self.llm_server.running else '按需加载'}",
                    ],
                )
            except Exception:
                pass
        if errors and self.overlay:
            self.overlay.show("error")
            self.overlay.set_state("error", status=errors[0], hint="请打开设置查看诊断", mode=self._mode_text())
            self.root.after(5000, self.overlay.hide)  # type: ignore[union-attr]
        if self.feed_wav and not errors:
            delay = int((self.session_delay + 0.6) * 1000)
            self.root.after(delay, lambda: self.start_session("wav"))  # type: ignore[union-attr]

    def _hint(self) -> str:
        if not self._ptt:
            return ""
        key = self._ptt.key.upper()
        if self._ptt.mode == "toggle":
            return f"按 {key} 开始，再按停止"
        return f"按住 {key} 说话，松开结束"

    def _set_status(self, text: str, state: str | None = None, *, error: bool = False, sticky: bool = False) -> None:
        if not self.overlay:
            return
        active = state in ("recording", "processing", "review", "target_changed", "error", "done")
        if active:
            self.overlay.show(state or "idle")
        self.overlay.set_state(
            state or ("error" if error else "idle"),
            status=text,
            hint="" if sticky else self._hint(),
            mode=self._mode_text(),
        )

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def start_session(self, source: str) -> None:
        if self.state != "idle":
            return
        if self.streaming is None:
            self._beep("error")
            msg = self._model_errors[0] if self._model_errors else "模型尚未加载完成，请稍候"
            self._set_status(msg, "error", error=True)
            if self.overlay:
                self.root.after(2500, self.overlay.hide)  # type: ignore[union-attr]
            return
        if self._capture and self._capture.recording:
            return

        target = capture_target()
        if target and target.pid == os.getpid():
            log.warning("捕获到自身窗口，忽略目标")
            target = None
        log.info("会话目标：%s · %s", target.exe if target else "无", target.class_name if target else "")
        mode = str(self.cfg.get("mode", "auto"))
        session = Session(
            id="sess_" + time.strftime("%Y%m%d_%H%M%S"),
            requested_mode=mode,
            target=target,
            started_at=time.time(),
            effective_smart=(mode == "smart"),
            executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="segment"),
        )
        self.session = session
        self.state = "recording"
        self._pending_text = ""
        self._last_voice_at = time.time()

        audio_cfg = self.cfg.get("audio", {}) or {}
        vad_cfg = audio_cfg.get("vad", {}) or {}
        self._capture = None
        if self.feed_wav:
            try:
                from .audio import load_wav, resample_to_16k

                data, sr = load_wav(self.feed_wav)
                if sr != TARGET_SR:
                    data = resample_to_16k(data, sr)
                self._wav_data = data
            except Exception as exc:
                self.state = "idle"
                self.session = None
                self._set_status(f"测试音频读取失败：{exc}", "error", error=True)
                return
        else:
            self._capture = AudioCapture(
                device=audio_cfg.get("device"),
                on_error=lambda msg: self._post("status", state="error", text=msg),
            )
            try:
                self._capture.start()
            except Exception as exc:
                self.state = "idle"
                self.session = None
                self._beep("error")
                self._set_status(f"麦克风打开失败：{exc}", "error", error=True)
                return
        self._stream = StreamingSession(
            self.streaming,
            self.cfg,
            self._on_stream_event_direct,
            min_segment_s=float(vad_cfg.get("min_segment_s", 0.4)),
            max_segment_s=float(vad_cfg.get("max_segment_s", 20.0)),
        )
        self._stream.start()
        self._feed_stop.clear()
        if self.feed_wav:
            self._feeder = threading.Thread(target=self._feed_wav_loop, name="wav-feed", daemon=True)
        else:
            self._feeder = threading.Thread(target=self._feed_loop, name="audio-feed", daemon=True)
        self._feeder.start()

        self.overlay.show("recording")  # type: ignore[union-attr]
        self.overlay.set_mode(mode)  # type: ignore[union-attr]
        self.overlay.set_text("", "", dim="正在聆听…")  # type: ignore[union-attr]
        self.overlay.set_state(  # type: ignore[union-attr]
            "recording", status="录音中", hint=self._hint(), mode=self._mode_text()
        )
        self._beep("start")
        if self.tray:
            self.tray.set_status("recording", "本地语音输入 - 录音中…")

    def _feed_loop(self) -> None:
        while not self._feed_stop.is_set():
            capture = self._capture
            stream = self._stream
            if capture is None or stream is None:
                break
            chunk = capture.read(0.2)
            if chunk is not None:
                stream.feed(chunk)

    def _feed_wav_loop(self) -> None:
        """测试/验收模式：把真实 WAV 以可控速率送入同一识别管线。"""
        import numpy as np

        session = self.session
        stream = self._stream
        data = getattr(self, "_wav_data", None)
        if stream is None or data is None:
            return
        stream.feed(np.zeros(int(TARGET_SR * 0.3), dtype=np.float32))
        chunk = 1600  # 100ms
        interval = 0.1 / self.feed_speed if self.feed_speed > 0 else 0.0
        for i in range(0, len(data), chunk):
            if self._feed_stop.is_set():
                return
            stream.feed(data[i : i + chunk])
            if interval:
                time.sleep(interval)
        stream.feed(np.zeros(int(TARGET_SR * 1.2), dtype=np.float32))
        self._post("wav_done")

    def _toggle_continuous(self) -> None:
        now = time.time()
        if now - self._continuous_last < 0.35:
            return
        self._continuous_last = now
        if self.state == "recording":
            self.finish_session()
        elif self.state == "idle":
            self.start_session("continuous")

    def _on_esc(self, _event=None) -> None:
        if self.state in ("recording", "processing"):
            self.cancel_session()
        elif self.state == "review":
            self.review_ui.hide() if self.review_ui else None

    def finish_session(self) -> None:
        if self.state != "recording":
            return
        self.state = "processing"
        self.overlay.set_state("processing", status="处理中…", hint="正在收尾识别", mode=self._mode_text())  # type: ignore[union-attr]
        self._feed_stop.set()
        threading.Thread(target=self._finish_worker, name="finish", daemon=True).start()

    def _finish_worker(self) -> None:
        session = self.session
        try:
            if self._capture:
                self._capture.stop()
            if self._feeder and self._feeder.is_alive():
                self._feeder.join(timeout=2.0)
            if self._stream:
                self._stream.stop(timeout=8.0)
            if session and session.executor:
                session.executor.shutdown(wait=True)
        except Exception as exc:
            log.exception("收尾失败：%s", exc)
        finally:
            self._post("session_stopped", cancelled=bool(session and session.cancelled))

    def cancel_session(self) -> None:
        session = self.session
        if not session:
            return
        if self.state == "review":
            if self.review_ui:
                self.review_ui.hide()
            self._end_session(session, cancelled=True)
            return
        if self.state not in ("recording", "processing"):
            return
        session.cancelled = True
        self.state = "processing"
        self.overlay.set_state("processing", status="正在取消…", hint="")  # type: ignore[union-attr]
        self._feed_stop.set()
        threading.Thread(target=self._cancel_worker, args=(session,), name="cancel", daemon=True).start()

    def _cancel_worker(self, session: Session) -> None:
        try:
            if self._stream:
                self._stream.stop(timeout=6.0)
            if self._capture:
                self._capture.stop()
            if session.executor:
                session.executor.shutdown(wait=True)
        except Exception:
            log.exception("取消收尾失败")
        finally:
            self._post("cancelled_session", session_id=session.id)

    def _on_cancelled_session(self, event: dict) -> None:
        session = self.session
        if session and session.id == event.get("session_id"):
            self._end_session(session, cancelled=True)

    def _end_session(self, session: Session, *, cancelled: bool) -> None:
        if self.session is not session:
            return
        self.session = None
        self.state = "idle"
        self._stream = None
        self._capture = None
        self._feeder = None
        if self.review_ui and self.review_ui.visible:
            self.review_ui.hide()
        if cancelled:
            if self.overlay:
                self.overlay.set_state("idle", status="已取消", hint="", mode=self._mode_text())
                self.overlay.set_text("", "", dim="已取消")
                self.root.after(900, self.overlay.hide)  # type: ignore[union-attr]
            if self.tray:
                self.tray.set_status("idle", "本地语音输入 - 就绪")
            if self.exit_after_session:
                self.root.after(800, self.quit)  # type: ignore[union-attr]
            return
        if self.overlay:
            self.overlay.set_state("done", status="完成", hint="", mode=self._mode_text())
            self.root.after(1400, self.overlay.hide)  # type: ignore[union-attr]
        if self.tray:
            self.tray.set_status("idle", "本地语音输入 - 就绪")
        if self.exit_after_session:
            self.root.after(1600, self.quit)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    # 流事件
    # ------------------------------------------------------------------ #
    def _on_stream_event_direct(self, event: dict) -> None:
        """流式线程回调。片段事件直接入队到会话执行器，保证收尾时能 wait 到。"""
        if event.get("type") == "segment":
            seg_event = event.get("segment")
            if seg_event is not None:
                try:
                    self._handle_segment(seg_event)
                except Exception:
                    log.exception("处理片段事件失败")
            return
        self._post("stream", event=event)

    def _handle_stream(self, event: dict) -> None:
        if self.session is None or self.state not in ("recording", "processing"):
            return
        kind = event.get("type")
        if kind == "partial":
            self.session.last_partial = (event.get("stable", ""), event.get("unstable", ""))
            self._last_voice_at = time.time()
            self._refresh_overlay_text()
        elif kind == "level":
            if self.overlay:
                self.overlay.set_level(float(event.get("db", -100.0)))
        elif kind == "speech_start":
            self._last_voice_at = time.time()
            if self.overlay and self.state == "recording":
                self.overlay.set_state(
                    "recording", status="正在识别…", hint=self._hint(), mode=self._mode_text()
                )
        elif kind == "error":
            self._set_status(str(event.get("message", "识别错误")), "error", error=True)
            self._beep("error")

    def _handle_segment(self, seg_event) -> None:
        session = self.session
        if session is None:
            return
        index = len(session.segments) + 1
        seg = Segment(
            id=f"{session.id}_seg{index:03d}",
            index=index,
            raw_asr=(seg_event.text or "").strip(),
            duration=float(seg_event.duration or 0.0),
            audio=seg_event.audio,
        )
        if not seg.raw_asr:
            return
        pipeline = self.pipeline
        pipeline.normalize(seg)
        with session.lock:
            session.segments.append(seg)
            if len(session.segments) > 20:
                for old in session.segments[:-20]:
                    old.audio = None
        if session.executor:
            session.executor.submit(self._process_segment, session, seg)

    def _process_segment(self, session: Session, seg: Segment) -> None:
        try:
            review_cfg = self.cfg.get("review", {}) or {}
            mode = str(review_cfg.get("mode", "auto"))
            use_review = (
                self.reviewer is not None
                and review_cfg.get("enabled", True)
                and mode != "off"
                and (mode == "always" or seg.duration >= float(review_cfg.get("min_segment_s", 2.5)))
            )
            review_text = None
            if use_review and seg.audio is not None and seg.audio.size:
                t0 = time.time()
                review_text = self.reviewer.review(seg.audio)
                seg.review_ms = (time.time() - t0) * 1000
            merge = merge_stream_review(
                seg.raw_asr,
                review_text,
                protected_terms=self.terminology.protected,
            )
            seg.reviewed_asr = review_text or ""
            seg.merge_note = merge.note or (f"复核采用：{merge.source}" if review_text else "未复核")
            seg.requires_review = merge.conflict
            base_text = merge.text
            seg.normalized = self.terminology.apply(base_text)
            seg.refine_source = "deterministic"
            seg.refined = seg.normalized

            # 自动模式在超过阈值后转为精修（只累积，不自动改写）
            if session.requested_mode == "auto" and not session.effective_smart:
                threshold = float((self.cfg.get("auto", {}) or {}).get("smart_after_seconds", 20.0))
                if session.elapsed >= threshold:
                    session.effective_smart = True

            if session.requested_mode == "smart" and not session.effective_smart:
                session.effective_smart = True

            if session.effective_smart:
                context = build_context(
                    session.segments[:-1],
                    int((self.cfg.get("refine", {}) or {}).get("max_context_sentences", 3)),
                )
                self.pipeline.refine(seg, context=context)
                seg.commit_status = "pending"
            else:
                self._commit_segment(session, seg)

            self._post("segment_done", session_id=session.id, segment_id=seg.id)
        except Exception as exc:
            log.exception("片段处理失败")
            seg.error = str(exc)
            self._post("status", state="error", text=f"片段处理失败：{exc}")

    def _commit_segment(self, session: Session, seg: Segment) -> None:
        if seg.commit_status == "committed":
            return
        text = (seg.display_text or "").strip()
        if not text:
            seg.commit_status = "failed"
            return
        with session.lock:
            separator = ""
            if session.inserted_text and session.inserted_text[-1].isascii() and text[0].isascii():
                separator = " "
            tx = self.insertion.prepare(separator + text, target=session.target, mode="fast")
            tx = self.insertion.commit(tx)
            session.transactions.append(tx)
            seg.commit_status = "committed" if tx.ok else "failed"
            if tx.ok:
                session.inserted_text += separator + text
                self._last_insert = tx
                # 已提交片段不再需要音频，及时释放内存
                seg.audio = None
            else:
                seg.error = tx.error
                self._pending_text = text
                self._post("target_changed", text=text, error=tx.error)
        self._post("segment_done", session_id=session.id, segment_id=seg.id)

    def _on_target_changed(self, event: dict) -> None:
        if self.state in ("recording", "processing"):
            self._set_status(event.get("error", "目标已变化，文字已保留"), "target_changed")
            if self.overlay:
                full = (self.session.inserted_text if self.session else "") + self._pending_text
                self.overlay.set_text(full, "", dim="目标已变化，文字已保留")
            # 不再继续向变化后的焦点提交，停下来让用户确认/复制
            if self.state == "recording":
                self.finish_session()

    def _on_segment_done(self, event: dict) -> None:
        session = self.session
        if session is None:
            return
        self._refresh_overlay_text()
        if self.review_ui and self.review_ui.visible:
            self.review_ui.refresh()

    def _on_session_stopped(self, event: dict) -> None:
        session = self.session
        if session is None:
            self.state = "idle"
            return
        cancelled = bool(event.get("cancelled") or session.cancelled)
        if cancelled:
            self._end_session(session, cancelled=True)
            return

        final_text = compose_text(session.segments)
        if not final_text and session.inserted_text:
            final_text = session.inserted_text
        self._add_history(session, final_text)
        self._add_session_stats(session, final_text)

        if session.effective_smart or any(seg.commit_status != "committed" for seg in session.segments):
            self.state = "review"
            self.overlay.set_state(
                "review",
                status=f"待确认 · {len(session.segments)} 段",
                hint="确认后插入原窗口",
                mode=self._mode_text(),
            )
            self.overlay.set_text(final_text, "", dim="")
            self.overlay.hide()
            if self.review_ui:
                self.review_ui.show(
                    session.segments,
                    model_status=self._llm_label(),
                    status="可编辑、重新识别或重新精修；插入时恢复到原窗口",
                )
            if self.auto_commit:
                self.root.after(400, self.commit_review)  # type: ignore[union-attr]
            if self.tray:
                self.tray.set_status("processing", "本地语音输入 - 待确认")
        else:
            self._end_session(session, cancelled=False)

    def _add_history(self, session: Session, final_text: str) -> None:
        if not (self.cfg.get("history", {}) or {}).get("enabled", True) or not final_text.strip():
            return
        raw = " ".join(seg.raw_asr for seg in session.segments if seg.raw_asr)
        self.storage.add_history(
            final_text,
            raw_text=raw,
            mode=session.requested_mode,
            app=session.target.exe if session.target else "",
            duration=session.elapsed,
            status="committed" if session.inserted_text else "review",
            max_entries=int((self.cfg.get("history", {}) or {}).get("max", 500)),
        )

    def _add_session_stats(self, session: Session, final_text: str) -> None:
        try:
            self.storage.add_session(
                started=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(session.started_at)),
                ended=time.strftime("%Y-%m-%dT%H:%M:%S"),
                mode=session.requested_mode,
                app=session.target.exe if session.target else "",
                segments=len(session.segments),
                asr_ms=sum(seg.review_ms for seg in session.segments),
                refine_ms=sum(seg.refine_ms for seg in session.segments),
                chars=len(final_text),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 悬浮窗文本
    # ------------------------------------------------------------------ #
    def _refresh_overlay_text(self) -> None:
        session = self.session
        if session is None or not self.overlay:
            return
        stable_parts: list[str] = []
        for seg in session.segments:
            if seg.commit_status == "committed":
                stable_parts.append(seg.display_text)
            else:
                stable_parts.append(seg.display_text)
                break
        committed = session.inserted_text
        current_stable, current_unstable = session.last_partial
        if not session.effective_smart:
            stable = committed
            if current_stable and not committed.endswith(current_stable):
                stable = committed + current_stable
            unstable = current_unstable
        else:
            stable = compose_text(session.segments)
            unstable = current_unstable
        self.overlay.set_text(stable, unstable)

    # ------------------------------------------------------------------ #
    # UI 命令
    # ------------------------------------------------------------------ #
    def _on_review_committed(self, text: str) -> None:
        session = self.session
        if self.review_ui:
            self.review_ui.hide()
        if self.overlay:
            self.overlay.set_state("done", status="已插入", hint="", mode=self._mode_text())
            self.overlay.set_text(text, "", dim="")
            self.root.after(1200, self.overlay.hide)  # type: ignore[union-attr]
        if session:
            self._end_session(session, cancelled=False)
        self.state = "idle"

    def _on_review_failed(self, error: str) -> None:
        self.state = "review"
        if self.review_ui:
            self.review_ui.set_status(f"插入失败：{error}")
            self.review_ui.show(
                self.session.segments if self.session else [],
                model_status=self._llm_label(),
                status=f"插入失败：{error}",
            )
        if self.overlay:
            self.overlay.show("target_changed")
            self.overlay.set_state("target_changed", status=error, hint="可复制或重新插入到原窗口")
    def _on_ui_command(self, action: str, payload: Any) -> None:
        if action == "stop":
            self.finish_session()
        elif action == "commit":
            if self.state == "review":
                self.commit_review()
            elif self.state == "recording":
                self.finish_session()
        elif action == "refine":
            if self.state == "recording" and self.session:
                self.session.effective_smart = True
                self._set_status("已切换精修：本次结束后面板确认", "recording")
            else:
                self.open_review()
        elif action == "cancel":
            self.cancel_session()
        elif action == "copy":
            self._copy_pending()
        elif action == "retry":
            self._retry_pending()
        elif action in ("review_insert",):
            self.commit_review()
        elif action == "review_copy":
            self._copy_review()
        elif action == "review_close":
            if self.review_ui:
                self.review_ui.hide()
            if self.state == "review" and self.session:
                self._end_session(self.session, cancelled=True)
        elif action == "review_restore":
            self._restore_original(payload)
        elif action == "review_rerecognize":
            self._rerecognize(payload)
        elif action == "review_rerun":
            self._rerun_refine(payload)
        elif action == "review_deep":
            self._rerun_refine(payload, level="deep")
        elif action == "review_refine_selection":
            self._refine_selection()

    def commit_review(self) -> None:
        session = self.session
        if session is None:
            return
        segments = [s for s in session.segments if s.commit_status != "committed"]
        text = compose_text(segments)
        if not text:
            if self.review_ui:
                self.review_ui.set_status("没有待插入的文字")
            return
        self.state = "processing"
        threading.Thread(target=self._commit_review_worker, args=(session, segments, text), daemon=True).start()

    def _commit_review_worker(self, session: Session, segments: list[Segment], text: str) -> None:
        separator = ""
        if session.inserted_text and session.inserted_text[-1].isascii() and text[0].isascii():
            separator = " "
        tx = self.insertion.prepare(separator + text, target=session.target, mode="smart")
        tx = self.insertion.commit(tx, allow_focus_restore=True)
        if tx.ok:
            for seg in segments:
                seg.commit_status = "committed"
            session.inserted_text += separator + text
            session.transactions.append(tx)
            self._last_insert = tx
            self._post("review_committed", text=(separator + text))
        else:
            self._post("review_failed", error=tx.error)

    def _copy_review(self) -> None:
        session = self.session
        if not session:
            return
        text = compose_text([s for s in session.segments if s.commit_status != "committed"]) or compose_text(session.segments)
        if text:
            clipboard.set_text(text)
            if self.review_ui:
                self.review_ui.set_status("已复制到剪贴板")

    def _copy_pending(self) -> None:
        text = self._pending_text or (self.session.inserted_text if self.session else "")
        if text:
            clipboard.set_text(text)
            self._set_status("文字已保留并复制到剪贴板", "target_changed")

    def _retry_pending(self) -> None:
        session = self.session
        if not session:
            return
        failed = [s for s in session.segments if s.commit_status == "failed"]
        if not failed:
            return
        self.state = "processing"
        threading.Thread(target=self._retry_pending_worker, args=(session, failed), daemon=True).start()

    def _retry_pending_worker(self, session: Session, failed: list[Segment]) -> None:
        for seg in failed:
            self._commit_segment(session, seg)
        self._post("segment_done", session_id=session.id, segment_id="")

    def _undo(self) -> None:
        ok, message = self.insertion.undo_last()
        self._set_status(message, "done" if ok else "error")
        self._beep("stop" if ok else "error")

    def _restore_original(self, seg: Segment | None) -> None:
        if not seg:
            return
        seg.user_edited = ""
        seg.refined = seg.normalized
        seg.requires_review = False
        seg.bump()
        if self.review_ui:
            self.review_ui.refresh()
            self.review_ui.set_status("已恢复原文")

    def _rerecognize(self, seg: Segment | None) -> None:
        if not seg or self.reviewer is None:
            if self.review_ui:
                self.review_ui.set_status("复核模型不可用")
            return
        if seg.audio is None or seg.audio.size == 0:
            if self.review_ui:
                self.review_ui.set_status("该片段没有保留音频，无法重新识别")
            return
        if self.review_ui:
            self.review_ui.set_status("正在重新识别…")
        threading.Thread(target=self._rerecognize_worker, args=(seg,), daemon=True).start()

    def _rerecognize_worker(self, seg: Segment) -> None:
        text = self.reviewer.review(seg.audio, timeout=8.0)  # type: ignore[union-attr]
        if text:
            seg.reviewed_asr = text
            seg.normalized = self.terminology.apply(text)
            seg.refined = seg.normalized
            seg.user_edited = ""
            seg.bump()
            self._post("review_refresh")
            self._post("status", state="review", text="重新识别完成")
        else:
            self._post("status", state="review", text="重新识别失败，已保留原结果")

    def _rerun_refine(self, seg: Segment | None, level: str | None = None) -> None:
        if not seg:
            return
        if not self.llm_server.available:
            if self.review_ui:
                self.review_ui.set_status("本地 LLM 不可用")
            return
        if self.review_ui:
            self.review_ui.set_status("正在重新精修…")
        session = self.session
        context = build_context(session.segments[:-1], 3) if session else []
        self.scheduler.submit(
            seg,
            context=context,
            level=level or str((self.cfg.get("refine", {}) or {}).get("level", "standard")),
            callback=lambda _outcome: self._post("review_refresh"),
        )

    def _refine_selection(self) -> None:
        if not self.review_ui or not self.session:
            return
        selection = self.review_ui.current_selection()
        seg = self.review_ui._current_segment()
        if not selection or seg is None:
            self.review_ui.set_status("请先在文本中选择要精修的片段")
            return
        text, _start, _end = selection
        self.review_ui.set_status("正在精修选中内容…")

        def worker() -> None:
            from .guard import check_refinement

            result = self.refiner.refine(
                segment_id=seg.id,
                source_revision=seg.revision,
                text=text,
                context=[],
                level="standard",
                protected_terms=self.terminology.protected,
            )
            if not result.ok:
                self._post("status", state="review", text=f"局部精修失败：{result.error}")
                return
            guard = check_refinement(
                text,
                result.text,
                result.edits,
                protected_terms=self.terminology.protected,
                level="standard",
            )
            if not guard.ok:
                self._post("status", state="review", text="局部精修未通过语义保护，已保留原文")
                return
            self._post("selection_refined", text=result.text)

        threading.Thread(target=worker, daemon=True).start()

    def open_review(self) -> None:
        if self.session and self.review_ui:
            if self.overlay:
                self.overlay.hide()
            self.review_ui.show(
                self.session.segments,
                model_status=self._llm_label(),
                status="可编辑、重新识别或重新精修",
            )

    def _llm_label(self) -> str:
        status = self.llm_server.status()
        if status.get("running"):
            return f"LLM 已加载 · {status.get('model', '')} · {status.get('memory_mb', 0)} MB"
        if status.get("available"):
            return "LLM 按需加载"
        return "LLM 不可用"

    # ------------------------------------------------------------------ #
    # 模式 / 设置 / 引导
    # ------------------------------------------------------------------ #
    def _mode_text(self) -> str:
        return {"fast": "极速", "smart": "精修", "auto": "自动"}.get(str(self.cfg.get("mode", "auto")), "自动")

    def set_mode(self, mode: str) -> None:
        if mode not in ("fast", "smart", "auto"):
            return
        self.cfg["mode"] = mode
        try:
            save_config(self.cfg, self.config_path)
        except Exception as exc:
            log.warning("保存模式失败：%s", exc)
        if self.overlay:
            self.overlay.set_mode(mode)
        if self.tray:
            try:
                self.tray.refresh()
            except Exception:
                pass
        self._set_status(f"模式：{self._mode_text()}", "idle", sticky=True)

    def open_settings(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--settings"]
            else:
                cmd = [sys.executable, "-m", "voiceinput", "--settings"]
            if self.config_path:
                cmd += ["-c", self.config_path]
            proc = subprocess.Popen(cmd, cwd=str(paths.app_root()), close_fds=True)
        except Exception as exc:
            log.error("打开设置失败：%s", exc)
            self._set_status(f"打开设置失败：{exc}", "error", error=True)
            return

        def watch() -> None:
            if proc.wait() == SETTINGS_RESTART_EXIT:
                self._post("restart")

        threading.Thread(target=watch, daemon=True).start()

    def open_onboarding(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--onboarding"]
            else:
                cmd = [sys.executable, "-m", "voiceinput", "--onboarding"]
            proc = subprocess.Popen(cmd, cwd=str(paths.app_root()), close_fds=True)
        except Exception as exc:
            log.warning("打开首次引导失败：%s", exc)
            return

        def watch() -> None:
            if proc.wait() == SETTINGS_RESTART_EXIT:
                self._post("restart")

        threading.Thread(target=watch, daemon=True).start()

    def _on_position(self, x: int, y: int) -> None:
        self.cfg.setdefault("ui", {})["position"] = [int(x), int(y)]
        try:
            save_config(self.cfg, self.config_path)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _beep(self, kind: str) -> None:
        if not (self.cfg.get("feedback", {}) or {}).get("beep", True):
            return
        try:
            import winsound

            freq, dur = {"start": (900, 80), "stop": (600, 80), "error": (350, 200)}.get(kind, (700, 80))
            winsound.Beep(freq, dur)
        except Exception:
            pass
