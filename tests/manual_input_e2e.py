"""手动 E2E：真实 Win32 文本窗口 + 真实剪贴板 + 全局按键。"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voiceinput import clipboard  # noqa: E402
from voiceinput.config import load_config  # noqa: E402
from voiceinput.inject import TextInsertionService  # noqa: E402
from voiceinput.target import capture_target, focus_target  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]


def find_main_window(pid: int) -> int:
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            if title.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def wait_state(path: Path, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("ready"):
                return data
        except Exception:
            pass
        time.sleep(0.05)
    raise TimeoutError(f"target app state not ready: {path}")


def run() -> int:
    out = Path(__file__).parent / "e2e_state.json"
    out.unlink(missing_ok=True)
    p = subprocess.Popen([sys.executable, str(Path(__file__).parent / "target_app.py"), str(out)])
    try:
        data = wait_state(out, 10.0)
        hwnd = find_main_window(p.pid)
        print("hwnd", hwnd, "tk-id", data.get("hwnd"))
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        target = capture_target()
        print("target:", target.describe() if target else None)

        clipboard.set_text("PROTECTED_CLIPBOARD_内容")
        before = clipboard.get_text()
        cfg = load_config()
        cfg["output"]["append_space"] = False
        cfg["output"]["append_newline"] = False
        svc = TextInsertionService(cfg)
        tx = svc.commit(svc.prepare("你好，Agent Memory 测试。", target=target))
        print("commit:", tx.status, tx.error, tx.method, tx.warning)
        time.sleep(0.6)
        state = json.loads(out.read_text(encoding="utf-8"))
        print("target text:", repr(state.get("text")))
        print("clipboard restored:", clipboard.get_text() == before, repr(clipboard.get_text()))
        assert tx.status == "committed", tx.error
        assert "Agent Memory" in state.get("text", ""), state.get("text")
        assert clipboard.get_text() == before, "clipboard not restored"

        # 目标变化：准备后把焦点切到第二个窗口
        out2 = Path(__file__).parent / "e2e_state2.json"
        out2.unlink(missing_ok=True)
        p2 = subprocess.Popen([sys.executable, str(Path(__file__).parent / "target_app.py"), str(out2), "Second"])
        try:
            wait_state(out2, 10.0)
            hwnd2 = find_main_window(p2.pid)
            tx2 = svc.prepare("不应插入到新窗口", target=target)
            user32.ShowWindow(hwnd2, 9)
            user32.SetForegroundWindow(hwnd2)
            time.sleep(0.4)
            tx2 = svc.commit(tx2)
            time.sleep(0.3)
            state2 = json.loads(out2.read_text(encoding="utf-8"))
            print("target-change commit:", tx2.status, tx2.error)
            print("second text:", repr(state2.get("text")))
            assert tx2.status in ("target_changed", "failed"), tx2.status
            assert "不应插入" not in state2.get("text", "")

            # 用户显式确认“插入到原窗口”时才允许恢复焦点
            tx2 = svc.commit(tx2, allow_focus_restore=True)
            time.sleep(0.4)
            state1 = json.loads(out.read_text(encoding="utf-8"))
            print("explicit restore commit:", tx2.status, repr(state1.get("text")))
            assert tx2.status == "committed"
            assert "不应插入" in state1.get("text", "")
        finally:
            p2.kill()

        # Unicode 直输回退
        focus_target(target)
        time.sleep(0.2)
        tx3 = svc.prepare("直输 Unicode 测试：你好世界 123", target=target)
        from voiceinput.inject import type_unicode

        ok = type_unicode(tx3.text)
        print("type_unicode:", ok)
        time.sleep(0.4)
        state = json.loads(out.read_text(encoding="utf-8"))
        print("after type:", repr(state.get("text")))
        assert "直输 Unicode" in state.get("text", "")
        print("E2E OK")
        return 0
    finally:
        p.kill()


if __name__ == "__main__":
    raise SystemExit(run())
