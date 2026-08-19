"""A guard against one specific defect, twice shipped: a name that does not exist.

`admin.py` called `_spawn` and `_rerun_and_report`, which live in `handlers.py`, and
`serve_polling` referenced three locals that its rewrite had moved into `Runtime`. Both
were invisible until the code path ran — one on a button nobody pressed, one on a
transport nobody used.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyflakes() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", "gryag"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_no_undefined_names_anywhere_in_the_package():
    undefined = [line for line in _pyflakes() if "undefined name" in line]

    assert not undefined, "\n".join(undefined)


def test_nothing_is_imported_without_being_used():
    """Unused imports are how a name that used to exist keeps looking like it still does."""
    unused = [line for line in _pyflakes() if "imported but unused" in line]

    assert not unused, "\n".join(unused)
