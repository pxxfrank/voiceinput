from __future__ import annotations

from types import SimpleNamespace

from voiceinput.compat import DEFAULT, TERMINAL, TERMINAL_LEGACY, TYPE_ONLY, resolve


def target(cls="Edit", exe="notepad.exe", title="无标题"):
    return SimpleNamespace(class_name=cls, exe=exe, title=title)


def test_default_target():
    assert resolve(target()).name == DEFAULT.name


def test_windows_terminal_class():
    assert resolve(target("CASCADIA_HOSTING_WINDOW_CLASS", "WindowsTerminal.exe")).name == TERMINAL.name


def test_classic_console_uses_shift_insert():
    assert resolve(target("ConsoleWindowClass", "conhost.exe")).name == TERMINAL_LEGACY.name


def test_terminal_exe_even_with_other_class():
    assert resolve(target("SomeWindow", "pwsh.exe")).name == TERMINAL_LEGACY.name


def test_configured_type_mode():
    assert resolve(target(), "type").name == TYPE_ONLY.name
    assert resolve(target("ConsoleWindowClass"), "type").prefer_unicode


def test_configured_paste_mode():
    assert resolve(target("ConsoleWindowClass"), "paste").name == DEFAULT.name
