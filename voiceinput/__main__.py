"""命令行入口：``python -m voiceinput``。"""

from __future__ import annotations

import argparse
import ctypes
import logging
import subprocess
import sys

from . import logging_setup, paths
from .config import ensure_config, load_config

log = logging.getLogger("voiceinput")


def _set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _kernel32():
    from ctypes import wintypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateMutexW.restype = wintypes.HANDLE
    lib.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    lib.CloseHandle.restype = wintypes.BOOL
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, lib


def _acquire_single_instance():
    ctypes, kernel32 = _kernel32()
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, paths.MUTEX_NAME)
    if not handle or ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def _release(handle) -> None:
    if not handle:
        return
    try:
        _, kernel32 = _kernel32()
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def _restart(handle, config_path: str | None) -> None:
    _release(handle)
    cmd = [sys.executable]
    if not getattr(sys, "frozen", False):
        cmd += ["-m", "voiceinput"]
    if config_path:
        cmd += ["-c", config_path]
    subprocess.Popen(cmd, cwd=str(paths.app_root()), close_fds=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="LocalVoiceInput", description="本地离线语音输入")
    parser.add_argument("-c", "--config", default=None, help="配置文件路径")
    parser.add_argument("--settings", action="store_true", help="打开设置窗口")
    parser.add_argument("--onboarding", action="store_true", help="打开首次引导")
    parser.add_argument("--diagnose", action="store_true", help="打印诊断信息")
    parser.add_argument("--load-test", action="store_true", help="诊断时加载全部模型")
    parser.add_argument("--selftest", action="store_true", help="用真实音频自检")
    parser.add_argument("--wav", default=None, help="自检用的 WAV 文件")
    parser.add_argument("--llm-test", action="store_true", help="自检时运行 LLM")
    parser.add_argument("--verify-models", action="store_true", help="按清单校验模型 SHA-256")
    parser.add_argument("--feed-wav", default=None, help="验收模式：用真实 WAV 驱动完整管线")
    parser.add_argument("--feed-speed", type=float, default=1.0, help="WAV 喂入倍速，0=全速")
    parser.add_argument("--exit-after-session", action="store_true", help="会话结束后自动退出（验收）")
    parser.add_argument("--auto-commit", action="store_true", help="精修模式自动确认插入（验收）")
    parser.add_argument("--mode", choices=["fast", "smart", "auto"], default=None, help="覆盖本次运行模式")
    parser.add_argument("--no-onboarding", action="store_true", help="不显示首次引导（验收/自动化）")
    parser.add_argument("--session-delay", type=float, default=0.0, help="验收模式下会话启动延迟秒数")
    parser.add_argument("--no-tray", action="store_true", help="不显示系统托盘")
    parser.add_argument("--no-instance-lock", action="store_true", help="允许多开（调试）")
    parser.add_argument("--portable", action="store_true", help="便携模式（数据存程序目录）")
    parser.add_argument("--watchdog", nargs=2, metavar=("PARENT_PID", "CHILD_PID"), help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    if args.watchdog:
        from .llm_watchdog import run as watchdog_run

        return watchdog_run(int(args.watchdog[0]), int(args.watchdog[1]))

    if args.portable:
        import os

        os.environ["VOICEINPUT_PORTABLE"] = "1"
    if args.config:
        import os

        os.environ["VOICEINPUT_CONFIG"] = args.config
        paths.settings_path  # noqa: B018
    paths.ensure_user_dirs()
    ensure_config()

    cfg = load_config(args.config)
    if args.mode:
        cfg["mode"] = args.mode
    logging_setup.setup(
        cfg.get("logging", {}).get("level", "INFO"),
        int(cfg.get("logging", {}).get("max_mb", 2)),
        int(cfg.get("logging", {}).get("backups", 3)),
    )

    if args.version:
        print(f"LocalVoiceInput {paths.VERSION}")
        return 0

    if args.diagnose:
        _set_dpi_awareness()
        from .diagnostics import main as diag_main

        return diag_main(load_test=args.load_test)

    if args.verify_models:
        from .modelstore import verify_manifest

        results = verify_manifest(progress=lambda r: print(f"{'OK ' if r['ok'] else 'BAD'} {r['name']}"))
        return 0 if all(r["ok"] for r in results) else 2

    if args.selftest:
        from .selftest import run as selftest_run

        return selftest_run(args.wav, llm=args.llm_test)

    if args.settings:
        _set_dpi_awareness()
        from .gui import main as gui_main

        return gui_main(args.config)

    if args.onboarding:
        _set_dpi_awareness()
        from .onboarding import main as onboarding_main

        return onboarding_main(args.config)

    if args.no_tray:
        cfg.setdefault("feedback", {})["tray"] = False

    mutex = None
    if not args.no_instance_lock:
        mutex = _acquire_single_instance()
        if mutex is None:
            logging.getLogger("voiceinput").warning("程序已在运行，本次启动退出。")
            return 0

    _set_dpi_awareness()
    from .app import VoiceInputApp

    app = VoiceInputApp(
        cfg,
        config_path=args.config,
        feed_wav=args.feed_wav,
        feed_speed=args.feed_speed,
        exit_after_session=args.exit_after_session,
        auto_commit=args.auto_commit,
        skip_onboarding=args.no_onboarding,
        session_delay=args.session_delay,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        app.quit()

    if app.restart_requested:
        _restart(mutex, args.config)
        return 0
    _release(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
