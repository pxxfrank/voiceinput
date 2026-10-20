from __future__ import annotations

from voiceinput.inject import TextInsertionService


class FakeTarget:
    def __init__(self, alive=True, current=True):
        self.alive = alive
        self.current = current
        self.hwnd = 1
        self.pid = 2
        self.exe = "test.exe"
        self.title = "Test"
        self.class_name = "Edit"
        self.focus_hwnd = 0
        self.focus_class = ""

    def is_alive(self):
        return self.alive

    def is_current(self):
        return self.current

    def describe(self):
        return "test"

    def to_dict(self):
        return {}


def _service(method="type"):
    return TextInsertionService({"output": {"method": method, "restore_clipboard": False}})


def test_payload_space_and_newline():
    svc = TextInsertionService({"output": {"append_space": True, "append_newline": True}})
    assert svc.prepare("abc").text == "abc \n"


def test_no_target_rejected():
    svc = _service()
    tx = svc.prepare("hello", target=None)
    tx = svc.commit(tx)
    assert tx.status == "failed"
    assert "目标" in tx.error


def test_dead_target_rejected():
    svc = _service()
    tx = svc.prepare("hello", target=FakeTarget(alive=False))
    tx = svc.commit(tx)
    assert tx.status == "failed"


def test_changed_target_not_written():
    svc = _service()
    tx = svc.prepare("hello", target=FakeTarget(current=False))
    tx = svc.commit(tx)
    assert tx.status == "target_changed"
    assert tx.text == "hello"


def test_commit_twice_is_idempotent():
    svc = _service()
    tx = svc.prepare("hello", target=FakeTarget())
    tx.status = "committed"
    before = tx.committed_at
    tx = svc.commit(tx)
    assert tx.committed_at == before


def test_undo_without_transaction():
    svc = _service()
    ok, message = svc.undo_last()
    assert not ok
    assert "没有" in message
