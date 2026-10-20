"""Windows 输入目标兼容策略。

不同窗口对“粘贴”快捷键/Unicode 直输的支持不同；这里集中维护兼容矩阵，
避免把终端、Electron、Office、经典 Edit 混为一谈。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InputStrategy:
    name: str
    paste_shortcut: str
    prefer_unicode: bool = False
    note: str = ""


DEFAULT = InputStrategy("default", "ctrl+v", False, "标准 Ctrl+V 粘贴")
TERMINAL = InputStrategy("terminal", "ctrl+shift+v", False, "终端使用 Ctrl+Shift+V 粘贴")
TERMINAL_LEGACY = InputStrategy("terminal-legacy", "shift+insert", False, "经典控制台使用 Shift+Insert 粘贴")
TYPE_ONLY = InputStrategy("type", "", True, "Unicode 直输（不占用剪贴板）")


_TERMINAL_CLASSES = {
    "cascadia_hosting_window_class": TERMINAL,
    "consolewindowclass": TERMINAL_LEGACY,
    "virtualconsoleclass": TERMINAL,
    "mintty": TERMINAL_LEGACY,
    "putty": TERMINAL_LEGACY,
    "windowsterminal": TERMINAL,
}
_TERMINAL_EXES = {
    "windowsterminal.exe": TERMINAL,
    "wt.exe": TERMINAL,
    "conhost.exe": TERMINAL_LEGACY,
    "cmd.exe": TERMINAL_LEGACY,
    "powershell.exe": TERMINAL_LEGACY,
    "pwsh.exe": TERMINAL_LEGACY,
    "mintty.exe": TERMINAL_LEGACY,
    "putty.exe": TERMINAL_LEGACY,
}


def resolve(target: Any, mode: str = "auto") -> InputStrategy:
    """根据目标窗口/进程与用户配置选择插入策略。"""
    mode = (mode or "auto").lower()
    if mode == "type":
        return TYPE_ONLY
    if mode == "paste":
        return DEFAULT
    if target is None:
        return DEFAULT
    cls = str(getattr(target, "class_name", "") or "").lower()
    exe = str(getattr(target, "exe", "") or "").lower()
    title = str(getattr(target, "title", "") or "").lower()
    for key, strategy in _TERMINAL_CLASSES.items():
        if key and key in cls:
            return strategy
    for key, strategy in _TERMINAL_EXES.items():
        if key and key == exe:
            return strategy
    if "windows terminal" in title:
        return TERMINAL
    return DEFAULT


def describe_matrix() -> list[dict[str, str]]:
    return [
        {"target": "Windows Terminal / Cascadia", "method": "Ctrl+Shift+V", "note": "剪贴板粘贴"},
        {"target": "conhost / cmd / PowerShell", "method": "Shift+Insert", "note": "经典控制台粘贴"},
        {"target": "Notepad / Edit / RichEdit", "method": "Ctrl+V", "note": "默认"},
        {"target": "VS Code / Electron / Chrome", "method": "Ctrl+V", "note": "默认"},
        {"target": "Office / WPS", "method": "Ctrl+V", "note": "默认"},
        {"target": "剪贴板含非文本格式", "method": "Unicode 直输", "note": "不修改剪贴板"},
        {"target": "用户配置 type", "method": "Unicode 直输", "note": "不占用剪贴板"},
    ]
