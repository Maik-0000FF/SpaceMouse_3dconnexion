"""Guard against drift between the ``COLOR_*`` constants and the hex
literals embedded in the ``DARK_THEME`` QSS block.

``constants.py`` notes that the two must be kept in sync manually. This
test enforces that contract in CI: any ``#xxxxxx`` literal appearing in
``DARK_THEME`` must also be the value of some ``COLOR_*`` constant."""

import re

from spacemouse_config import constants


def test_dark_theme_hex_literals_are_in_palette():
    palette_values = {
        v for k, v in vars(constants).items() if k.startswith("COLOR_") and isinstance(v, str)
    }
    hex_in_theme = set(re.findall(r"#[0-9a-fA-F]{6}", constants.DARK_THEME))
    drift = hex_in_theme - palette_values
    assert not drift, (
        f"DARK_THEME contains hex literals not in the palette: {sorted(drift)}. "
        "Add them as COLOR_* constants or update the QSS block to reference "
        "the existing constants."
    )
