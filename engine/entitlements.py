"""
Feature entitlements — the single source of truth for what each license tier
may do.

The free tier stays genuinely useful (record-and-replay of basic input on up to
a couple of macros) while the high-value automation that people actually pay a
bot for is reserved for Pro:

    * background mode (PostMessage input without moving the real cursor)
    * image / pixel / rectangle detection
    * loop mode
    * running a whole folder of macros in parallel (multi-accounting)

The engine consults this module before saving or running a macro. Keeping all
gating here means there is exactly one place to tune the free/paid line.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from engine.product_config import PRODUCT_NAME


class Tier(str, Enum):
    """A user's licensing tier."""

    FREE = "free"
    PRO = "pro"


# Sentinel for "no limit".
UNLIMITED: int = -1

# Detection actions are the paid value-add (vision / branching automation).
DETECTION_ACTIONS = frozenset(
    {
        "pixel_wait",
        "pixel_check",
        "find_and_click",
        "image_wait",
        "image_check",
        "find_rects_and_click",
        "find_all_and_click",
    }
)

# Basic input actions available on every tier.
BASIC_ACTIONS = frozenset(
    {
        "move",
        "click",
        "double_click",
        "right_click",
        "drag",
        "scroll",
        "key",
        "type",
        "wait",
        "stop",
    }
)


@dataclass(frozen=True)
class Entitlements:
    """Immutable description of what a tier is allowed to do."""

    tier: Tier
    max_macros: int
    background: bool
    detection: bool
    loop: bool
    parallel_folder: bool

    @property
    def unlimited_macros(self) -> bool:
        return self.max_macros == UNLIMITED


_FREE = Entitlements(
    tier=Tier.FREE,
    max_macros=2,
    background=False,
    detection=False,
    loop=False,
    parallel_folder=False,
)

_PRO = Entitlements(
    tier=Tier.PRO,
    max_macros=UNLIMITED,
    background=True,
    detection=True,
    loop=True,
    parallel_folder=True,
)

_BY_TIER: Dict[Tier, Entitlements] = {Tier.FREE: _FREE, Tier.PRO: _PRO}


def for_tier(tier: Tier) -> Entitlements:
    """Return the entitlements for *tier* (defaults to FREE if unknown)."""
    return _BY_TIER.get(tier, _FREE)


class LockedFeatureError(Exception):
    """Raised when an action requires a higher tier than the user has."""

    def __init__(self, message: str, feature: str = "") -> None:
        super().__init__(message)
        self.feature = feature
        self.message = message


# ── macro inspection ──────────────────────────────────────────────────────────


def _iter_action_types(actions: List[Dict]) -> List[str]:
    """Flatten every action 'type' in a macro, recursing into branches."""
    found: List[str] = []
    for action in actions or []:
        t = action.get("type")
        if t:
            found.append(t)
        for branch in ("on_match", "on_no_match", "on_found", "on_not_found"):
            if isinstance(action.get(branch), list):
                found.extend(_iter_action_types(action[branch]))
    return found


def macro_required_features(macro: Dict) -> Dict[str, bool]:
    """Return which gated features a macro relies on."""
    types = _iter_action_types(macro.get("actions", []))
    return {
        "background": bool(macro.get("background", False)),
        "detection": any(t in DETECTION_ACTIONS for t in types),
        "loop": bool(macro.get("loop", False)),
    }


# ── gate checks (return a human-readable upgrade message, or None) ────────────

_UPGRADE_HINT = f"Upgrade to {PRODUCT_NAME} Pro to unlock this."


def check_macro_runnable(macro: Dict, ent: Entitlements) -> Optional[str]:
    """Return an upgrade message if *macro* uses a feature *ent* lacks."""
    needs = macro_required_features(macro)
    if needs["background"] and not ent.background:
        return f"Background mode is a Pro feature. {_UPGRADE_HINT}"
    if needs["detection"] and not ent.detection:
        return (
            "Image / pixel / rectangle detection is a Pro feature. "
            f"{_UPGRADE_HINT}"
        )
    if needs["loop"] and not ent.loop:
        return f"Loop mode is a Pro feature. {_UPGRADE_HINT}"
    return None


def check_can_create(current_count: int, ent: Entitlements) -> Optional[str]:
    """Return an upgrade message if creating another macro exceeds the limit."""
    if ent.unlimited_macros:
        return None
    if current_count >= ent.max_macros:
        return (
            f"The free tier is limited to {ent.max_macros} macros. "
            f"{_UPGRADE_HINT}"
        )
    return None


def check_parallel(ent: Entitlements) -> Optional[str]:
    """Return an upgrade message if parallel folder runs are not allowed."""
    if ent.parallel_folder:
        return None
    return (
        "Running macros in parallel (multi-accounting) is a Pro feature. "
        f"{_UPGRADE_HINT}"
    )
