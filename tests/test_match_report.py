"""Tests for scoring every template against a live window.

This is the project's most useful diagnostic — it found the discovery-ration bug, a
threshold that sat inside its own template's score band, and two duplicate templates
in three days of live use. It lived only in `tools/`, which meant it did not exist for
anyone who had not read the source, so the scoring moved into `engine/` and the app
grew a tab for it. These tests are on the shared part, so the CLI and the tab cannot
disagree about what a score means.
"""

import numpy as np
import pytest

from engine import image_matcher as im
from engine import match_report as mr

pytestmark = pytest.mark.unit


def _templates(tmp_path, *names):
    import cv2
    rng = np.random.default_rng(0)
    for name in names:
        cv2.imwrite(str(tmp_path / name),
                    rng.integers(0, 255, (20, 30, 3), dtype=np.uint8))
    return tmp_path


def _stub_window(monkeypatch, iconic=False, title="A Game"):
    import win32gui
    monkeypatch.setattr(win32gui, "IsIconic", lambda h: iconic)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda h: title)


def _stub_capture(monkeypatch, ok=True):
    frame = np.zeros((696, 1236, 3), dtype=np.uint8) if ok else None
    monkeypatch.setattr(im, "_grab_haystack", lambda hwnd, region: frame)


# ── refusals worth a sentence ─────────────────────────────────────────────────

def test_a_minimised_window_is_refused_with_the_reason(monkeypatch, tmp_path):
    """Every template would read "no match" and the user would blame their crops."""
    _stub_window(monkeypatch, iconic=True)
    with pytest.raises(mr.ReportError) as exc:
        mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert "minimised" in str(exc.value)


def test_no_templates_is_refused(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    with pytest.raises(mr.ReportError):
        mr.score_templates(1, templates_dir=tmp_path)


def test_a_window_that_cannot_be_captured_is_refused(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch, ok=False)
    with pytest.raises(mr.ReportError) as exc:
        mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert "captured" in str(exc.value)


# ── what a row says ───────────────────────────────────────────────────────────

def test_rows_carry_the_score_and_where_it_landed(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    monkeypatch.setattr(im, "find_template",
                        lambda *a, **k: im.Match(120, 240, 0.93, 30, 20))

    report = mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    row = report.rows[0]
    assert row.matched and row.score == pytest.approx(0.93) and row.at == (120, 240)
    assert row.std is not None and row.std > 0
    assert report.matched == 1
    assert "1 of 1" in report.summary


def test_a_miss_is_a_miss_not_an_error(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    monkeypatch.setattr(im, "find_template", lambda *a, **k: None)

    report = mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert report.rows[0].status == mr.NO_MATCH
    assert report.matched == 0


@pytest.mark.parametrize("error,status", [
    (im.TemplateUnusable("flat"), mr.UNUSABLE),
    (im.TemplateMissing("gone"), mr.MISSING),
])
def test_a_template_the_matcher_refuses_is_reported_not_hidden(
        monkeypatch, tmp_path, error, status):
    """The report exists to explain, so "the engine will not use this one" has to be
    on the page — not collapsed into "no match" alongside crops that are simply
    off screen."""
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)

    def raise_it(*_a, **_k):
        raise error

    monkeypatch.setattr(im, "find_template", raise_it)
    report = mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert report.rows[0].status == status
    assert report.rows[0].note


def test_the_effective_threshold_shows_the_wgc_allowance(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    monkeypatch.setattr(im, "find_template", lambda *a, **k: None)

    report = mr.score_templates(1, threshold=0.80,
                                templates_dir=_templates(tmp_path, "a.png"))
    assert report.effective == pytest.approx(0.80 - im._WGC_THRESHOLD_OFFSET)
    assert report.haystack == (1236, 696)


def test_templates_are_scored_in_a_stable_order(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    monkeypatch.setattr(im, "find_template", lambda *a, **k: None)

    report = mr.score_templates(
        1, templates_dir=_templates(tmp_path, "c.png", "a.png", "b.png"))
    assert [r.name for r in report.rows] == ["a.png", "b.png", "c.png"]


# ── the override must not escape ──────────────────────────────────────────────

def test_every_template_gets_a_scale_search(monkeypatch, tmp_path):
    """Without this the report lies: five templates scored in a row all read "no
    match" while one of their buttons was on screen and scored 0.94 alone."""
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    seen = []
    monkeypatch.setattr(im, "find_template",
                        lambda *a, **k: seen.append(im._unrationed) or None)

    mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png", "b.png"))
    assert seen == [True, True]


def test_the_override_does_not_outlive_the_report(monkeypatch, tmp_path):
    """It is a module global and the app scores templates in the same process it runs
    macros in. Left on, every later run pays for unlimited searches."""
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)
    monkeypatch.setattr(im, "find_template", lambda *a, **k: None)

    assert im._unrationed is False
    mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert im._unrationed is False


def test_the_override_is_restored_even_when_scoring_raises(monkeypatch, tmp_path):
    _stub_window(monkeypatch)
    _stub_capture(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(im, "find_template", boom)
    with pytest.raises(RuntimeError):
        mr.score_templates(1, templates_dir=_templates(tmp_path, "a.png"))
    assert im._unrationed is False


def test_the_context_manager_restores_a_nested_state():
    with im.unrationed_discovery():
        assert im._unrationed is True
        with im.unrationed_discovery():
            assert im._unrationed is True
        assert im._unrationed is True, "an inner scope must not switch it off"
    assert im._unrationed is False
