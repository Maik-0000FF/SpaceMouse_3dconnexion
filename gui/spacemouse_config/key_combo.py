"""Qt-free helpers for parsing and formatting "key:Mod+Key" combo
strings used by the Buttons-card key-combo binding.

The daemon's combo parser (src/config.c::parse_key_combo) accepts
strings like ``Ctrl+Shift+S`` — zero or more modifiers joined by ``+``
followed by an end key from KEY_NAMES. These helpers mirror that
parser on the Python side so the GUI can canonicalise input from the
combo dialog before writing config.json. They live in their own
module (not key_combo_dialog.py) so the pytest job stays runnable
without a PySide6 install.
"""

from .constants import COMBO_KEY_NAMES, COMBO_MODIFIER_NAMES

# Map every modifier spelling the daemon parser accepts onto the
# canonical name we emit. Lower-cased lookup so case in the source
# config doesn't matter. The canonical names are exactly those in
# COMBO_MODIFIER_NAMES so format_combo can reuse that ordering.
_MOD_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "meta": "Meta",
    "super": "Meta",
    "win": "Meta",
    "cmd": "Meta",
}

# Lower-case → canonical-display mapping so parse can accept any case
# (the daemon's lookup_key uses strcasecmp) and emit the readable form
# back from COMBO_KEY_NAMES.
_KEY_CANONICAL = {k.lower(): k for k in COMBO_KEY_NAMES}


def parse_combo_string(s):
    """Parse a combo body like ``Ctrl+Shift+S`` into ``(mods, key)``.

    The body is the part after the ``key:`` prefix the daemon expects.
    Modifier spellings (Ctrl/Control, Meta/Super/Win/Cmd, …) are
    normalised onto the canonical names listed in
    :data:`constants.COMBO_MODIFIER_NAMES`. The end key is normalised
    to the display form from :data:`constants.COMBO_KEY_NAMES`. Returns
    ``([], "")`` on parse failure so a caller editing a malformed
    config doesn't crash — the dialog re-opens with empty state.
    """
    if not isinstance(s, str) or not s.strip():
        return [], ""
    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        return [], ""
    end = _KEY_CANONICAL.get(parts[-1].lower())
    if end is None:
        return [], ""
    seen = set()
    mods = []
    for raw in parts[:-1]:
        canonical = _MOD_ALIASES.get(raw.lower())
        if canonical is None:
            return [], ""
        if canonical in seen:
            # Duplicate modifier — daemon parser rejects this too, so
            # mirror that behaviour rather than silently dedup'ing.
            return [], ""
        seen.add(canonical)
        mods.append(canonical)
    return mods, end


def format_combo(mods, key):
    """Build a canonical combo string from a list/set of modifiers and
    end key. Modifier order is forced to Ctrl→Shift→Alt→Meta so the
    written config is stable regardless of which order the dialog's
    checkboxes were toggled in. Empty key returns the empty string —
    the caller will treat the row as unconfigured."""
    if not key:
        return ""
    mods_set = {m for m in (mods or []) if m in COMBO_MODIFIER_NAMES}
    ordered = [m for m in COMBO_MODIFIER_NAMES if m in mods_set]
    return "+".join([*ordered, key])
