"""Tests for judging a crop at capture time.

The three findings each stand in for a real failure this project hit: a flat crop
that the matcher refuses outright, an element that appears several times so
find_and_click picks an arbitrary one, and the measured case of a plain `OK` button
scoring 0.91 against a completely different button on the same screen.
"""

import cv2
import numpy as np
import pytest

from engine import image_matcher as im
from engine import template_check as tc

pytestmark = pytest.mark.unit


def _noise(w=40, h=30, seed=0):
    """A crop with enough structure to be matchable, and unique to its seed."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def _flat(w=40, h=30, value=200):
    return np.full((h, w, 3), value, dtype=np.uint8)


def _ui_element(w=295, h=109):
    """A crop with the kind of structure a real UI element has.

    Random noise is the wrong fixture for anything involving rescaling: it is all
    high-frequency, so downscaling destroys the correlation that a button's edges and
    lettering keep. Using noise here would have made a scale-aware check look broken.
    """
    img = np.full((h, w, 3), 30, dtype=np.uint8)
    cv2.rectangle(img, (4, 4), (w - 5, h - 5), (210, 190, 120), -1)
    cv2.rectangle(img, (4, 4), (w - 5, h - 5), (60, 50, 30), max(1, h // 24))
    cv2.putText(img, "Attack", (int(w * 0.14), int(h * 0.66)),
                cv2.FONT_HERSHEY_DUPLEX, w / 260.0, (40, 30, 20), max(1, h // 30))
    cv2.circle(img, (int(w * 0.85), h // 2), h // 5, (90, 60, 200), -1)
    return img


def _screen_with(crop, at=(301, 403), size=(1280, 720), seed=99):
    """A screen containing *crop* once, at a deliberately unaligned position."""
    rng = np.random.default_rng(seed)
    screen = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    x, y = at
    screen[y:y + crop.shape[0], x:x + crop.shape[1]] = crop
    return screen


# ── the crop itself ───────────────────────────────────────────────────────────

def test_a_flat_crop_is_a_blocker():
    findings = tc.inspect_crop(_flat())
    assert len(findings) == 1
    assert findings[0].code == "featureless"
    assert findings[0].blocks is True


def test_the_bar_is_the_matcher_s_own():
    """The wizard must not accept what the engine will reject: image_matcher raises
    TemplateUnusable below the same standard deviation."""
    assert tc.contrast(_flat()) < im.MIN_NEEDLE_STD
    assert tc.contrast(_noise()) > im.MIN_NEEDLE_STD


def test_a_flat_crop_stops_further_checks():
    """Nothing else is worth reporting about a crop the matcher will never match."""
    crop = _flat()
    findings = tc.inspect_crop(crop, screen=_screen_with(crop), existing=[])
    assert [f.code for f in findings] == ["featureless"]


def test_an_unreadable_capture_is_a_blocker():
    assert tc.inspect_crop(None)[0].code == "unreadable"
    assert tc.inspect_crop(np.zeros((0, 0, 3), dtype=np.uint8))[0].code == "unreadable"


def test_a_good_crop_on_a_clean_screen_has_nothing_to_say():
    crop = _noise(seed=1)
    assert tc.inspect_crop(crop, screen=_screen_with(crop), existing=[]) == []


# ── uniqueness on the screen it came from ─────────────────────────────────────

def test_a_crop_that_appears_more_than_once_is_reported():
    """find_and_click clicks the single best match, so which of five identical
    buttons it picks is not something the macro controls."""
    crop = _noise(seed=2)
    screen = _screen_with(crop, at=(301, 403))
    for x, y in ((100, 100), (700, 500), (900, 120)):
        screen[y:y + crop.shape[0], x:x + crop.shape[1]] = crop

    findings = tc.inspect_crop(crop, screen=screen)
    assert [f.code for f in findings] == ["not_unique"]
    assert "4 times" in findings[0].message
    assert findings[0].blocks is False    # find_all_and_click is built on this


def test_a_crop_that_cannot_find_itself_is_reported():
    """Which normally means the screen moved between the grab and the crop."""
    findings = tc.inspect_crop(_noise(seed=3), screen=_screen_with(_noise(seed=4)))
    assert [f.code for f in findings] == ["not_found_on_screen"]


def test_with_no_screen_only_the_crop_is_judged():
    assert tc.inspect_crop(_noise(seed=5)) == []


def test_a_crop_larger_than_the_screen_is_not_judged_against_it():
    big = _noise(w=2000, h=1500, seed=6)
    assert [f.code for f in tc.inspect_crop(big, screen=_screen_with(_noise()))] == []


# ── collision with templates already captured ─────────────────────────────────

def test_a_near_duplicate_of_an_existing_template_is_reported(tmp_path):
    """The measured case: two crops the engine cannot tell apart at the threshold
    macros click at, however different they look to a person."""
    existing = tmp_path / "already.png"
    base = _noise(seed=7)
    cv2.imwrite(str(existing), base)

    # The same element captured a pixel differently — visually identical.
    findings = tc.inspect_crop(base.copy(), existing=[existing])
    assert [f.code for f in findings] == ["collides"]
    assert "already.png" in findings[0].message


def test_the_same_element_captured_at_another_window_size_is_a_collision(tmp_path):
    """The check claims the engine cannot tell two crops apart, and the engine is
    scale-aware — so the check has to be. Comparing crops as stored missed this twice
    in one session: the same Realm Raid attack button captured at 2840x1600 and at
    1236x696 scored 0.31 stored and 0.85 across scales.
    """
    big = _ui_element(295, 109)
    existing = tmp_path / "same_element_bigger.png"
    cv2.imwrite(str(existing), big)

    # The same element as it would come out of a window 0.435x the size — a ratio that
    # deliberately falls *between* the 0.400 and 0.448 rungs of the coarse ladder, so a
    # coarse-only search reports nothing and the fine pass is what finds it.
    small = cv2.resize(big, (int(295 * 0.435), int(109 * 0.435)),
                       interpolation=cv2.INTER_AREA)

    assert tc._cross_score(small, big) >= tc.DEFAULT_THRESHOLD
    assert [f.code for f in tc.inspect_crop(small, existing=[existing])] == ["collides"]


def test_cross_scoring_gives_the_same_answer_either_way_round():
    big = _ui_element(200, 80)
    small = cv2.resize(big, (100, 40), interpolation=cv2.INTER_AREA)
    assert tc._cross_score(small, big) == tc._cross_score(big, small)


def test_a_non_ascii_path_is_still_read(tmp_path):
    """cv2.imread returns None for a non-ASCII path on Windows, and here that failure
    is silent: the collision check would skip every existing template and pass an exact
    duplicate as clean. Templates live under %APPDATA%, so one accented character in a
    profile name is enough."""
    accented = tmp_path / "Nguyễn Đạt"
    accented.mkdir()
    path = accented / "tệp_mẫu.png"
    crop = _noise(seed=23)
    # cv2.imwrite cannot write here either, so encode and let Python place the bytes.
    # The app itself saves through PIL, which handles these paths, so only reading was
    # ever broken.
    path.write_bytes(cv2.imencode(".png", crop)[1].tobytes())

    assert cv2.imread(str(path)) is None, "premise: OpenCV cannot open this path"
    assert tc.as_bgr(path) is not None
    assert [f.code for f in tc.inspect_crop(crop.copy(), existing=[path])] == \
        ["collides"]


def test_a_texture_that_matches_everywhere_is_reported_without_deduplicating(tmp_path):
    """Deduplicating thousands of hits is quadratic: measured 57 s inside _nms on a
    real desktop for one small crop, which is a frozen capture dialog. Past a couple of
    hundred hits the exact number tells the user nothing anyway."""
    tile = _noise(w=16, h=16, seed=24)
    screen = np.tile(tile, (40, 60, 1))          # the same 16x16 patch everywhere

    import time as _time
    started = _time.monotonic()
    findings = tc.inspect_crop(tile, screen=screen)
    elapsed = _time.monotonic() - started

    assert [f.code for f in findings] == ["not_unique"]
    assert "over 200" in findings[0].message
    assert elapsed < 5.0, f"took {elapsed:.1f}s — the dialog would be frozen"


def test_an_unrelated_template_is_not_reported(tmp_path):
    existing = tmp_path / "other.png"
    cv2.imwrite(str(existing), _noise(seed=8))
    assert tc.inspect_crop(_noise(seed=9), existing=[existing]) == []


def test_the_collision_bar_is_the_threshold_macros_click_at(tmp_path):
    """Reporting below it would name collisions the engine would never make."""
    assert tc.DEFAULT_THRESHOLD == 0.80

    existing = tmp_path / "a.png"
    base = _noise(seed=10)
    cv2.imwrite(str(existing), base)
    # Same crop, so the score is 1.0: reported at any threshold up to 1.0...
    assert tc.inspect_crop(base.copy(), existing=[existing], threshold=1.0)
    # ...and a threshold above what correlation can reach reports nothing.
    assert tc.inspect_crop(base.copy(), existing=[existing], threshold=1.01) == []


def test_an_already_unusable_template_is_not_blamed_on_this_crop(tmp_path):
    flat = tmp_path / "flat.png"
    cv2.imwrite(str(flat), _flat())
    assert tc.inspect_crop(_noise(seed=11), existing=[flat]) == []


def test_crops_that_do_not_fit_inside_each_other_are_skipped(tmp_path):
    """A wider-but-shorter crop cannot be compared by matching one in the other,
    and resizing would report a similarity the matcher may never produce."""
    existing = tmp_path / "wide.png"
    cv2.imwrite(str(existing), _noise(w=200, h=10, seed=12))
    tall = _noise(w=10, h=200, seed=12)
    assert tc.inspect_crop(tall, existing=[existing]) == []


def test_a_missing_or_corrupt_existing_file_is_ignored(tmp_path):
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a png")
    assert tc.inspect_crop(_noise(seed=13),
                           existing=[corrupt, tmp_path / "gone.png"]) == []


# ── inputs and reporting ──────────────────────────────────────────────────────

def test_pil_images_and_paths_are_accepted(tmp_path):
    from PIL import Image

    path = tmp_path / "p.png"
    crop = _noise(seed=14)
    cv2.imwrite(str(path), crop)

    assert tc.as_bgr(path).shape == crop.shape
    pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    assert np.array_equal(tc.as_bgr(pil), crop)
    assert tc.as_bgr(Image.fromarray(np.zeros((4, 4), dtype=np.uint8))).shape[2] == 3


def test_findings_are_reported_worst_first():
    crop = _flat()
    findings = tc.inspect_crop(crop, screen=_screen_with(crop))
    assert findings[0].blocks is True


def test_summarise_is_empty_for_a_clean_crop():
    assert tc.summarise([]) == ""
    two = [tc.Finding(tc.WARNING, "a", "first"), tc.Finding(tc.WARNING, "b", "second")]
    assert tc.summarise(two).startswith("first") and "+1 more" in tc.summarise(two)


def test_re_capturing_a_template_does_not_collide_with_itself(tmp_path):
    """other_templates excludes the file being replaced, or every re-capture would
    report a collision with the version it is replacing."""
    from gui.capture_review import other_templates

    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    names = {p.name for p in other_templates(tmp_path, exclude="a.png")}
    assert names == {"b.png"}
    assert len(other_templates(tmp_path)) == 2
    assert other_templates(tmp_path / "missing") == []
