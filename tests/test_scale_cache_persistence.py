"""Tests for the scale cache outliving the process.

Discovering a template's scale is the most expensive thing the matcher does — measured
2797 ms per template on a 1810x1020 window, and a pack reads 11 of them. Held in memory
only, every launch paid it again.

And the rationing that stops one search starving the others turns that cost into a
*delay*. Measured on a live client: while a battle is on screen the "Tap to continue"
template is asked for, is genuinely absent, and a failed search caches nothing — so it is
locked out for `_DISCOVERY_INTERVAL`. When the result screen appears it is still inside
that lockout, reads as absent, and the macro waits. Worst case about 23 s after the screen
was drawn, on a template that scored 0.948 against that very frame once discovery was
allowed to run.

The fix is not a shorter interval, which exists for a measured reason. It is to stop
rediscovering what was already known.
"""

import json

import numpy as np
import pytest

from engine import image_matcher as im

pytestmark = pytest.mark.unit


@pytest.fixture
def persisted(tmp_path, monkeypatch):
    """Persistence on, pointed at a temp directory rather than the user's."""
    monkeypatch.setattr(im, "_persist_path", lambda: tmp_path / ".scale_cache.json")
    im.set_persistence(True)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)
    yield tmp_path / ".scale_cache.json"
    im.set_persistence(False)


KEY = ("templates/a.png", 1810, 1020)


def test_a_discovered_scale_survives_the_process(persisted, monkeypatch):
    im._record_scale(KEY, 1.4644)
    assert persisted.exists(), "nothing was written"

    # A fresh process: memory empty, file intact.
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)
    assert im._scale_cache == {}

    assert im._scale_order(KEY)[0] == pytest.approx(1.4644)


def test_the_cheap_path_tries_the_remembered_scale_first(persisted, monkeypatch):
    """Which is the whole point: first guess right means no search is attempted."""
    im._record_scale(KEY, 1.4644)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)

    order = im._scale_order(KEY)
    assert order[0] == pytest.approx(1.4644)
    assert 1.0 in order, "1.0 must remain as a fallback"


def test_one_template_teaches_the_window_scale_to_the_others(persisted, monkeypatch):
    """A pack is captured at one resolution, so a sibling's answer is a good second
    guess — and it is the only thing that helps a template which is never on screen at
    the moment it is asked for."""
    im._record_scale(KEY, 1.4644)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)

    sibling = ("templates/b.png", 1810, 1020)
    assert im._scale_order(sibling)[0] == pytest.approx(1.4644)


def test_a_scale_of_one_is_remembered_but_not_offered_as_a_window_hint(persisted,
                                                                      monkeypatch):
    """1.0 is already the last resort for every template, so promoting it as the
    window's scale would say nothing and could displace a real hint."""
    im._record_scale(KEY, 1.0)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)
    im._load_persisted()
    assert im._window_scale == {}


def test_a_different_window_size_is_a_different_entry(persisted, monkeypatch):
    im._record_scale(KEY, 1.4644)
    im._record_scale(("templates/a.png", 1236, 696), 1.0)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)

    assert im._scale_order(KEY)[0] == pytest.approx(1.4644)
    assert im._scale_order(("templates/a.png", 1236, 696))[0] == pytest.approx(1.0)


def test_a_corrupt_file_is_ignored_rather_than_fatal(persisted, monkeypatch):
    persisted.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(im, "_persist_loaded", False)
    im._load_persisted()                      # must not raise
    assert im._scale_cache == {}


@pytest.mark.parametrize("payload", [
    '{"scales": "not a dict"}',
    '{"scales": {"badkey": 1.5}}',
    '{"scales": {"templates/a.png|1810|1020": "not a number"}}',
    '{"scales": {"templates/a.png|1810|1020": -1}}',
    '{"scales": {"templates/a.png|x|1020": 1.5}}',
    '{}',
])
def test_a_malformed_entry_is_dropped_not_trusted(persisted, monkeypatch, payload):
    """A wrong scale costs one failed comparison and then normal discovery, so ignoring
    junk is enough — but a *negative* or non-numeric one would resize to nothing."""
    persisted.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(im, "_persist_loaded", False)
    im._load_persisted()
    assert im._scale_cache == {}


def test_a_stale_scale_does_not_wedge_the_matcher(persisted, monkeypatch):
    """The reason nothing validates the file. A template re-captured at another size has
    a wrong remembered scale; the cheap path simply misses and discovery runs."""
    im._record_scale(KEY, 3.0)
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)
    order = im._scale_order(KEY)
    assert order[0] == pytest.approx(3.0)
    assert order[-1] == 1.0, "a wrong memory must not remove the fallback"


def test_the_file_is_bounded(persisted, monkeypatch):
    monkeypatch.setattr(im, "_PERSIST_LIMIT", 5)
    for i in range(12):
        im._record_scale((f"templates/{i}.png", 1810, 1020), 1.0 + i / 100)
    written = json.loads(persisted.read_text(encoding="utf-8"))["scales"]
    assert len(written) == 5
    # The newest, because the oldest window size is the least likely to come back.
    assert "templates/11.png|1810|1020" in written


def test_persistence_off_touches_no_disk(tmp_path, monkeypatch):
    target = tmp_path / ".scale_cache.json"
    monkeypatch.setattr(im, "_persist_path", lambda: target)
    im.set_persistence(False)
    im._record_scale(KEY, 1.4644)
    assert not target.exists(), "the suite would be writing to the user's data directory"


def test_a_second_session_does_not_pay_for_discovery_again(persisted, monkeypatch):
    """The measurement the whole change is for, end to end through the real search.

    A needle that only matches when scaled up costs a full two-stage discovery the first
    time. With the scale remembered, the cheap path answers on its first guess — and the
    assertion counts *comparisons* rather than seconds, because a wall-clock threshold on
    a test machine is a flake waiting to happen.
    """
    import cv2

    # Structured content, not noise. Random pixels do not survive resampling — the
    # correct scale scored 0.519 on a noise fixture — while edges and blocks do, which is
    # what a real button or banner is made of.
    hay = np.full((700, 900, 3), 40, np.uint8)
    rng = np.random.default_rng(11)
    for i in range(60):
        x, y = int(rng.integers(0, 860)), int(rng.integers(0, 660))
        cv2.rectangle(hay, (x, y), (x + 30, y + 20),
                      tuple(int(v) for v in rng.integers(60, 200, 3)), -1)
    cv2.rectangle(hay, (400, 300), (520, 360), (250, 250, 250), -1)
    cv2.rectangle(hay, (410, 310), (510, 350), (20, 20, 30), -1)
    cv2.putText(hay, "ATTACK", (415, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (250, 250, 250), 2)
    element = hay[300:360, 400:520].copy()
    # The template as if captured on a smaller window, so the engine must scale it UP.
    small = cv2.resize(element, (element.shape[1] * 100 // 146,
                                 element.shape[0] * 100 // 146),
                       interpolation=cv2.INTER_AREA)
    path = persisted.parent / "needle.png"
    cv2.imwrite(str(path), small)
    key = (str(path), hay.shape[1], hay.shape[0])

    scored = []
    real_score_at = im._score_at
    monkeypatch.setattr(
        im, "_score_at",
        lambda h, n, s: (scored.append(s), real_score_at(h, n, s))[1])

    with im.unrationed_discovery():
        scale = im._discover_scale(hay, small)
    assert scale and scale != 1.0, "the fixture must actually need scaling"
    discovery_comparisons = len(scored)
    assert discovery_comparisons > 10, (
        f"discovery should be a search, not a lucky guess "
        f"({discovery_comparisons} comparisons)")
    im._record_scale(key, scale)

    # A new process: memory cleared, the file kept.
    im.clear_scale_cache()
    monkeypatch.setattr(im, "_persist_loaded", False)
    scored.clear()

    order = im._scale_order(key)
    assert order[0] == pytest.approx(scale)
    assert len(scored) == 0, "reading the cache must not score anything"
    assert real_score_at(hay, small, order[0]) > 0.9, "the remembered scale still matches"
    print(f"\n    {discovery_comparisons} comparisons to discover, "
          f"0 to remember (first guess correct)")
