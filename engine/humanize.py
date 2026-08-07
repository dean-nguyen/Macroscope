"""Make automated input less mechanically identical.

Before this, every delay in a macro was a fixed constant and every click landed on
the exact centre of the matched template — so a running macro produced a perfect
metronome hitting the same pixel forever. That is a recognisable pattern, and the
README had to say so.

This does not make automation undetectable and nothing here should be described as
if it did. What it removes is the trivially obvious signature.

Two knobs, both per-macro:

    "humanize": false        turn all of it off for this macro
    "humanize": {"timing_pct": 0.15, "click_px": 3}

Timing is scattered by a *fraction* rather than a fixed number of milliseconds, so a
1200 ms settle and a 2500 ms poll both stay sensible at one setting. Click scatter is a
radius in pixels, and callers that know the size of what they are clicking pass their
own bound so the jitter cannot land outside the target.

Scope is deliberately narrow: only `wait.ms` and `loop_delay_ms` are scattered. A
`poll_ms`, a `timeout_ms` and a keystroke `interval` are used exactly as written,
because those are timeouts and rates the macro author chose for a reason, not pauses
meant to look human.
"""

from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

# Defaults chosen to be plainly visible in a log without changing behaviour:
# ±15% on a 2500 ms poll is ±375 ms, and 3 px on a button is nothing.
DEFAULT_TIMING_PCT = 0.15
DEFAULT_CLICK_PX = 3

# Its own generator, so seeding it in a test cannot be disturbed by anything else
# using the random module.
_rng = random.Random()


def seed(value: int) -> None:
    """Make jitter reproducible (tests only)."""
    _rng.seed(value)


class Humanize:
    """Resolved jitter settings for one macro run."""

    __slots__ = ("timing_pct", "click_px")

    def __init__(self, timing_pct: float = DEFAULT_TIMING_PCT,
                 click_px: int = DEFAULT_CLICK_PX):
        self.timing_pct = max(0.0, float(timing_pct))
        self.click_px = max(0, int(click_px))

    @property
    def enabled(self) -> bool:
        return self.timing_pct > 0 or self.click_px > 0

    def delay(self, ms: float) -> float:
        """Scatter a delay by ±timing_pct, never below zero."""
        if self.timing_pct <= 0 or ms <= 0:
            return ms
        return max(0.0, ms * (1.0 + _rng.uniform(-self.timing_pct, self.timing_pct)))

    def point(self, x: Optional[int], y: Optional[int],
              max_px: Optional[int] = None) -> Tuple[Optional[int], Optional[int]]:
        """Scatter a click point within a radius.

        *max_px* lets a caller that knows the size of the thing being clicked cap the
        scatter — find_and_click passes a quarter of the template's smaller side, so a
        jittered click stays well inside the element it matched.
        """
        radius = self.click_px if max_px is None else min(self.click_px, int(max_px))
        if radius <= 0 or x is None or y is None:
            return x, y
        return x + _rng.randint(-radius, radius), y + _rng.randint(-radius, radius)


DISABLED = Humanize(timing_pct=0.0, click_px=0)


def from_macro(macro: Dict) -> Humanize:
    """Read the ``humanize`` field of a macro.

    Absent means on with the defaults: this is a safety feature, so it should not
    need to be asked for. ``false`` turns it off — which a macro that must hit an
    exact pixel, or that is being compared against a recording, may legitimately want.
    """
    setting = macro.get("humanize", True)
    if isinstance(setting, dict):
        # None, not `or`: `click_px: 0` legitimately means "scatter timing but not
        # clicks", while an explicit null must not reach float() and kill the run.
        def given(field, default):
            value = setting.get(field)
            return default if value is None else value

        return Humanize(
            timing_pct=given("timing_pct", DEFAULT_TIMING_PCT),
            click_px=given("click_px", DEFAULT_CLICK_PX),
        )
    if setting is None or setting is True:
        return Humanize()
    if not setting:
        # false, 0, "" — anything a reader would write meaning "off". Only `false` is
        # documented, but reading `0` as "on" would be a trap.
        return DISABLED
    return Humanize()
