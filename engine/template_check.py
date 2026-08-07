"""Judge a freshly captured template before it is saved.

The engine can already tell a user that a template *did not match* — the log
prints every check and its score, and `tools/match_report.py` scores everything
against a live window. What it could not do is tell them their crop was never
going to work, at the one moment they can trivially fix it: while the game is
still on the screen they cropped it from.

Three things go wrong at capture time, and each is checked here against measured
behaviour rather than a rule of thumb:

- **A featureless crop.** An empty panel or a flat button fill correlates with
  anything, so `image_matcher` refuses to match it at all. Held to exactly the
  matcher's own bar, so the wizard cannot accept something the engine will reject.
- **A crop that is not unique on its own screen.** `find_and_click` clicks the
  single best match, so a crop that appears five times clicks an arbitrary one of
  them. This is measured directly, by counting matches on the screen the crop came
  from, rather than guessing from the crop's size.
- **A crop that collides with a template already captured.** Measured on a live
  game: a plain `OK` button scored 0.91 against a completely different button on
  the same screen, because the two share their chrome and `OK` is two characters of
  text. Two templates that score above the threshold macros click at are
  interchangeable to the engine, whatever they look like to a person.

The comparison threshold defaults to 0.80 — the value the pack uses for anything it
clicks — because that is the number that decides whether a macro can tell two
things apart. A lower bar here would report collisions the engine would never make.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import cv2
import numpy as np

from engine import image_matcher as im

# The threshold the pack clicks at, so a collision reported here is a collision
# the engine could actually make.
DEFAULT_THRESHOLD = 0.80

BLOCKER = "blocker"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """Something wrong with a crop. ``blocker`` means the engine cannot use it."""

    level: str
    code: str
    message: str

    @property
    def blocks(self) -> bool:
        return self.level == BLOCKER


def as_bgr(image) -> Optional[np.ndarray]:
    """Accept a PIL image, a numpy array, or a path; return BGR uint8 or None."""
    if image is None:
        return None
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image
    if isinstance(image, (str, Path)):
        # The matcher's reader, not cv2.imread: a non-ASCII path returns None from
        # OpenCV, and here that failure is silent — the collision check would skip
        # every existing template and pass an exact duplicate as clean.
        return im.imread_unicode(image)
    try:                                    # PIL image
        return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def contrast(crop) -> float:
    """Standard deviation of a crop — what the matcher judges usability by."""
    arr = as_bgr(crop)
    return 0.0 if arr is None else float(arr.std())


def inspect_crop(
    crop,
    screen=None,
    existing: Iterable = (),
    threshold: float = DEFAULT_THRESHOLD,
) -> List[Finding]:
    """Everything wrong with *crop*, worst first.

    *screen* is the full screenshot the crop was taken from — pass the same grab
    it was cropped out of, not a fresh one, or an animating game will look like a
    crop that cannot find itself. *existing* is the templates already captured.
    """
    needle = as_bgr(crop)
    if needle is None or needle.size == 0:
        return [Finding(BLOCKER, "unreadable",
                        "That capture could not be read as an image.")]

    findings: List[Finding] = []

    std = float(needle.std())
    if std < im.MIN_NEEDLE_STD:
        # No point checking anything else: the matcher will not match this at all.
        return [Finding(
            BLOCKER, "featureless",
            f"This crop is almost all one colour (contrast {std:.1f}, the engine "
            f"needs {im.MIN_NEEDLE_STD:.0f}). Normalised correlation divides by "
            f"the variation in the image, so a flat crop matches anywhere — the "
            f"engine will refuse it rather than mis-click. Crop tighter, or "
            f"include some text or an edge.")]

    findings.extend(_screen_findings(needle, screen, threshold))
    findings.extend(_collision_findings(needle, existing, threshold))
    return findings


# Above this many raw hits, stop counting and just say "many". Deduplicating them is
# quadratic (image_matcher._nms is a Python double loop), and a small crop of ordinary
# screen content produces thousands: measured on a real 6400x2400 desktop, a 16 px crop
# hit 12779 positions and one worst case spent 57 s inside _nms alone — a frozen capture
# dialog. The exact number past this point tells the user nothing they cannot see.
_TOO_MANY_HITS = 200


def _screen_findings(needle, screen, threshold: float) -> List[Finding]:
    haystack = as_bgr(screen)
    if haystack is None:
        return []
    if needle.shape[0] > haystack.shape[0] or needle.shape[1] > haystack.shape[1]:
        return []
    if float(needle.std()) < im.MIN_NEEDLE_STD:
        return []

    # Count the raw hits first. Only a small set is worth deduplicating.
    raw = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    hits = int(np.count_nonzero(raw >= threshold))
    if hits > _TOO_MANY_HITS:
        return [Finding(
            WARNING, "not_unique",
            f"This matches the screen you captured it from in over "
            f"{_TOO_MANY_HITS} places at threshold {threshold:.2f}, so it is not a "
            f"crop of one thing — it is a piece of texture that occurs all over. "
            f"find_and_click would pick an arbitrary one. Crop something with an "
            f"edge, a word, or an icon in it.")]

    matches = im._cv_match_all(haystack, needle, threshold) if hits else []
    if len(matches) > 1:
        return [Finding(
            WARNING, "not_unique",
            f"This appears {len(matches)} times on the screen you captured it "
            f"from, at threshold {threshold:.2f}. find_and_click clicks the single "
            f"best match, so which one it picks is not something the macro "
            f"controls. Include something that differs between them — a label, or "
            f"a bit of the surrounding panel.")]
    if not hits:
        # It came out of this screen, so it should find itself. Worth saying,
        # because it usually means the screen moved between grab and crop.
        return [Finding(
            WARNING, "not_found_on_screen",
            "This does not match the screen it was captured from, which normally "
            "means the window changed while you were cropping. Capture it again "
            "with the screen holding still.")]
    return []


def _collision_findings(needle, existing: Iterable, threshold: float) -> List[Finding]:
    """Templates already captured that the engine could not tell this one from."""
    scored: List[tuple] = []
    for path in existing:
        other = as_bgr(path)
        if other is None or other.size == 0:
            continue
        if float(other.std()) < im.MIN_NEEDLE_STD:
            continue                        # already unusable; not this crop's fault
        score = _cross_score(needle, other)
        if score is not None and score >= threshold:
            scored.append((score, Finding(
                WARNING, "collides",
                f"Scores {score:.2f} against '{Path(str(path)).name}', which is "
                f"already captured — at or above the {threshold:.2f} macros click "
                f"at, so the engine cannot reliably tell them apart even if they "
                f"look different to you. Crop one of them to include more of what "
                f"makes it different.")))
    # Worst collision first, sorted on the score itself rather than on the rendered
    # sentence. Not a bug fix and there is nothing to test: scores are clamped to
    # [0, 1] and formatted to two decimals, so every reachable string sorts the same
    # way the number does. It stops being true the day the wording changes.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [finding for _score, finding in scored]


def _cross_score(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    """Best correlation between two crops, **across scales**, or None if they can
    never be compared.

    Scale-aware because the matcher is. Comparing the crops only as stored has a
    blind spot that live use walked straight into: the Realm Raid attack button
    captured from a 2840x1600 window and the same button captured from a 1236x696
    window scored 0.31 as stored and **0.8468 at scale 0.43** — the ratio between
    those two windows. As-stored comparison would have called them unrelated and let
    a redundant template into the pack, which is precisely the collision a user
    creates by re-capturing at a different window size.

    The search is the matcher's own **two-stage** one — coarse ladder, then a fine pass
    around the winner — walked in both directions so the answer does not depend on
    which crop was passed first. The coarse ladder alone is not enough, and live use
    proved it: two captures of the same "Tap to continue" bar, 505x64 and 220x28, sit
    at a ratio of 0.435, which falls between the 0.400 and 0.448 rungs. Coarse-only
    scored them below the bar and reported nothing.

    Measured on the pack's own templates: **~42 ms per pair, worst 73 ms**, essentially
    all of it inside matchTemplate. That is per *already-captured* template, so the
    check grows with the templates directory and is why `gui/capture_review.py` runs it
    off the UI thread.
    """
    coarse, best = _best_cross(a, b, im._SCALE_LADDER)
    if coarse is None:
        return None
    fine = [round(coarse * f, 4) for f in im._REFINE_FACTORS]
    _, refined = _best_cross(a, b, fine)
    return max(best, refined)


def _best_cross(a: np.ndarray, b: np.ndarray, scales) -> tuple:
    """(scale of the best correlation, that correlation) over *scales*."""
    best_scale, best = None, -1.0
    for scale in scales:
        for needle, haystack in ((a, b), (b, a)):
            scaled = needle if scale == 1.0 else im._resize_needle(needle, scale)
            if not _fits(scaled, haystack):
                continue
            if float(scaled.std()) < im.MIN_NEEDLE_STD:
                continue
            result = cv2.matchTemplate(haystack, scaled, cv2.TM_CCOEFF_NORMED)
            score = im._clamp_score(cv2.minMaxLoc(result)[1])
            if score > best:
                best_scale, best = scale, score
    return best_scale, best


def _fits(small: np.ndarray, large: np.ndarray) -> bool:
    return small.shape[0] <= large.shape[0] and small.shape[1] <= large.shape[1]


def summarise(findings: Sequence[Finding]) -> str:
    """One line for a status label. Empty when there is nothing to say."""
    if not findings:
        return ""
    if len(findings) == 1:
        return findings[0].message
    return findings[0].message + f"  (+{len(findings) - 1} more)"
