"""llama-server 看门狗：主程序异常退出时终止子进程，避免遗留后台服务。"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

SYNCHRONIZE = 0x00100000
PROCESS_TERMINATE = 0x0001


def run(parent_pid: int, child_pid: int) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    parent = kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))
    child = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, int(child_pid))
    if not parent or not child:
        return 0
    try:
        while True:
            if kernel32.WaitForSingleObject(parent, 500) == 0:  # parent exited
                kernel32.TerminateProcess(child, 0)
                return 0
            if kernel32.WaitForSingleObject(child, 0) == 0:  # child exited
                return 0
            time.sleep(0.2)
    finally:
        kernel32.CloseHandle(parent)
        kernel32.CloseHandle(child)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        return 2
    return run(int(argv[0]), int(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
