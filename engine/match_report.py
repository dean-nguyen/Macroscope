"""Score every captured template against a live window.

This answers the question users and pack authors actually ask — "why doesn't my
template match?" — and it is the single most useful diagnostic this project has. It
found the discovery-ration bug, the wrong `reward_confirm` threshold and two
duplicate templates in three days of live use, and until now it existed only as a
CLI, which is to say it did not exist for anyone who did not read the source.

Scores are raw `TM_CCOEFF_NORMED` with anticorrelation floored at 0, so the number
means what it says. Measured on a live game window: a template that IS on screen
scores ~0.92-0.99 and absent ones reach ~0.47. If everything scores in the 0.40s,
nothing is matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from engine import image_matcher as im
from engine.paths import TEMPLATES_DIR

MATCH = "match"
NO_MATCH = "no match"
UNUSABLE = "unusable"
MISSING = "missing"


class ReportError(RuntimeError):
    """The report could not be produced, with a reason worth showing a user."""


@dataclass(frozen=True)
class TemplateScore:
    name: str
    status: str
    score: Optional[float] = None
    at: Optional[Tuple[int, int]] = None
    std: Optional[float] = None
    note: str = ""

    @property
    def matched(self) -> bool:
        return self.status == MATCH


@dataclass(frozen=True)
class Report:
    title: str
    haystack: Tuple[int, int]
    threshold: float
    effective: float
    rows: List[TemplateScore]

    @property
    def matched(self) -> int:
        return sum(1 for r in self.rows if r.matched)

    @property
    def summary(self) -> str:
        if not self.rows:
            return "no templates to score"
        return (f"{self.matched} of {len(self.rows)} matched on the screen that is "
                f"up right now")


def score_templates(
    hwnd: int,
    threshold: float = 0.80,
    pattern: str = "*.png",
    templates_dir: Optional[Path] = None,
    title: str = "",
) -> Report:
    """Score every template under *templates_dir* against *hwnd* as it looks now.

    Every template gets a scale search, whatever it costs: scoring a whole directory
    in one pass is exactly the batch the ration exists to slow down, and a report that
    says "no match" because the previous template spent the budget is worse than a
    slow one. Measured before that was true: five templates in a row all read "no
    match" while one of their buttons was plainly on screen and scored 0.94 alone.

    The override is scoped, so a report cannot leave macros paying for it.
    """
    import win32gui

    directory = Path(templates_dir) if templates_dir else TEMPLATES_DIR

    if win32gui.IsIconic(hwnd):
        raise ReportError(
            "That window is minimised. No frames are produced while it is, so every "
            "template would report 'no match' — restore it and score again.")

    templates = sorted(directory.glob(pattern))
    if not templates:
        raise ReportError(f"No templates matching {pattern!r} in {directory}")

    with im.unrationed_discovery():
        haystack = im._grab_haystack(hwnd, None)
        if haystack is None:
            raise ReportError("That window could not be captured.")

        rows = [_score_one(path, hwnd, threshold) for path in templates]

    return Report(
        title=title or win32gui.GetWindowText(hwnd),
        haystack=(haystack.shape[1], haystack.shape[0]),
        threshold=threshold,
        effective=threshold - im._WGC_THRESHOLD_OFFSET,
        rows=rows,
    )


def _score_one(path: Path, hwnd: int, threshold: float) -> TemplateScore:
    std = None
    image = im.imread_unicode(path)
    if image is not None:
        std = float(image.std())

    try:
        result = im.find_template(f"templates/{path.name}", hwnd=hwnd,
                                  threshold=threshold)
    except im.TemplateUnusable:
        return TemplateScore(path.name, UNUSABLE, std=std,
                             note="flat or featureless — the matcher refuses it, "
                                  "because a crop with no variation correlates with "
                                  "anything")
    except im.TemplateMissing:
        return TemplateScore(path.name, MISSING, std=std,
                             note="not readable on disk")

    if result:
        cx, cy, score = result
        return TemplateScore(path.name, MATCH, score=score, at=(cx, cy), std=std)
    return TemplateScore(path.name, NO_MATCH, std=std)


ADVICE = (
    "Only templates whose element is actually visible should match. One that matches "
    "while its element is off screen is not distinctive enough — a plain 'OK' button "
    "was measured scoring 0.91 against a completely different button, because two "
    "characters of text cannot outweigh a box of flat fill."
)
