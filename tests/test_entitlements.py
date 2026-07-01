"""Unit tests for the free/Pro feature-gating logic."""

import pytest

from engine.entitlements import (
    Tier,
    check_can_create,
    check_macro_runnable,
    check_parallel,
    for_tier,
    macro_required_features,
)

pytestmark = pytest.mark.unit


def _macro(**kw):
    base = {"name": "m", "actions": []}
    base.update(kw)
    return base


# ── free tier blocks paid features ────────────────────────────────────────────


def test_free_blocks_background():
    m = _macro(background=True, actions=[{"type": "click"}])
    assert check_macro_runnable(m, for_tier(Tier.FREE)) is not None


def test_free_blocks_detection_actions():
    m = _macro(actions=[{"type": "find_and_click", "template": "x.png"}])
    assert check_macro_runnable(m, for_tier(Tier.FREE)) is not None


def test_free_blocks_loop():
    m = _macro(loop=True, actions=[{"type": "click"}])
    assert check_macro_runnable(m, for_tier(Tier.FREE)) is not None


def test_free_allows_basic_actions():
    m = _macro(actions=[{"type": "click"}, {"type": "type", "text": "hi"}])
    assert check_macro_runnable(m, for_tier(Tier.FREE)) is None


def test_detection_nested_in_branch_is_caught():
    m = _macro(
        actions=[
            {
                "type": "pixel_check",
                "x": 1,
                "y": 1,
                "color": [0, 0, 0],
                "on_match": [{"type": "find_all_and_click", "template": "a"}],
            }
        ]
    )
    assert check_macro_runnable(m, for_tier(Tier.FREE)) is not None


# ── pro tier unlocks everything ───────────────────────────────────────────────


def test_pro_allows_all_features():
    m = _macro(
        background=True,
        loop=True,
        actions=[{"type": "image_wait", "template": "x.png"}],
    )
    assert check_macro_runnable(m, for_tier(Tier.PRO)) is None


# ── macro count limit ─────────────────────────────────────────────────────────


def test_free_macro_count_limit():
    free = for_tier(Tier.FREE)
    assert check_can_create(0, free) is None
    assert check_can_create(1, free) is None
    assert check_can_create(2, free) is not None  # at the cap


def test_pro_macro_count_unlimited():
    assert check_can_create(10_000, for_tier(Tier.PRO)) is None


# ── parallel folder runs ──────────────────────────────────────────────────────


def test_free_blocks_parallel():
    assert check_parallel(for_tier(Tier.FREE)) is not None


def test_pro_allows_parallel():
    assert check_parallel(for_tier(Tier.PRO)) is None


# ── feature inspection ────────────────────────────────────────────────────────


def test_macro_required_features():
    m = _macro(
        background=True,
        loop=True,
        actions=[{"type": "image_wait", "template": "x.png"}],
    )
    assert macro_required_features(m) == {
        "background": True,
        "detection": True,
        "loop": True,
    }


def test_basic_macro_requires_nothing():
    m = _macro(actions=[{"type": "click"}])
    assert macro_required_features(m) == {
        "background": False,
        "detection": False,
        "loop": False,
    }
