"""系统托盘：状态、模式切换、设置/引导入口。"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

log = logging.getLogger("voiceinput.tray")

_COLORS = {
    "idle": (120, 124, 130),
    "recording": (220, 60, 60),
    "processing": (230, 180, 40),
    "error": (200, 40, 130),
}
_MODE_TEXT = {"fast": "极速输入", "smart": "智能精修", "auto": "自动"}


def _icon_image(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=color)
    cx = size / 2
    d.rounded_rectangle((cx - 7, 16, cx + 7, 38), radius=7, fill=(255, 255, 255))
    d.arc((cx - 14, 26, cx + 14, 50), start=0, end=180, fill=(255, 255, 255), width=3)
    d.line((cx, 48, cx, 54), fill=(255, 255, 255), width=3)
    return img


class TrayController:
    def __init__(
        self,
        title: str,
        on_quit: Callable[[], None],
        on_open_settings: Optional[Callable[[], None]] = None,
        on_set_mode: Optional[Callable[[str], None]] = None,
        mode: Optional[Callable[[], str]] = None,
        on_open_panel: Optional[Callable[[], None]] = None,
        on_open_onboarding: Optional[Callable[[], None]] = None,
        on_undo: Optional[Callable[[], None]] = None,
        on_restart: Optional[Callable[[], None]] = None,
        on_check_update: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_quit = on_quit
        self._on_open_settings = on_open_settings
        self._on_set_mode = on_set_mode
        self._mode = mode
        self._on_open_panel = on_open_panel
        self._on_open_onboarding = on_open_onboarding
        self._on_undo = on_undo
        self._on_restart = on_restart
        self._on_check_update = on_check_update
        self._info_lines: list[str] = []
        self._icon = pystray.Icon(
            "LocalVoiceInput",
            _icon_image(_COLORS["idle"]),
            title,
            menu=self._build_menu(),
        )

    def _build_menu(self) -> pystray.Menu:
        items: list = []
        for line in self._info_lines:
            items.append(pystray.MenuItem(line, None, enabled=False))
        if self._info_lines:
            items.append(pystray.Menu.SEPARATOR)
        if self._on_open_panel:
            items.append(pystray.MenuItem("打开精修面板", lambda: self._on_open_panel(), default=True))
        if self._on_set_mode:
            items.append(
                pystray.MenuItem(
                    "输入模式",
                    pystray.Menu(
                        *[
                            pystray.MenuItem(
                                label,
                                (lambda m=key: self._on_set_mode(m)),
                                checked=(lambda _i, k=key: bool(self._mode and self._mode() == k)),
                                radio=True,
                            )
                            for key, label in (("fast", "极速输入"), ("smart", "智能精修"), ("auto", "自动"))
                        ]
                    ),
                )
            )
        if self._on_undo:
            items.append(pystray.MenuItem("撤销上次上屏", lambda: self._on_undo()))
        items.append(pystray.Menu.SEPARATOR)
        if self._on_open_settings:
            items.append(pystray.MenuItem("设置…", lambda: self._on_open_settings()))
        if self._on_open_onboarding:
            items.append(pystray.MenuItem("首次引导…", lambda: self._on_open_onboarding()))
        items.append(pystray.Menu.SEPARATOR)
        if self._on_check_update:
            items.append(pystray.MenuItem("检查更新…", lambda: self._on_check_update()))
        if self._on_restart:
            items.append(pystray.MenuItem("重启程序", lambda: self._on_restart()))
        items.append(pystray.MenuItem("退出", lambda: self._on_quit()))
        return pystray.Menu(*items)

    def refresh(self) -> None:
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:
            pass

    def set_info(self, lines: list[str]) -> None:
        self._info_lines = list(lines)
        self.refresh()

    def set_status(self, status: str, tooltip: str | None = None, info: list[str] | None = None) -> None:
        try:
            self._icon.icon = _icon_image(_COLORS.get(status, _COLORS["idle"]))
            if tooltip:
                self._icon.title = tooltip
            if info is not None:
                self._info_lines = list(info)
                self.refresh()
        except Exception:
            pass

    def run(self) -> None:
        self._icon.run()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
