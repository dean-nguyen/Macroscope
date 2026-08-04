"""Import every engine and gui module, and fail if any of them cannot be.

The GUI has no test coverage, so a syntax error or a stale import in gui/ reaches
main unnoticed — that is exactly how gui/inspector.py came to call a helper the
engine no longer had. Importing is cheap, needs no display (no Tk window is
created), and catches that whole class of breakage.

Run locally the same way CI does:

    python tools/import_check.py
"""

import importlib
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PACKAGES = ("engine", "gui")


def main() -> int:
    failed = []
    for package in PACKAGES:
        for mod in pkgutil.iter_modules([str(ROOT / package)]):
            name = f"{package}.{mod.name}"
            try:
                importlib.import_module(name)
            except Exception as exc:
                failed.append(name)
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            else:
                print(f"ok   {name}")

    print()
    if failed:
        print(f"{len(failed)} module(s) failed to import: {', '.join(failed)}")
        return 1
    print("all modules import cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
