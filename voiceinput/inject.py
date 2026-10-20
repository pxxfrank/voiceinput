"""全局文字插入：输入事务、目标校验、剪贴板保护、Unicode 直输回退。"""

from __future__ import annotations

import ctypes
import logging
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any, Callable

import keyboard

from . import clipboard, compat
from .target import WindowTarget, current_process_elevated, focus_target

log = logging.getLogger("voiceinput.input")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def type_unicode(text: str, interval: float = 0.001) -> bool:
    """通过 SendInput 直接输入 Unicode 字符（不占用剪贴板）。

    对普通编辑器、浏览器、Office 可用；终端/游戏等不保证。
    """
    units = text.encode("utf-16-le")
    ok = True
    count = 0
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i : i + 2], "little")
        if code in (0x000A, 0x000D):
            events = [(VK_RETURN, 0), (VK_RETURN, KEYEVENTF_KEYUP)]
        else:
            events = [(0, KEYEVENTF_UNICODE), (0, KEYEVENTF_KEYUP | KEYEVENTF_UNICODE)]
        for vk, flags in events:
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.wScan = 0 if vk else code
            inp.ki.dwFlags = flags
            inp.ki.time = 0
            inp.ki.dwExtraInfo = 0
            if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp)) != 1:
                ok = False
        count += 1
        if count % 20 == 0:
            time.sleep(interval)
    return ok


@dataclass
class InputTransaction:
    text: str
    target: WindowTarget | None = None
    mode: str = "fast"
    id: str = field(default_factory=lambda: "tx_" + uuid.uuid4().hex[:12])
    status: str = "prepared"  # prepared | committed | failed | target_changed | cancelled
    method: str = ""
    strategy: str = ""
    error: str = ""
    warning: str = ""
    created_at: float = field(default_factory=time.time)
    committed_at: float = 0.0
    clipboard_restored: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "committed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "method": self.method,
            "strategy": self.strategy,
            "error": self.error,
            "warning": self.warning,
            "target": self.target.to_dict() if self.target else None,
            "text_len": len(self.text),
            "created_at": self.created_at,
            "committed_at": self.committed_at,
            "clipboard_restored": self.clipboard_restored,
        }


class TextInsertionService:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        output = cfg.get("output", {}) or {}
        self.method = str(output.get("method", "paste"))
        self.restore_clipboard = bool(output.get("restore_clipboard", True))
        self.append_space = bool(output.get("append_space", False))
        self.append_newline = bool(output.get("append_newline", False))
        self.verify_target = bool(output.get("verify_target", True))
        self.type_fallback = bool(output.get("type_fallback", True))
        self.compat_mode = str(output.get("compat_mode", "auto") or "auto")
        self.current_elevated = current_process_elevated()
        self.last_transaction: InputTransaction | None = None
        self.history: list[InputTransaction] = []

    def payload(self, text: str) -> str:
        if self.append_space:
            text += " "
        if self.append_newline:
            text += "\n"
        return text

    def prepare(self, text: str, *, target: WindowTarget | None = None, mode: str = "fast") -> InputTransaction:
        tx = InputTransaction(text=self.payload(text), target=target, mode=mode)
        self.last_transaction = tx
        self.history.append(tx)
        if len(self.history) > 50:
            self.history = self.history[-50:]
        return tx

    def _target_ok(self, tx: InputTransaction, *, force: bool = False, allow_focus_restore: bool = False) -> tuple[bool, str]:
        if not self.verify_target or force:
            return True, ""
        if tx.target is None:
            return False, "无法确定输入目标，请先点击目标输入框后重试。"
        if not tx.target.is_alive():
            return False, "目标窗口已关闭，文字已保留。"
        if getattr(tx.target, "elevated", False) and not self.current_elevated:
            return False, "目标窗口以管理员权限运行，当前程序权限不足；请以管理员身份运行本程序后重试。"
        if not tx.target.is_current():
            # 自动提交绝不抢焦点；只有用户显式确认“插入到原窗口”才恢复焦点
            if allow_focus_restore and focus_target(tx.target):
                return True, ""
            return False, "输入焦点已改变，已暂停提交；文字已保留，可复制或选择插入到原窗口。"
        return True, ""

    def commit(
        self,
        tx: InputTransaction,
        *,
        force: bool = False,
        allow_focus_restore: bool = False,
    ) -> InputTransaction:
        if tx.status == "committed":
            return tx
        if not tx.text:
            tx.status = "failed"
            tx.error = "没有可提交的文字"
            return tx
        ok, error = self._target_ok(tx, force=force, allow_focus_restore=allow_focus_restore)
        if not ok:
            tx.status = "target_changed" if "焦点" in error else "failed"
            tx.error = error
            log.warning("提交被拒绝：%s", error)
            return tx

        strategy = compat.resolve(tx.target, self.compat_mode)
        tx.strategy = strategy.name
        method = "type" if strategy.prefer_unicode else self.method
        snap = None
        seq = None
        try:
            if method == "paste":
                if self.restore_clipboard:
                    snap = clipboard.snapshot()
                    if not snap.complete:
                        if self.type_fallback:
                            method = "type"
                            snap = None
                            tx.warning = "剪贴板含无法安全恢复的格式，已改用直接输入；原剪贴板未被修改。"
                        else:
                            tx.status = "failed"
                            tx.error = "剪贴板含无法安全恢复的格式，已取消粘贴以避免数据丢失。"
                            return tx
                if method == "paste":
                    seq = clipboard.set_text(tx.text)
                    if seq is None:
                        if self.type_fallback:
                            method = "type"
                            snap = None
                            tx.warning = "剪贴板被其他程序占用，已改用直接输入。"
                        else:
                            tx.status = "failed"
                            tx.error = "无法写入剪贴板"
                            return tx
                    else:
                        time.sleep(0.03)
                        keyboard.send(strategy.paste_shortcut or "ctrl+v")
                        time.sleep(0.16)

            if method == "type":
                if not type_unicode(tx.text):
                    tx.status = "failed"
                    tx.error = "直接输入失败（目标应用可能不接受 Unicode 输入）"
                    return tx

            # 粘贴后目标可能被切换；文字可能已进入目标，记录警告但不重复提交
            if self.verify_target and tx.target and not tx.target.is_current():
                tx.warning = (tx.warning + "；" if tx.warning else "") + "提交期间焦点发生变化，请核对结果。"

            # 只有在剪贴板仍由本次操作占用时才恢复
            if snap is not None and seq is not None and self.restore_clipboard:
                if clipboard.still_ours(seq, tx.text):
                    tx.clipboard_restored = clipboard.restore(snap)
                    if not tx.clipboard_restored:
                        tx.warning = (tx.warning + "；" if tx.warning else "") + "原剪贴板未能完整恢复。"
                else:
                    tx.warning = (tx.warning + "；" if tx.warning else "") + "剪贴板已被其他程序更新，未覆盖。"

            tx.status = "committed"
            tx.method = method
            tx.committed_at = time.time()
            log.info("已提交 %d 字（%s）", len(tx.text), method)
            return tx
        except Exception as exc:
            tx.status = "failed"
            tx.error = str(exc)
            log.exception("文字提交失败")
            return tx

    def cancel(self, tx: InputTransaction | None = None) -> None:
        tx = tx or self.last_transaction
        if tx and tx.status == "prepared":
            tx.status = "cancelled"

    def undo_last(self) -> tuple[bool, str]:
        tx = self.last_transaction
        if not tx or tx.status != "committed":
            return False, "没有可撤销的输入"
        if time.time() - tx.committed_at > 60:
            return False, "上一次输入已超过 60 秒，无法撤销"
        if tx.target and not tx.target.is_current():
            if not focus_target(tx.target):
                return False, "无法回到原输入窗口，未执行撤销"
        length = len(tx.text)
        if length > 300:
            keyboard.send("ctrl+z")
        else:
            for _ in range(length):
                keyboard.send("backspace")
        tx.status = "cancelled"
        return True, f"已撤销 {length} 个字符"
