"""本地 LLM 精修：由主程序管理的 llama.cpp 子进程 + 结构化输出。

- 只监听 127.0.0.1，随机端口，不暴露局域网，不联网。
- 生命周期由主程序管理：按需启动、健康检查、崩溃重启、退出清理、空闲卸载。
- 通过 Windows Job Object 保证主程序异常退出时子进程被一并回收。
"""

from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import modelstore

log = logging.getLogger("voiceinput.llm")

CREATE_NO_WINDOW = 0x08000000

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "segment_id": {"type": "string"},
        "source_revision": {"type": "integer"},
        "revised_text": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "replacement": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["source", "replacement", "reason"],
            },
        },
        "requires_review": {"type": "boolean"},
    },
    "required": ["segment_id", "source_revision", "revised_text", "edits", "requires_review"],
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(url: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def process_memory_mb(pid: int) -> float:
    try:
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        handle = kernel32.OpenProcess(0x1000 | 0x0400, False, int(pid))
        if not handle:
            return 0.0
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return round(counters.WorkingSetSize / (1024 * 1024), 1)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return 0.0


class _JobObject:
    """KILL_ON_JOB_CLOSE：父进程退出/崩溃时子进程一并结束。"""

    def __init__(self) -> None:
        self.handle = None
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            kernel32.SetInformationJobObject.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return
            # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            class BASIC(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong),
                ]

            class EXT(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", BASIC),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = EXT()
            info.BasicLimitInformation.LimitFlags = 0x2000
            kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
            self.handle = handle
        except Exception:
            self.handle = None

    def assign(self, pid: int) -> None:
        if not self.handle:
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            proc = kernel32.OpenProcess(0x0100 | 0x0400, False, int(pid))
            if proc:
                ok = kernel32.AssignProcessToJobObject(self.handle, proc)
                if not ok:
                    log.debug("AssignProcessToJobObject 受限（将由看门狗兜底）：%s", ctypes.get_last_error())
                kernel32.CloseHandle(proc)
        except Exception:
            pass


_JOB = _JobObject()


@dataclass
class RefineResponse:
    ok: bool
    text: str = ""
    edits: list[dict[str, Any]] = field(default_factory=list)
    requires_review: bool = False
    error: str = ""
    latency_ms: float = 0.0
    raw: str = ""
    source: str = "llm"


class LlamaServer:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        refine = cfg.get("refine", {}) or {}
        self.context = int(refine.get("context", 2048))
        configured_threads = int(refine.get("threads", 0) or 0)
        if configured_threads <= 0:
            configured_threads = min(12, max(4, (os.cpu_count() or 8) // 3))
        self.threads = configured_threads
        self.idle_unload_s = float(refine.get("idle_unload_s", 900) or 0)
        self.model_path = modelstore.find_llm_model(cfg)
        self.server_path = modelstore.find_llama_server(cfg)
        self._proc: subprocess.Popen | None = None
        self._log_handle = None
        self._err_handle = None
        self._lock = threading.RLock()
        self._port = 0
        self._load_seconds = 0.0
        self._last_used = 0.0
        self._started_at = 0.0
        self._idle_stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        self._last_error = ""
        self._restarts = 0
        # 该 llama.cpp 版本的 json_schema 约束解码会退化（生成重复 token），
        # 统一使用 json_object + 应用层校验。
        self._schema_supported = False
        self._preloaded = False
        atexit.register(self.stop)

    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return bool(self.model_path and self.model_path.exists() and self.server_path and self.server_path.exists())

    @property
    def running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def status(self) -> dict[str, Any]:
        pid = self._proc.pid if self.running else 0
        return {
            "available": self.available,
            "running": self.running,
            "model": self.model_path.name if self.model_path else "",
            "model_path": str(self.model_path or ""),
            "server": str(self.server_path or ""),
            "port": self._port,
            "pid": pid,
            "load_seconds": round(self._load_seconds, 2),
            "memory_mb": process_memory_mb(pid) if pid else 0.0,
            "last_error": self._last_error,
            "restarts": self._restarts,
            "idle_seconds": round(time.time() - self._last_used, 1) if self._last_used else 0.0,
            "device": "CPU",
        }

    def _log_tail(self, limit: int = 2500) -> str:
        if not self._log_handle:
            return ""
        try:
            path = Path(self._log_handle.name)
            data = path.read_text(encoding="utf-8", errors="ignore")
            return data[-limit:]
        except Exception:
            return ""

    def start(self, timeout: float = 90.0) -> None:
        with self._lock:
            if self.running:
                return
            if not self.available:
                raise FileNotFoundError(
                    "本地 LLM 运行时不完整：未找到 llama-server.exe 或 GGUF 模型。"
                )
            self._port = _free_port()
            log_path = _server_log_path()
            try:
                self._log_handle = log_path.open("ab")
                self._err_handle = subprocess.STDOUT
            except Exception:
                self._log_handle = None
            cmd = [
                str(self.server_path),
                "-m",
                str(self.model_path),
                "-c",
                str(self.context),
                "-t",
                str(self.threads),
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
                "--no-webui",
                "--jinja",
                "-ngl",
                "0",
                "--parallel",
                "1",
            ]
            log.info("启动 llama-server：%s", " ".join(cmd[:3]))
            t0 = time.time()
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.server_path.parent),
                    stdout=self._log_handle,
                    stderr=self._err_handle,
                    creationflags=CREATE_NO_WINDOW,
                    close_fds=False,
                )
            except Exception as exc:
                self._last_error = f"启动失败：{exc}"
                raise
            _JOB.assign(self._proc.pid)
            self._start_watchdog(self._proc.pid)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    self._last_error = f"llama-server 退出（code={self._proc.returncode}）：{self._log_tail(800)}"
                    raise RuntimeError(self._last_error)
                try:
                    health = _http_json(f"http://127.0.0.1:{self._port}/health", timeout=2.0)
                    if health.get("status") == "ok":
                        self._load_seconds = time.time() - t0
                        self._started_at = time.time()
                        self._last_used = time.time()
                        self._last_error = ""
                        log.info("llama-server 就绪：%.2fs，端口 %d", self._load_seconds, self._port)
                        self._start_idle_thread()
                        return
                except Exception:
                    pass
                time.sleep(0.25)
            self.stop()
            self._last_error = f"llama-server 启动超时（{timeout:.0f}s）：{self._log_tail(800)}"
            raise TimeoutError(self._last_error)

    def _start_watchdog(self, child_pid: int) -> None:
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--watchdog", str(os.getpid()), str(child_pid)]
            else:
                cmd = [sys.executable, "-m", "voiceinput", "--watchdog", str(os.getpid()), str(child_pid)]
            subprocess.Popen(
                cmd,
                cwd=str(modelstore.paths.app_root()),
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
        except Exception as exc:
            log.warning("启动 llama 看门狗失败：%s", exc)

    def _start_idle_thread(self) -> None:
        if self.idle_unload_s <= 0 or self._idle_thread:
            return
        self._idle_stop.clear()

        def loop() -> None:
            while not self._idle_stop.wait(30.0):
                if not self.running:
                    return
                if time.time() - self._last_used > self.idle_unload_s:
                    log.info("LLM 空闲超过 %.0fs，卸载模型", self.idle_unload_s)
                    self.stop()
                    return

        self._idle_thread = threading.Thread(target=loop, name="llm-idle", daemon=True)
        self._idle_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._idle_stop.set()
            proc = self._proc
            self._proc = None
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if self._log_handle:
                try:
                    self._log_handle.close()
                except Exception:
                    pass
            self._log_handle = None
            self._idle_thread = None
            self._port = 0

    def ensure_running(self) -> None:
        if not self.running:
            self.start()

    def chat(self, messages: list[dict], *, timeout: float = 30.0, max_tokens: int = 512,
             temperature: float = 0.2, response_format: dict | None = None,
             cache_prompt: bool = True) -> str:
        self.ensure_running()
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": int(max_tokens),
            "stream": False,
            "cache_prompt": bool(cache_prompt),
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if response_format:
            payload["response_format"] = response_format
        try:
            data = _http_json(
                f"http://127.0.0.1:{self._port}/v1/chat/completions",
                payload,
                timeout=timeout,
            )
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                pass
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        self._last_used = time.time()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM 返回为空：{str(data)[:300]}")
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")

    def preload(self) -> None:
        if self._preloaded:
            return
        self._preloaded = True
        try:
            self.start()
            # 预热一次极短请求，避免用户第一次精修等待 prompt 处理/图分配
            self.chat(
                [{"role": "user", "content": "只回复 OK"}],
                timeout=30.0,
                max_tokens=4,
                temperature=0.0,
                cache_prompt=False,
            )
            log.info("LLM 预热完成")
        except Exception as exc:
            log.warning("LLM 预加载失败：%s", exc)
            self._last_error = str(exc)


def _server_log_path() -> Path:
    from . import paths

    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    return paths.logs_dir() / "llm-server.log"


class Refiner:
    """面向片段的精修请求：提示词、JSON 协议、解析、重试。"""

    SYSTEM = (
        '只输出 JSON 对象：{"revised_text":"...","edits":[],"requires_review":false}。'
        "revised_text 是用户这段口述文字整理后的结果，不能包含任何说明、字段名或标签。"
        "做最小必要整理，保留原意、数字与“大概/可能/似乎/也许/应该”等表达；"
        "不得添加原文没有的事实、数字或专名；数字、英文术语、受保护术语原样保留。"
        "edits 只列改变语义或术语的修改；仅标点/去口头禅时用空数组。"
    )

    def __init__(self, cfg: dict[str, Any], server: LlamaServer) -> None:
        self.cfg = cfg
        self.server = server
        refine = cfg.get("refine", {}) or {}
        self.enabled = bool(refine.get("enabled", True))
        self.timeout_s = float(refine.get("timeout_s", 12.0))
        self.max_tokens = int(refine.get("max_tokens", 512))
        self.temperature = float(refine.get("temperature", 0.2))

    def refine(
        self,
        *,
        segment_id: str,
        source_revision: int,
        text: str,
        context: list[str] | None = None,
        level: str = "standard",
        protected_terms: list[str] | None = None,
        timeout: float | None = None,
    ) -> RefineResponse:
        if not self.enabled:
            return RefineResponse(False, error="LLM 已关闭", source="disabled")
        if not text.strip():
            return RefineResponse(False, error="空文本", source="empty")
        payload = {
            "segment_id": segment_id,
            "source_revision": int(source_revision),
            "level": level,
            "text": text.strip(),
            "context": list(context or [])[-3:],
            "protected_terms": list(protected_terms or []),
        }
        context_text = "\n".join(f"- {c}" for c in payload["context"]) or "（无）"
        terms = "、".join(payload["protected_terms"]) or "（无）"
        user = (
            f"口述文字：{payload['text']}\n"
            f"上文（只读，不要合并进结果）：\n{context_text}\n"
            f"受保护术语：{terms}\n"
            f"level={level}。只输出约定的 JSON。"
        )
        messages = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": user},
        ]
        t0 = time.time()
        raw = ""
        response_format = {"type": "json_object"}
        try:
            raw = self.server.chat(
                messages,
                timeout=timeout or self.timeout_s,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format=response_format,
            )
            parsed = self._parse(raw, segment_id, source_revision)
            if parsed is not None:
                parsed.latency_ms = (time.time() - t0) * 1000
                parsed.raw = raw
                return parsed
        except Exception as exc:
            msg = str(exc)
            log.warning("精修请求失败：%s", msg)
            return RefineResponse(False, error=msg, latency_ms=(time.time() - t0) * 1000, raw=raw)

        # 第二次：json_object + 更严格指令
        try:
            raw = self.server.chat(
                messages
                + [
                    {
                        "role": "user",
                        "content": "上次输出不是合法 JSON。请只输出符合协议的 JSON 对象，不要任何其他文字。",
                    }
                ],
                timeout=timeout or self.timeout_s,
                max_tokens=self.max_tokens,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = self._parse(raw, segment_id, source_revision)
            if parsed is not None:
                parsed.latency_ms = (time.time() - t0) * 1000
                parsed.raw = raw
                return parsed
        except Exception as exc:
            return RefineResponse(
                False,
                error=str(exc),
                latency_ms=(time.time() - t0) * 1000,
                raw=raw,
            )
        return RefineResponse(
            False,
            error="模型输出无法解析为合法 JSON",
            latency_ms=(time.time() - t0) * 1000,
            raw=raw,
        )

    @staticmethod
    def _parse(raw: str, segment_id: str, revision: int) -> RefineResponse | None:
        text = (raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        if "segment_id" in obj and str(obj.get("segment_id")) != str(segment_id):
            return RefineResponse(False, error="segment_id 不匹配", source="invalid")
        if "source_revision" in obj:
            try:
                if int(obj.get("source_revision")) != int(revision):
                    return RefineResponse(False, error="source_revision 不匹配", source="invalid")
            except (TypeError, ValueError):
                return RefineResponse(False, error="source_revision 非法", source="invalid")
        revised = str(obj.get("revised_text", "") or "").strip()
        for prefix in ("口述文字：", "口述文字:", "原文：", "原文:"):
            if revised.startswith(prefix):
                revised = revised[len(prefix) :].strip()
        if not revised:
            return RefineResponse(False, error="revised_text 为空", source="invalid")
        if any(marker in revised for marker in ("revised_text", "requires_review", "上文（只读", "level=")):
            return RefineResponse(False, error="模型把说明/字段名写进了结果", source="invalid")
        edits = obj.get("edits") or []
        if not isinstance(edits, list):
            edits = []
        return RefineResponse(
            True,
            text=revised,
            edits=[e for e in edits if isinstance(e, dict)],
            requires_review=bool(obj.get("requires_review", False)),
        )
