"""输入目标窗口跟踪与安全校验。

只记录窗口句柄、进程、标题、焦点控件，不读取目标应用内容。
插入前必须确认目标仍是当初捕获的窗口/输入框；焦点变化时拒绝盲目提交。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.SetFocus.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

advapi32.OpenProcessToken.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL


def _class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(hwnd, buf, 256)
    except Exception:
        return ""
    return buf.value


def _window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    try:
        user32.GetWindowTextW(hwnd, buf, 512)
    except Exception:
        return ""
    return buf.value


def _process_exe(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
    finally:
        kernel32.CloseHandle(handle)
    return ""


def is_process_elevated(pid: int) -> bool:
    """判断目标进程是否以管理员权限运行（用于 UIPI 提前提示）。"""
    if not pid:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    token = ctypes.c_void_p()
    try:
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return False
        value = wintypes.DWORD(0)
        returned = wintypes.DWORD(0)
        ok = advapi32.GetTokenInformation(
            token,
            TOKEN_ELEVATION,
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(returned),
        )
        return bool(ok and value.value)
    except Exception:
        return False
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(handle)


def current_process_elevated() -> bool:
    return is_process_elevated(__import__("os").getpid())


@dataclass
class WindowTarget:
    hwnd: int
    pid: int
    exe: str
    title: str
    class_name: str
    focus_hwnd: int = 0
    focus_class: str = ""
    elevated: bool = False
    captured_at: float = field(default_factory=time.time)

    def is_alive(self) -> bool:
        return bool(self.hwnd and user32.IsWindow(self.hwnd))

    def is_current(self) -> bool:
        if not self.is_alive():
            return False
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground != self.hwnd:
            return False
        if self.focus_hwnd:
            info = _gui_thread_info(self.hwnd)
            if info and info.hwndFocus and int(info.hwndFocus) != self.focus_hwnd:
                return False
        return True

    def describe(self) -> str:
        name = self.exe or self.class_name or "未知应用"
        title = self.title.strip()
        if len(title) > 40:
            title = title[:40] + "…"
        return f"{name} · {title}" if title else name

    def to_dict(self) -> dict:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "exe": self.exe,
            "title": self.title,
            "class_name": self.class_name,
            "focus_hwnd": self.focus_hwnd,
            "focus_class": self.focus_class,
            "elevated": self.elevated,
            "captured_at": self.captured_at,
        }


def _gui_thread_info(hwnd: int) -> GUITHREADINFO | None:
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not tid:
        return None
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return None
    return info


def capture_target() -> WindowTarget | None:
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    info = _gui_thread_info(hwnd)
    focus = int(info.hwndFocus) if info and info.hwndFocus else 0
    return WindowTarget(
        hwnd=hwnd,
        pid=int(pid.value),
        exe=_process_exe(int(pid.value)),
        title=_window_title(hwnd),
        class_name=_class_name(hwnd),
        focus_hwnd=focus,
        focus_class=_class_name(focus),
        elevated=is_process_elevated(int(pid.value)),
    )


def focus_target(target: WindowTarget, timeout: float = 0.8) -> bool:
    """把焦点恢复到捕获时的窗口/控件，返回是否成功。

    使用 AttachThreadInput 绕过前台窗口锁定；不会向错误窗口发送文字。
    """
    if not target or not target.is_alive():
        return False
    if target.is_current():
        return True
    try:
        user32.ShowWindow(target.hwnd, 9)  # SW_RESTORE
    except Exception:
        pass
    current_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(target.hwnd, None)
    attached = False
    try:
        if current_tid != target_tid:
            attached = bool(user32.AttachThreadInput(current_tid, target_tid, True))
        user32.BringWindowToTop(target.hwnd)
        user32.SetForegroundWindow(target.hwnd)
        if target.focus_hwnd:
            user32.SetFocus(target.focus_hwnd)
    except Exception:
        pass
    finally:
        if attached:
            try:
                user32.AttachThreadInput(current_tid, target_tid, False)
            except Exception:
                pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.is_current():
            return True
        time.sleep(0.03)
    # 焦点控件不同但顶层窗口一致时，允许继续（部分应用会重建控件）
    return int(user32.GetForegroundWindow() or 0) == target.hwnd
