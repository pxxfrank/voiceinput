"""系统托盘图标与状态显示。"""

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


def _icon_image(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=color)
    # 简化的麦克风图形
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
        on_open_config: Optional[Callable[[], None]] = None,
        on_open_models: Optional[Callable[[], None]] = None,
        on_toggle_autostart: Optional[Callable[[], None]] = None,
        is_autostart: Optional[Callable[[], bool]] = None,
        on_restart: Optional[Callable[[], None]] = None,
        on_set_caption: Optional[Callable[[str], None]] = None,
        caption_mode: Optional[Callable[[], str]] = None,
        on_set_font: Optional[Callable[[int], None]] = None,
        font_size: Optional[Callable[[], int]] = None,
    ) -> None:
        self._on_quit = on_quit
        self._on_open_settings = on_open_settings
        self._on_open_config = on_open_config
        self._on_open_models = on_open_models
        self._on_toggle_autostart = on_toggle_autostart
        self._is_autostart = is_autostart
        self._on_restart = on_restart
        self._on_set_caption = on_set_caption
        self._caption_mode = caption_mode
        self._on_set_font = on_set_font
        self._font_size = font_size
        self._info_lines: list[str] = []
        self._icon = pystray.Icon(
            "voiceinput",
            _icon_image(_COLORS["idle"]),
            title,
            menu=self._build_menu(),
        )

    def _build_menu(self) -> pystray.Menu:
        items = []
        for line in self._info_lines:
            items.append(pystray.MenuItem(line, None, enabled=False))
        if self._info_lines:
            items.append(pystray.Menu.SEPARATOR)
        if self._on_open_settings:
            items.append(pystray.MenuItem("设置…", lambda: self._on_open_settings(), default=True))
        if self._on_open_config:
            items.append(pystray.MenuItem("打开配置文件", lambda: self._on_open_config()))
        if self._on_open_models:
            items.append(pystray.MenuItem("打开模型目录", lambda: self._on_open_models()))
        if self._on_set_caption:
            items.append(
                pystray.MenuItem(
                    "字幕",
                    pystray.Menu(
                        pystray.MenuItem(
                            "悬浮字幕（2 行）",
                            lambda: self._on_set_caption("show"),
                            checked=lambda _i: self._caption_mode() == "show",
                            radio=True,
                        ),
                        pystray.MenuItem(
                            "字幕窗口（全部字幕）",
                            lambda: self._on_set_caption("window"),
                            checked=lambda _i: self._caption_mode() == "window",
                            radio=True,
                        ),
                        pystray.MenuItem(
                            "仅录音指示点",
                            lambda: self._on_set_caption("dot"),
                            checked=lambda _i: self._caption_mode() == "dot",
                            radio=True,
                        ),
                        pystray.MenuItem(
                            "关闭",
                            lambda: self._on_set_caption("off"),
                            checked=lambda _i: self._caption_mode() == "off",
                            radio=True,
                        ),
                    ),
                )
            )
        if self._on_set_font:
            items.append(
                pystray.MenuItem(
                    "字幕大小",
                    pystray.Menu(
                        *[
                            pystray.MenuItem(
                                label,
                                (lambda s=value: self._on_set_font(s)),
                                checked=(lambda _i, v=value: self._font_size() == v),
                                radio=True,
                            )
                            for label, value in (("小", 13), ("中", 15), ("大", 18), ("特大", 22))
                        ]
                    ),
                )
            )
        if self._on_toggle_autostart:
            items.append(
                pystray.MenuItem(
                    "开机自启",
                    lambda: self._on_toggle_autostart(),
                    checked=lambda _item: bool(self._is_autostart and self._is_autostart()),
                )
            )
        items.append(pystray.Menu.SEPARATOR)
        if self._on_restart:
            items.append(pystray.MenuItem("重启程序", lambda: self._on_restart()))
        items.append(pystray.MenuItem("退出", lambda: self._on_quit()))
        return pystray.Menu(*items)

    def set_info(self, lines: list[str]) -> None:
        """更新菜单顶部的信息行（引擎 / 热键等）。"""
        self._info_lines = list(lines)
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:  # pragma: no cover
            pass

    def set_status(self, status: str, tooltip: str | None = None) -> None:
        try:
            self._icon.icon = _icon_image(_COLORS.get(status, _COLORS["idle"]))
            if tooltip:
                self._icon.title = tooltip
        except Exception:  # pragma: no cover - 托盘不可用时忽略
            pass

    def run(self) -> None:
        self._icon.run()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # pragma: no cover
            pass
