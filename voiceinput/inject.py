"""把识别结果输入到当前光标处。"""

from __future__ import annotations

import time
from typing import Optional

import keyboard
import pyperclip


def _read_clipboard() -> Optional[str]:
    try:
        return pyperclip.paste()
    except Exception:
        return None


def _write_clipboard(text: str) -> None:
    pyperclip.copy(text)


def insert_text(
    text: str,
    method: str = "paste",
    restore_clipboard: bool = True,
    restore_delay: float = 0.2,
) -> None:
    """将 ``text`` 插入到当前焦点处。

    默认使用「剪贴板 + Ctrl+V」，对中文和多输入法环境最可靠；
    粘贴完成后会把剪贴板还原为原内容。
    """
    if not text:
        return

    if method == "type":
        # 仅适用于纯 ASCII；中文请使用 paste。
        keyboard.write(text, delay=0.005)
        return

    old = _read_clipboard() if restore_clipboard else None
    _write_clipboard(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")

    if restore_clipboard and old is not None:
        time.sleep(restore_delay)
        try:
            _write_clipboard(old)
        except Exception:
            pass
