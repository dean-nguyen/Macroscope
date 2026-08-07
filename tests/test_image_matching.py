"""Tests for matcher robustness: uncaptured templates, window resizing, and
proportional coordinates.

Each of these covers a failure that made a freshly installed pack unusable:
a missing screenshot aborted the whole macro, a resized game window matched
nothing, and pixel coordinates were tied to one window size.
"""

import sys
import time

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
        # Pretend both floors elapsed: one clock per window size (so no tick spends
        # two searches) and one per template (so the retry slot cannot be
        # monopolised). Neither may ever become permanent.
        im._sweep_state[key[1:]] = 0.0
        im._swept[key] = 0.0

    assert im._may_sweep(key) is True, \
        "discovery must still be possible after many fruitless attempts"


def test_only_one_template_sweeps_at_a_time():
    """A search costs ~6.9 s on a real game window, so several templates sweeping
    back to back would stall one tick for a minute. One at a time, always."""
    im.clear_scale_cache()
    haystack = _canvas()
    absent = np.random.default_rng(8).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    key_a = ("template-a", haystack.shape[1], haystack.shape[0])
    key_b = ("template-b", haystack.shape[1], haystack.shape[0])

    assert im._may_sweep(key_a) is True
    im._match_scaled(haystack, absent, 0.98, key_a)     # takes the slot
    assert im._may_sweep(key_b) is False, \
        "two templates must not sweep back to back"


def test_a_template_that_has_never_searched_gets_its_own_turn():
    """The bug this replaced: rationing by window size alone starved the only
    template that could answer.

    Measured against a live game window at 0.44x — five templates scored in a row all
    reported "no match", because the first (absent) one spent the interval and the
    next four were refused discovery in 0.05 s each. The one whose button was plainly
    on screen scored 0.94 when given a search of its own. Every pack macro checks
    absent guard templates first, so in a 2.5 s poll loop the scale was never
    discovered at all, and the pack only ever worked at exactly the capture size.
    """
    im.clear_scale_cache()
    haystack = _canvas()
    absent = np.random.default_rng(11).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    guard = ("absent-guard", haystack.shape[1], haystack.shape[0])
    wanted = ("the-one-on-screen", haystack.shape[1], haystack.shape[0])

    im._match_scaled(haystack, absent, 0.98, guard)     # takes the slot, learns nothing
    assert im._may_sweep(wanted) is False               # not in the same breath...

    # ...but once the floor has passed it is this template's turn, not another
    # 20-second wait. The floor is the cost of the last search, so pretend it elapsed.
    im._sweep_state[wanted[1:]] = time.monotonic() - (im._SWEEP_FLOOR + 1.0)
    assert im._may_sweep(wanted) is True, \
        "a template that has never searched must not wait out the long interval"

    # A template that already had its turn does wait the long interval.
    im._match_scaled(haystack, absent, 0.98, guard)
    im._sweep_state[guard[1:]] = time.monotonic() - (im._SWEEP_FLOOR + 1.0)
    assert im._may_sweep(guard) is False


def test_note_sweep_is_only_for_tests_now():
    """_claim_sweep records the slot itself; _note_sweep stays as a way for a test to
    stamp one without going through the decision."""
    im.clear_scale_cache()
    key = ("t", 400, 300)
    im._note_sweep(key)
    assert key in im._swept


def test_the_retry_slot_is_not_monopolised_by_the_first_template():
    """The bug the first version of this fix still had, proven by simulation over 200
    ticks: with a retry clock held per window size, the first guard template swept 24
    times and the on-screen template never retried after its single first turn, so an
    element that appeared later was never found at all.

    Every pack macro checks absent guard templates first, so this is the ordinary case,
    not a corner.
    """
    im.clear_scale_cache()
    size = (1236, 696)
    guard = ("guard", *size)
    wanted = ("on-screen", *size)

    # Both have had their one first-time pass, long ago.
    past = time.monotonic() - (im._DISCOVERY_INTERVAL + 5)
    im._swept[guard] = past
    im._swept[wanted] = past
    im._sweep_state[size] = past
    im._sweep_cost[size] = 0.2

    assert im._may_sweep(guard) is True
    im._note_sweep(guard)
    im._note_sweep_cost(guard, 0.2)

    # The guard just retried, so it must now wait out the long interval...
    assert im._may_sweep(guard) is False
    # ...and the slot must be available to the other template once the per-size floor
    # passes, rather than going back to the guard.
    im._sweep_state[size] = time.monotonic() - (im._SWEEP_FLOOR + 0.5)
    assert im._may_sweep(wanted) is True, \
        "the retry slot must not be monopolised by whichever template is scored first"
    assert im._may_sweep(guard) is False


def test_every_template_in_a_realistic_pack_gets_served():
    """Two templates is inside the rotation, so a two-template test cannot see the
    starvation this rule exists to stop.

    Measured with only the per-template clock and no "who waited longest" rule, using
    this pack's own scoring order — 8 templates, the one on screen scored last behind
    seven absent guards, 1.1 s searches, 2.5 s poll: after 400 ticks the first six
    guards had swept 66-67 times each and the visible template zero. Anything past
    roughly _DISCOVERY_INTERVAL / tick positions in scoring order starved permanently.
    """
    im.clear_scale_cache()
    size = (1236, 696)
    names = [f"template-{i}" for i in range(12)]
    poll, search = 2.5, 1.1        # the pack's loop delay, and a measured search

    # Time has to actually advance, and this is the crux: with a 20 s interval and
    # ~3.6 s per served tick, the front of the list comes due again after ~6 slots.
    # Anything past that position is what starved, so a test with a frozen clock — or
    # with fewer templates than fit in one interval — cannot see this at all.
    clock = [1000.0]
    real = time.monotonic
    im.time.monotonic = lambda: clock[0]
    served = {name: 0 for name in names}
    try:
        for _tick in range(120):
            clock[0] += poll
            for name in names:
                if im._claim_sweep((name, *size)):
                    served[name] += 1
                    clock[0] += search
                    im._note_sweep_cost((name, *size), search)
    finally:
        im.time.monotonic = real

    starved = [n for n, c in served.items() if not c]
    assert not starved, f"never searched: {starved}"
    assert max(served.values()) - min(served.values()) <= 1, \
        f"unevenly served: {served}"


def test_a_search_that_raises_still_costs_its_ration():
    """_note_sweep_cost is in a finally for a reason: a template whose search blows up
    must not get a free retry on every tick."""
    im.clear_scale_cache()
    haystack = _canvas()
    needle = np.random.default_rng(21).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    key = ("explodes", haystack.shape[1], haystack.shape[0])

    def boom(*_a, **_k):
        raise RuntimeError("discovery blew up")

    real = im._discover_scale
    im._discover_scale = boom
    try:
        with pytest.raises(RuntimeError):
            im._match_scaled(haystack, needle, 0.98, key)
    finally:
        im._discover_scale = real

    assert key in im._swept, "the slot must be spent even when the search raises"
    assert im._may_sweep(key) is False
    # What the finally actually protects: the adaptive floor. _note_sweep already
    # recorded _swept before the search, so asserting only that cannot tell the
    # finally from its absence.
    assert key[1:] in im._sweep_cost, \
        "the search's cost must be recorded even when it raises"


def test_the_floor_between_searches_is_what_the_last_one_cost():
    """A fixed floor cannot serve a 1.1 s sweep and a 6.9 s one. Waiting out the last
    search's own cost keeps discovery near half the wall clock at any window size."""
    im.clear_scale_cache()
    size = (1236, 696)
    fresh = ("never-searched", *size)

    im._note_sweep_cost(("someone-else", *size), 6.9)   # a slow window

    im._sweep_state[size] = time.monotonic() - 3.0
    assert im._may_sweep(fresh) is False, "3 s is not enough after a 6.9 s search"
    im._sweep_state[size] = time.monotonic() - 7.5
    assert im._may_sweep(fresh) is True

    # And on a fast window the floor collapses to the minimum, so discovery is not
    # needlessly slow there.
    im.clear_scale_cache()
    im._note_sweep_cost(("someone-else", *size), 0.05)
    im._sweep_state[size] = time.monotonic() - (im._SWEEP_FLOOR + 0.1)
    assert im._may_sweep(fresh) is True


def test_one_lock_holds_the_whole_decision():
    """"Claim the slot" has to mean it. Checking and recording in two lock
    acquisitions let 8 threads start 4 concurrent searches where the floor allows 1,
    measured with a 1 microsecond switch interval — and run_folder runs macros in
    parallel by default."""
    import threading

    im.clear_scale_cache()
    size = (800, 600)
    im._sweep_cost[size] = 5.0            # a slow window: the floor is wide
    starts = []
    barrier = threading.Barrier(8)

    def go(i):
        barrier.wait()
        if im._claim_sweep((f"t{i}", *size)):
            starts.append(i)

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    assert len(starts) == 1, f"{len(starts)} threads claimed the same slot"


def test_the_diagnostics_override_does_not_outlive_a_cache_reset():
    im.clear_scale_cache()
    key = ("t", 800, 600)
    im.set_unrationed_discovery(True)
    assert im._may_sweep(key) is True
    im.clear_scale_cache()
    im._note_sweep(key)
    assert im._may_sweep(key) is False, \
        "a diagnostics override must not survive into a macro run"


def test_diagnostics_can_pay_any_price():
    """tools/match_report.py scores a whole directory in one pass — exactly the batch
    the floor slows down. A report that says "no match" because of rationing is worse
    than a slow report."""
    im.clear_scale_cache()
    key = ("t", 800, 600)
    im._note_sweep(key)                      # slot just taken
    assert im._may_sweep(key) is False
    try:
        im.set_unrationed_discovery(True)
        assert im._may_sweep(key) is True
    finally:
        im.set_unrationed_discovery(False)
    assert im._may_sweep(key) is False


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
