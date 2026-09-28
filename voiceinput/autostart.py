"""开机自启：在「启动」文件夹写入一个静默启动脚本。

实现方式不依赖任何第三方库：向
``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup``
写入一个（UTF-16 编码的）.vbs，登录时由 wscript 静默拉起程序；删除该文件即关闭自启。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import PROJECT_ROOT

STARTUP_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)
SCRIPT_NAME = "voiceinput.vbs"


def _launch_target() -> tuple[str, str]:
    """返回 (可执行文件, 附加参数)。"""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    exe = Path(sys.executable).resolve()
    pyw = exe.with_name("pythonw.exe")  # 用 pythonw 静默启动，避免弹控制台
    if pyw.exists():
        exe = pyw
    return str(exe), "-m voiceinput"


def _vbs(exe: str, args: str) -> str:
    cmd = f'"{exe}"' + (f" {args}" if args else "")
    cmd_vbs = cmd.replace('"', '""')  # VBS 字符串内转义双引号
    wd_vbs = str(PROJECT_ROOT).replace('"', '""')
    return (
        "' voiceinput 开机自启脚本（由程序自动生成，删除本文件即可关闭自启）\n"
        'Set sh = CreateObject("WScript.Shell")\n'
        f'sh.CurrentDirectory = "{wd_vbs}"\n'
        f'sh.Run "{cmd_vbs}", 0, False\n'
    )


def _script_path() -> Path:
    return STARTUP_DIR / SCRIPT_NAME


def is_enabled() -> bool:
    return _script_path().exists()


def enable() -> Path:
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    exe, args = _launch_target()
    path = _script_path()
    # 用 UTF-16(带 BOM) 写入，兼容路径中的非 ASCII 字符
    path.write_text(_vbs(exe, args), encoding="utf-16")
    return path


def disable() -> None:
    path = _script_path()
    if path.exists():
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="voiceinput 开机自启管理")
    parser.add_argument("action", choices=["enable", "disable", "status"])
    args = parser.parse_args()
    if args.action == "enable":
        print(f"已开启开机自启：{enable()}")
    elif args.action == "disable":
        disable()
        print("已关闭开机自启")
    else:
        print("开机自启：", "已开启" if is_enabled() else "已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
