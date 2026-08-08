"""Every command line in tools/README.md must actually parse.

It documented `--title` *after* the subcommand for months, and argparse rejects that:
`--title` belongs to game_probe's own parser, not to its subcommands. Nobody noticed
because nobody runs a README.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "tools" / "README.md"

pytestmark = pytest.mark.unit


def documented_commands():
    """Every `python tools/...` line inside a fenced block in the README."""
    text = README.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.split("#")[0].strip()          # drop trailing comments
        if line.startswith("python tools/"):
            yield line


def test_the_readme_actually_shows_some_commands():
    commands = list(documented_commands())
    assert len(commands) >= 5, commands


@pytest.mark.parametrize("command", list(documented_commands()))
def test_each_documented_command_parses(command):
    parts = shlex.split(command)
    script = Path(parts[1]).name
    args = parts[2:]

    if script == "game_probe.py":
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import game_probe
            game_probe.build_parser().parse_args(args)   # SystemExit if malformed
        finally:
            sys.path.remove(str(ROOT / "tools"))
        return

    # The others have no parser worth importing (they run work at import time or on
    # call), so check the shape argparse would reject: an option after a positional
    # that the tool does not take.
    result = subprocess.run([sys.executable, str(ROOT / parts[1]), "--help"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    for arg in args:
        if arg.startswith("--"):
            assert arg.split("=")[0] in result.stdout, \
                f"{script} does not document {arg}"


def test_the_title_option_must_precede_the_subcommand():
    """The specific mistake, kept as its own line so a regression names itself."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import game_probe
        parser = game_probe.build_parser()
        parser.parse_args(["--title", "Onmyoji", "shot"])     # the documented form
        with pytest.raises(SystemExit):
            parser.parse_args(["shot", "--title", "Onmyoji"])  # what the README said
    finally:
        sys.path.remove(str(ROOT / "tools"))
