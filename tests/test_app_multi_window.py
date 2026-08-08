"""The app's play/stop button when one macro runs on several windows.

`on_done` fires once per window. Flipping the button on the first of them showed a
stopped macro that was still running — and pressing it then *stopped* the rest,
because the button and the engine disagreed about what pressing it meant. That is
exactly what makes someone conclude a macro can only ever run on one window.

Driven through the real method with a stub, so no Tk window is needed.
"""

from types import SimpleNamespace

import pytest

from gui.app import App

pytestmark = pytest.mark.unit


class _Engine:
    def __init__(self, running):
        self._running = list(running)

    def running_windows(self, _name):
        return list(self._running)

    def stopped_reason(self, _name):
        return None


def _app(running):
    flips, statuses = [], []
    return SimpleNamespace(
        _engine=_Engine(running),
        _update_toggle_btn=lambda name, running: flips.append(running),
        _status=statuses.append,
        _log=lambda msg, tag="info": None,
        flips=flips,
        statuses=statuses,
    )


def test_the_button_stays_stopped_while_another_window_runs():
    app = _app(running=[222])
    App._on_macro_done(app, "demo")
    assert app.flips == [], "the button must not say stopped while a run is alive"
    assert "still running" in app.statuses[-1]


def test_the_button_flips_once_the_last_window_finishes():
    app = _app(running=[])
    App._on_macro_done(app, "demo")
    assert app.flips == [False]
    assert "finished" in app.statuses[-1]


def test_a_guard_reason_is_only_announced_when_everything_has_stopped():
    """Otherwise one window stalling would report the whole macro as stopped while
    the other is still working."""
    app = _app(running=[222])
    app._engine.stopped_reason = lambda _name: "lost its screen"
    App._on_macro_done(app, "demo")
    assert "lost its screen" not in " ".join(app.statuses)

    app = _app(running=[])
    app._engine.stopped_reason = lambda _name: "lost its screen"
    App._on_macro_done(app, "demo")
    assert "lost its screen" in " ".join(app.statuses)
