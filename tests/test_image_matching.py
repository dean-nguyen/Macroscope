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


def _ui_canvas(w=1280, h=800):
    """A haystack that behaves like a game UI rather than like noise.

    Scale matching is tested against band-limited content on purpose. Pure random
    noise is not merely the hardest case, it is an unrepresentative one: no
    resampling-based approach can recover it unless the trial scale happens to
    invert the original resample exactly, and real templates are plates, borders
    and text, not per-pixel noise.
    """
    import cv2

    rng = np.random.default_rng(7)
    bg = cv2.GaussianBlur(rng.integers(60, 190, (h, w, 3), dtype=np.uint8), (31, 31), 0)
    return bg


def _ui_button(label="Ready", w=260, h=120):
    """A plate with a border and text — the shape of a real template."""
    import cv2

    rng = np.random.default_rng(11)
    btn = np.full((h, w, 3), 58, np.uint8)
    btn += rng.normal(0, 6, btn.shape).astype(np.int16).clip(-40, 40).astype(np.uint8)
    cv2.rectangle(btn, (1, 1), (w - 2, h - 2), (225, 205, 140), 1)
    cv2.putText(btn, label, (24, int(h * 0.65)), cv2.FONT_HERSHEY_SIMPLEX,
                1.1, (250, 250, 250), 2)
    return btn


def _canvas_with(button, at=(301, 403)):
    """Paste *button* into a UI-like canvas at (y, x); returns (haystack, centre).

    The default position is deliberately NOT a multiple of 4. An earlier attempt at
    a downscaling pre-filter measured a score loss of 0.0000 and was shipped on that
    basis — but every measurement had pasted the element at (700, 1200), and both
    coordinates happen to be divisible by 4. Repeating it one pixel across showed
    losses up to 0.37, because the element's position decides whether the two
    images resample onto the same grid, and an app puts its buttons where it likes.
    Aligned coordinates in a fixture hide exactly that class of bug.
    """
    hay = _ui_canvas()
    y, x = at
    bh, bw = button.shape[:2]
    hay[y:y + bh, x:x + bw] = button
    return hay, (x + bw // 2, y + bh // 2)


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

@pytest.mark.parametrize("factor", [0.5, 0.8, 1.25, 1.5])
def test_matches_needle_captured_at_a_different_window_size(factor):
    """A template stored at one window size must be found at another."""
    import cv2

    im.clear_scale_cache()
    button = _ui_button()
    haystack, centre = _canvas_with(button)

    # The template as it would have been captured from a differently sized window.
    interp = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
    stored = cv2.resize(button, (int(button.shape[1] * factor),
                                 int(button.shape[0] * factor)), interpolation=interp)

    key = (f"scaled-{factor}", haystack.shape[1], haystack.shape[0])
    result = im._match_scaled(haystack, stored, 0.85, key)
    assert result is not None, f"not found at {factor}x"
    cx, cy, _ = result
    assert abs(cx - centre[0]) < 12 and abs(cy - centre[1]) < 12, \
        f"found at ({cx},{cy}), expected near {centre}"


@pytest.mark.parametrize("offset", [(300, 400), (301, 401), (302, 403), (303, 402)])
def test_scale_search_does_not_depend_on_pixel_alignment(offset):
    """Finding a rescaled template must not depend on where it happens to sit.

    This is the guard against re-introducing a downscaling shortcut. Any approach
    that shrinks both images before comparing only works when the element's
    position aligns with the sampling grid; measured, the same button lost 0.0000
    at a multiple-of-4 offset and 0.1181 one pixel over.
    """
    import cv2

    im.clear_scale_cache()
    button = _ui_button()
    haystack, centre = _canvas_with(button, at=offset)
    stored = cv2.resize(button, (int(button.shape[1] * 0.8), int(button.shape[0] * 0.8)),
                        interpolation=cv2.INTER_AREA)

    key = (f"offset-{offset}", haystack.shape[1], haystack.shape[0])
    result = im._match_scaled(haystack, stored, 0.85, key)
    assert result is not None, f"not found with the element at {offset}"
    cx, cy, _ = result
    assert abs(cx - centre[0]) < 12 and abs(cy - centre[1]) < 12


def test_discovery_costs_a_bounded_number_of_matches():
    """The search must not be a fine ladder walked one full match at a time.

    A single ladder fine enough for matching needs ~75 rungs at ~284 ms each on a
    real game window — a 19-second stall per template, which is what the two-stage
    search replaced.
    """
    calls = []
    real_score_at = im._score_at

    def counting(haystack, needle, scale):
        calls.append(scale)
        return real_score_at(haystack, needle, scale)

    im.clear_scale_cache()
    haystack = _canvas()
    needle = np.random.default_rng(4).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    im._score_at = counting
    try:
        im._discover_scale(haystack, needle)
    finally:
        im._score_at = real_score_at

    assert len(calls) <= 32, f"discovery used {len(calls)} full matches"
    assert len(im._SCALE_LADDER) <= 32, \
        f"coarse ladder has {len(im._SCALE_LADDER)} rungs"


def test_discovered_scale_is_cached_for_the_window_size():
    import cv2

    im.clear_scale_cache()
    button = _ui_button()
    haystack, _ = _canvas_with(button)
    stored = cv2.resize(button, (int(button.shape[1] * 0.8), int(button.shape[0] * 0.8)),
                        interpolation=cv2.INTER_AREA)

    key = ("cached-scale", haystack.shape[1], haystack.shape[0])
    assert im._match_scaled(haystack, stored, 0.85, key) is not None
    assert key in im._scale_cache
    # Recorded as a hint for other templates at this window size.
    assert key[1:] in im._window_scale


def test_ladder_sweeps_are_rationed():
    """A macro that legitimately matches nothing must not sweep every tick."""
    im.clear_scale_cache()
    haystack = _canvas()
    unrelated = np.random.default_rng(999).integers(
        0, 256, size=(40, 40, 3), dtype=np.uint8)
    key = ("no-such-element", haystack.shape[1], haystack.shape[0])

    assert im._match_scaled(haystack, unrelated, 0.98, key) is None
    assert im._may_sweep(key) is False, "second miss should not sweep again"


def test_discovery_is_never_switched_off_permanently():
    """Sweeps are rationed by time, never exhausted.

    A macro is normally started before the element it waits for is on screen, so
    an attempt-count budget gets spent while the element is legitimately absent —
    and the template can then never be found for the life of the process.
    """
    im.clear_scale_cache()
    haystack = _canvas()
    absent = np.random.default_rng(5).integers(0, 256, size=(40, 40, 3), dtype=np.uint8)
    key = ("late-arrival", haystack.shape[1], haystack.shape[0])

    for _ in range(10):                       # ten fruitless ticks
        im._match_scaled(haystack, absent, 0.98, key)
        # Pretend the interval elapsed. The ration is held per window size, not
        # per template, so that is the entry to clear.
        im._sweep_state[key[1:]] = 0.0

    assert im._may_sweep(key) is True, \
        "discovery must still be possible after many fruitless attempts"


def test_sweeps_are_rationed_per_window_size_not_per_template():
    """One search per interval, shared across the pack.

    A search costs ~6.9 s on a real game window, so nine templates each sweeping on
    their own schedule would spend more time searching than the interval itself. One
    is enough: whoever resolves the scale records it in _window_scale and the rest
    try that first for the price of a single match.
    """
    im.clear_scale_cache()
    haystack = _canvas()
    absent = np.random.default_rng(8).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    key_a = ("template-a", haystack.shape[1], haystack.shape[0])
    key_b = ("template-b", haystack.shape[1], haystack.shape[0])

    assert im._may_sweep(key_a) is True
    im._match_scaled(haystack, absent, 0.98, key_a)     # consumes the slot
    assert im._may_sweep(key_b) is False, \
        "a second template must not sweep in the same interval"


def test_one_template_scale_does_not_strand_the_others():
    """_window_scale is a hint, not a gate.

    Templates in a pack can come from different sessions at different window
    sizes; if the first one to resolve its scale blocked discovery for the rest,
    those would never match again.
    """
    im.clear_scale_cache()
    haystack = _canvas()
    key_a = ("template-a", haystack.shape[1], haystack.shape[0])
    key_b = ("template-b", haystack.shape[1], haystack.shape[0])

    im._record_scale(key_a, 1.5)              # A discovered a non-1.0 scale
    assert key_a[1:] in im._window_scale

    assert im._may_sweep(key_b) is True, \
        "another template must still be allowed to discover its own scale"


# ── frame scope ───────────────────────────────────────────────────────────────

def test_frame_scope_is_per_thread():
    """Each macro runs on its own thread and several can run at once.

    A shared depth counter never returns to zero while any macro is looping, so
    the frames stop being cleared and every macro keeps polling one frozen
    screenshot. A shared counter also drifts upward under contention, because
    += on a dict entry is not atomic, and never recovers.
    """
    import threading

    depths = {}
    barrier = threading.Barrier(2)

    def worker(name):
        im.begin_frame_scope()
        barrier.wait()                     # both threads inside a scope at once
        depths[name] = im._scope()["depth"]
        im.end_frame_scope()
        depths[f"{name}-after"] = im._scope()["depth"]

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert depths == {"a": 1, "b": 1, "a-after": 0, "b-after": 0}, depths


def test_frame_scope_depth_survives_contention():
    import threading

    def worker():
        for _ in range(2000):
            im.begin_frame_scope()
            im.end_frame_scope()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert im._scope()["depth"] == 0


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


def test_proportional_coords_refuse_without_a_window():
    """No resolved window means no client size to take a fraction of.

    Returning a placeholder here would click at (0, 0) in background mode, or
    wherever the cursor happens to sit in foreground mode — a wrong click with no
    warning. Failing the action is the honest outcome.
    """
    ctx = {"client_w": 0, "client_h": 0, "log": lambda _m: None}
    with pytest.raises(ar.ActionError):
        ar._coords({"xp": 0.5, "yp": 0.5}, ctx)


def test_pixels_short_circuit_before_the_window_is_consulted():
    """Both axes in pixels means xp/yp are never resolved, so a missing window
    cannot matter — the reason the "fall back to x/y" branch was dead code."""
    ctx = {"client_w": 0, "client_h": 0, "log": lambda _m: None}
    assert ar._coords({"x": 7, "y": 8, "xp": 0.5, "yp": 0.5}, ctx) == (7, 8)


@pytest.mark.parametrize("action_type", sorted(ar.ACTIONS_WITH_PROPORTIONS))
def test_proportional_coords_validate_where_supported(action_type):
    _validate({"name": "m", "actions": [{"type": action_type, "xp": 0.5, "yp": 0.5}]})


@pytest.mark.parametrize("action_type,extra", [
    ("drag", {"x2": 1, "y2": 1}),
    ("pixel_check", {"color": "#ffffff"}),
    ("pixel_wait", {"color": "#ffffff"}),
])
def test_proportional_coords_rejected_where_unsupported(action_type, extra):
    """These handlers never read xp/yp: drag and the pixel actions index a["x"]
    directly, so accepting them would validate and then raise KeyError mid-run."""
    action = {"type": action_type, "xp": 0.5, "yp": 0.5, **extra}
    with pytest.raises(ValueError, match="only supported on"):
        _validate({"name": "m", "actions": [action]})


def test_proportions_apply_per_axis():
    # y is given in pixels, x proportionally — each axis resolves on its own.
    ctx = {"client_w": 1000, "client_h": 500}
    assert ar._coords({"y": 42, "xp": 0.25}, ctx) == (250, 42)


def test_click_validates_with_only_proportional_coords():
    # move requires x/y; xp/yp must satisfy that requirement.
    _validate({"name": "m", "actions": [{"type": "move", "xp": 0.5, "yp": 0.5}]})
