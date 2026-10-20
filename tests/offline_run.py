"""断网运行验收：在进程内拒绝一切非回环网络连接，再跑完整语音管线。

这不是 Mock：ASR、复核、LLM 都是真实模型；只是把外部网络访问变成硬失败，
用来证明核心功能不依赖联网。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ALLOWED = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
_ATTEMPTS: list[str] = []


def _host_of(addr) -> str:
    if isinstance(addr, tuple) and addr:
        return str(addr[0])
    return str(addr)


def _hook(event: str, args) -> None:
    if event == "socket.connect":
        host = _host_of(args[1])
        if host not in _ALLOWED:
            _ATTEMPTS.append(f"connect:{host}")
            raise RuntimeError(f"离线验收：拒绝外部连接 {host}")
    elif event == "socket.getaddrinfo":
        host = str(args[0])
        if host not in _ALLOWED:
            _ATTEMPTS.append(f"resolve:{host}")
            raise RuntimeError(f"离线验收：拒绝外部域名解析 {host}")


def main() -> int:
    sys.addaudithook(_hook)
    from voiceinput.__main__ import main as app_main

    sys.argv = ["voiceinput", *sys.argv[1:]]
    try:
        code = app_main()
    finally:
        print("外部网络尝试：", _ATTEMPTS or "无")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
