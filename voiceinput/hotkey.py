"""全局热键监听（按住说话 / 按一下开始-再按结束）。"""

from __future__ import annotations

from typing import Callable

import keyboard


class PushToTalk:
    """监听单个按键。

    ``mode="hold"``  ：按住热键录音，松开结束（默认）。
    ``mode="toggle"``：按一下开始，再按一下结束。
    """

    def __init__(
        self,
        key: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        mode: str = "hold",
    ) -> None:
        self.key = key
        self.mode = mode if mode in ("hold", "toggle") else "hold"
        self._on_start = on_start
        self._on_stop = on_stop
        self._active = False

    def _handle_press(self, _event=None) -> None:
        if self.mode == "toggle":
            if self._active:
                self._active = False
                self._on_stop()
            else:
                self._active = True
                self._on_start()
            return
        if self._active:  # 忽略自动重复
            return
        self._active = True
        self._on_start()

    def _handle_release(self, _event=None) -> None:
        if self.mode == "toggle":
            return
        if not self._active:
            return
        self._active = False
        self._on_stop()

    def register(self) -> None:
        keyboard.on_press_key(self.key, self._handle_press, suppress=False)
        keyboard.on_release_key(self.key, self._handle_release, suppress=False)

    def wait(self) -> None:
        keyboard.wait()

    def run(self) -> None:
        self.register()
        self.wait()
