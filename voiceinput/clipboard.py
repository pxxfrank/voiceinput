"""剪贴板快照/恢复与占用校验。

原则：
- 不无条件清空用户剪贴板；
- 只有能证明剪贴板仍由本次操作占用（序列号未变）时才恢复；
- 非文本格式无法完整复制时，报告 incomplete，调用方改用 Unicode 直输，避免丢数据。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, field

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17

GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p

_SYNTHETIC = {CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE, 0x80}


@dataclass
class ClipboardSnapshot:
    formats: dict[int, bytes] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    text: str = ""
    complete: bool = True
    seq: int = 0

    @property
    def format_names(self) -> list[str]:
        return [self.names.get(fmt, str(fmt)) for fmt in self.formats]


def _open(retries: int = 12, delay: float = 0.015) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def _format_name(fmt: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if user32.GetClipboardFormatNameW(fmt, buf, 256):
        return buf.value
    return str(fmt)


def get_sequence() -> int:
    return int(user32.GetClipboardSequenceNumber())


def get_text() -> str:
    if not _open():
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def snapshot() -> ClipboardSnapshot:
    snap = ClipboardSnapshot(seq=get_sequence())
    if not _open():
        snap.complete = False
        return snap
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            name = _format_name(fmt)
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            size = int(kernel32.GlobalSize(handle))
            if size <= 0:
                # 句柄型格式（位图/图元文件等）无法用 GMEM 复制
                if fmt in _SYNTHETIC:
                    snap.complete = False
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                snap.complete = False
                continue
            try:
                data = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
            snap.formats[fmt] = data
            snap.names[fmt] = name
        snap.text = snap_text()
    finally:
        user32.CloseClipboard()
    return snap


def snap_text() -> str:
    """在已打开剪贴板的情况下读取文本（内部使用）。"""
    handle = user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return ""
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return ""
    try:
        return ctypes.wstring_at(ptr)
    finally:
        kernel32.GlobalUnlock(handle)


def set_text(text: str) -> int | None:
    """写入 Unicode 文本，返回写入并关闭剪贴板后的序列号。"""
    if not _open():
        return None
    ok = False
    try:
        if not user32.EmptyClipboard():
            return None
        data = (str(text) + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        ok = bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()
    if not ok:
        return None
    # 关闭剪贴板后序列号才稳定
    time.sleep(0.01)
    return get_sequence()


def restore(snap: ClipboardSnapshot) -> bool:
    """恢复快照。仅在调用方确认剪贴板仍被本次操作占用时调用。"""
    if snap is None or not snap.formats or not snap.complete:
        return False
    if not _open():
        return False
    try:
        if not user32.EmptyClipboard():
            return False
        ok = True
        for fmt, data in snap.formats.items():
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                ok = False
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                ok = False
                continue
            try:
                ctypes.memmove(ptr, data, len(data))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):
                ok = False
        return ok
    finally:
        user32.CloseClipboard()


def still_ours(seq: int, text: str) -> bool:
    return get_sequence() == int(seq) and get_text() == text


def describe() -> list[str]:
    snap = snapshot()
    return snap.format_names
