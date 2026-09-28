"""命令行入口：``python -m voiceinput``。"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from .app import VoiceInputApp
from .config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, load_config, save_default_config

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def _setup_logging(level: str, logfile: str | None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(_LOG_FORMAT, "%Y-%m-%d %H:%M:%S")

    # 后台运行时没有控制台，stderr 可能为 None
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    if logfile:
        path = Path(logfile)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _kernel32():
    import ctypes
    from ctypes import wintypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateMutexW.restype = wintypes.HANDLE
    lib.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    lib.CloseHandle.restype = wintypes.BOOL
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, lib


def _acquire_single_instance():
    """用命名互斥体保证同一会话只运行一个实例，返回句柄或 None。"""
    ctypes, kernel32 = _kernel32()
    ctypes.set_last_error(0)  # 清除残留，避免误判
    handle = kernel32.CreateMutexW(None, False, "Local\\voiceinput-singleton")
    if not handle or ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def _restart(mutex, config_path: str | None) -> None:
    """释放单实例锁后拉起一个新进程，然后本进程退出。"""
    import subprocess

    if mutex:
        _, kernel32 = _kernel32()
        kernel32.CloseHandle(mutex)  # 释放锁，允许新进程接管

    cmd = [sys.executable]
    if not getattr(sys, "frozen", False):
        cmd += ["-m", "voiceinput"]
    if config_path:
        cmd += ["-c", config_path]
    subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), close_fds=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="voiceinput", description="离线语音输入法")
    parser.add_argument("-c", "--config", default=None, help="配置文件路径")
    parser.add_argument("--no-tray", action="store_true", help="不显示系统托盘")
    parser.add_argument("--no-instance-lock", action="store_true", help="允许多开（调试用）")
    parser.add_argument("--settings", action="store_true", help="打开设置界面后退出")
    parser.add_argument("--hud", action="store_true", help="运行悬浮录音指示器（内部用）")
    args = parser.parse_args()

    if args.hud:
        from .hud import main as hud_main

        return hud_main()

    if args.settings:
        from .gui import main as gui_main

        return gui_main()

    if args.config is None and not DEFAULT_CONFIG_PATH.exists():
        save_default_config(DEFAULT_CONFIG_PATH)

    cfg = load_config(args.config)
    if args.no_tray:
        cfg.setdefault("feedback", {})["tray"] = False

    log_cfg = cfg.get("logging", {})
    _setup_logging(log_cfg.get("level", "INFO"), log_cfg.get("file"))

    mutex = None
    if not args.no_instance_lock:
        mutex = _acquire_single_instance()
        if mutex is None:
            logging.getLogger("voiceinput").warning("voiceinput 已在运行，本次启动退出。")
            return 0

    app = VoiceInputApp(cfg)
    app.start()
    try:
        app.run_tray()
    except KeyboardInterrupt:
        app.quit()

    if app.restart_requested:
        _restart(mutex, args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
