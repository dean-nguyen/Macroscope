"""The test count in README.md must be the real one.

It said `# 227 tests` while the suite had 370 — 143 out, and nothing could notice,
because a number in prose is not checked by anything. On a project whose whole pitch is
that its claims are measured, a claim that is 60% off is worse than no claim.

So this fails on the commit that adds a test, and the fix is to update the number. Same
shape as `test_editor_actions.py` failing when a new action is not registered in the
picker: the check exists because the author will not remember.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

pytestmark = pytest.mark.unit


def stated_count() -> int:
    text = README.read_text(encoding="utf-8")
    matches = re.findall(r"#\s*(\d+)\s+tests\b", text)
    assert len(matches) == 1, f"expected one '# N tests' comment, found {matches}"
    return int(matches[0])


def collected_count() -> int:
    """What pytest itself reports. --collect-only does not execute anything, so this
    does not recurse."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    ).stdout
    match = re.search(r"(\d+) tests? collected", out)
    assert match, f"could not read a count from pytest:\n{out[-2000:]}"
    return int(match.group(1))


def test_the_readme_states_the_real_test_count():
    stated, actual = stated_count(), collected_count()
    assert stated == actual, (
        f"README.md says {stated} tests, the suite collects {actual}. "
        f"Update the number in the Development section."
    )
