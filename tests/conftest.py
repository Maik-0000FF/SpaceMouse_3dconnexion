"""pytest setup: make ``gui/`` importable as the ``spacemouse_config`` package."""

import sys
from pathlib import Path

_GUI = Path(__file__).resolve().parent.parent / "gui"
if str(_GUI) not in sys.path:
    sys.path.insert(0, str(_GUI))
