"""No test may send real input to the machine running it.

This is not hypothetical. Several tests build a macro with a `click` action and stub
`background_input.post_click` — but a macro with no `background`/`target_hwnd` does
not take that path: `_click` falls through to pyautogui and clicks the developer's
actual screen, at whatever coordinate the fixture happened to use. They had been doing
that on every run, here and on CI.

So the real-input surface is replaced for the whole suite. A test that wants to assert
what would have been sent can read `sent_input`, or monkeypatch the same names itself —
monkeypatch restores after each test, so it composes with this.
"""

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """One Tk root for the whole run — never create a second, never destroy this one.

    Tk does not really support a root being torn down and another built in the same
    process: the second `tk.Tk()` raises TclError. A test file that made its own root
    and destroyed it at module teardown therefore *disabled every Tk test in every
    file that ran after it*, which looks like ten "no display" skips rather than a
    failure. Measured: adding one such file took `test_theme_scaling` from 10 passing
    to 10 skipped, on a machine with a display.
    """
    import tkinter as tk
    try:
        window = tk.Tk()
    except tk.TclError:                      # pragma: no cover - headless CI
        pytest.skip("no display")
    window.withdraw()
    yield window
    window.destroy()


class _Recorder:
    """Stands in for pyautogui, recording calls instead of performing them."""

    def __init__(self):
        self.calls = []

    def _record(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return call

    def __getattr__(self, name):
        # size() is read for clamping, so it has to answer with something usable.
        if name == "size":
            return lambda: (1920, 1080)
        if name in ("FAILSAFE", "PAUSE"):
            return False
        return self._record(name)


@pytest.fixture(autouse=True)
def no_real_input(monkeypatch):
    """Replace every path that could move the mouse or press a key."""
    import engine.action_runner as ar

    recorder = _Recorder()
    monkeypatch.setattr(ar, "pyautogui", recorder)

    for name in ("post_click", "post_double_click", "post_right_click", "post_move",
                 "post_drag", "post_scroll", "post_key", "post_type"):
        if hasattr(ar.bg, name):
            monkeypatch.setattr(ar.bg, name, lambda *a, **k: None)

    return recorder
