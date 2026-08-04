"""Tests for matcher robustness: uncaptured templates, window resizing, and
proportional coordinates.

Each of these covers a failure that made a freshly installed pack unusable:
a missing screenshot aborted the whole macro, a resized game window matched
nothing, and pixel coordinates were tied to one window size.
"""

import numpy as np
import pytest

import engine.action_runner as ar
import engine.image_matcher as im
from engine.macro_engine import _validate

pytestmark = pytest.mark.unit


def _canvas(w=600, h=400):
    """A haystack with enough structure for correlation to be meaningful."""
    rng = np.random.default_rng(1234)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


# ── uncaptured templates ──────────────────────────────────────────────────────

def test_missing_template_raises_template_missing(tmp_path):
    with pytest.raises(im.TemplateMissing):
        im.find_template(str(tmp_path / "nope.png"))


def test_template_missing_is_a_file_not_found_error():
    # Callers that already catch FileNotFoundError must keep working.
    assert issubclass(im.TemplateMissing, FileNotFoundError)


def test_safe_find_treats_missing_template_as_not_found(tmp_path):
    logged = []
    action = {"template": str(tmp_path / "never-captured.png")}
    ar._warned_missing.clear()

    result = ar._safe_find(action, None, 0.9, {"log": logged.append})

    assert result is None, "a missing template must not raise past the action"
    assert any("missing template" in m for m in logged)


def test_missing_template_logged_once_per_template(tmp_path):
    logged = []
    action = {"template": str(tmp_path / "never-captured.png")}
    ar._warned_missing.clear()

    for _ in range(3):
        ar._safe_find(action, None, 0.9, {"log": logged.append})

    assert sum("missing template" in m for m in logged) == 1


def test_find_and_click_takes_not_found_branch_when_uncaptured(tmp_path):
    """The whole point: one uncaptured template must not kill the macro."""
    ar._warned_missing.clear()
    branch_ran = []
    action = {
        "type": "find_and_click",
        "template": str(tmp_path / "never-captured.png"),
        "on_not_found": [{"type": "wait", "ms": 0}],
    }

    ar._find_and_click(action, lambda actions: branch_ran.extend(actions),
                       {"log": lambda _m: None})

    assert branch_ran == [{"type": "wait", "ms": 0}]


# ── scale-aware matching ──────────────────────────────────────────────────────

def test_matches_needle_captured_at_a_different_window_size():
    import cv2

    im.clear_scale_cache()
    haystack = _canvas()
    patch = haystack[120:200, 180:300].copy()

    # Same element as it would look captured from a window 25% larger.
    bigger = cv2.resize(patch, (int(patch.shape[1] * 1.25), int(patch.shape[0] * 1.25)),
                        interpolation=cv2.INTER_CUBIC)

    key = ("scaled-needle", haystack.shape[1], haystack.shape[0])
    assert im._match_scaled(haystack, bigger, 0.85, key) is not None


def test_discovered_scale_is_cached_for_the_window_size():
    import cv2

    im.clear_scale_cache()
    haystack = _canvas()
    patch = haystack[50:130, 60:190].copy()
    smaller = cv2.resize(patch, (int(patch.shape[1] * 0.8), int(patch.shape[0] * 0.8)),
                         interpolation=cv2.INTER_AREA)

    key = ("cached-scale", haystack.shape[1], haystack.shape[0])
    assert im._match_scaled(haystack, smaller, 0.85, key) is not None
    assert key in im._scale_cache
    # Generalises to other templates at this window size, so each one does not
    # have to pay for its own ladder sweep.
    assert key[1:] in im._window_scale


def test_ladder_sweeps_are_rationed():
    """A macro that legitimately matches nothing must not sweep every tick."""
    im.clear_scale_cache()
    haystack = _canvas()
    # Structured, but absent from the haystack — a different random image.
    unrelated = np.random.default_rng(999).integers(
        0, 256, size=(40, 40, 3), dtype=np.uint8)
    key = ("no-such-element", haystack.shape[1], haystack.shape[0])

    assert im._match_scaled(haystack, unrelated, 0.98, key) is None
    assert im._may_sweep(key) is False, "second miss should not sweep again"


# ── flat templates ────────────────────────────────────────────────────────────

def test_flat_template_is_refused(tmp_path):
    """A featureless capture correlates perfectly with everything.

    TM_CCOEFF_NORMED divides by the template's standard deviation, so a solid
    patch scores 1.0 against any haystack — matching it would click a random
    spot rather than find a button.
    """
    import cv2

    flat = tmp_path / "flat.png"
    cv2.imwrite(str(flat), np.full((40, 40, 3), 200, dtype=np.uint8))

    with pytest.raises(im.TemplateUnusable):
        im._load_needle(str(flat))


def test_flat_needle_never_reports_a_match():
    haystack = _canvas()
    flat = np.full((40, 40, 3), 7, dtype=np.uint8)
    assert im._cv_match(haystack, flat, 0.95) is None


def test_unusable_template_degrades_like_a_missing_one(tmp_path):
    """It must not abort the macro either — same graceful path."""
    import cv2

    flat = tmp_path / "flat.png"
    cv2.imwrite(str(flat), np.full((40, 40, 3), 200, dtype=np.uint8))
    assert issubclass(im.TemplateUnusable, im.TemplateMissing)

    ar._warned_missing.clear()
    logged = []
    result = ar._safe_find({"template": str(flat)}, None, 0.9, {"log": logged.append})

    assert result is None
    assert any("flat/featureless" in m for m in logged)


# ── proportional coordinates ──────────────────────────────────────────────────

def test_proportional_coords_resolve_against_client_size():
    ctx = {"client_w": 2840, "client_h": 1600}
    assert ar._coords({"xp": 0.5, "yp": 0.25}, ctx) == (1420, 400)


def test_pixels_win_over_proportions():
    ctx = {"client_w": 2840, "client_h": 1600}
    assert ar._coords({"x": 10, "y": 20, "xp": 0.5, "yp": 0.5}, ctx) == (10, 20)


def test_proportional_coords_fall_back_without_a_window():
    """No resolved window means no client size to scale against — say so."""
    logged = []
    ctx = {"client_w": 0, "client_h": 0, "log": logged.append}
    assert ar._coords({"xp": 0.5, "yp": 0.5}, ctx) == (None, None)
    assert any("xp/yp" in m for m in logged)


def test_proportions_apply_per_axis():
    # y is given in pixels, x proportionally — each axis resolves on its own.
    ctx = {"client_w": 1000, "client_h": 500}
    assert ar._coords({"y": 42, "xp": 0.25}, ctx) == (250, 42)


def test_click_validates_with_only_proportional_coords():
    # move requires x/y; xp/yp must satisfy that requirement.
    _validate({"name": "m", "actions": [{"type": "move", "xp": 0.5, "yp": 0.5}]})
