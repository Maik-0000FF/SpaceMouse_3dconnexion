#!/usr/bin/env python3
"""SpaceMouse Control launcher.

The GUI is split across the ``spacemouse_config`` package. This launcher is
installed by ``install.sh`` to ``~/.local/bin/spacemouse-config.py`` while the
package itself is copied to ``~/.local/share/spacemouse/spacemouse_config/``.

The same script also works straight from a checked-out source tree: in that
case the package lives next to this file under ``gui/``.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INSTALL = Path.home() / ".local" / "share" / "spacemouse"

for _cand in (_HERE, _INSTALL):
    if (_cand / "spacemouse_config" / "__init__.py").is_file():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break

from spacemouse_config.app import main  # noqa: E402

if __name__ == "__main__":
    main()
