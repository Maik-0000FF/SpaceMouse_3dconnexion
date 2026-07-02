"""Drift guard: the GUI mirrors several daemon tables by hand (the
key-name table, the modifier-alias table, and the object-form action
wire tokens). Nothing enforces that the two copies stay in sync, so a
new key added to the C side but not the Python side (or vice versa)
would silently make that key unbindable from the GUI.

These tests parse the daemon C source and assert the Python tables in
:mod:`spacemouse_config.constants` / :mod:`spacemouse_config.key_combo`
match. They fail loudly the moment the two drift apart. The long-term
fix is a single generated source both sides consume; until then this
keeps the hand-maintained copies honest.
"""

import re
from pathlib import Path

from spacemouse_config import constants, key_combo

_ROOT = Path(__file__).resolve().parent.parent
_CORE_C = _ROOT / "src" / "spacemouse-core.c"
_CONFIG_C = _ROOT / "src" / "config.c"


def _table_names(source, decl):
    """Return the quoted names from the C array initializer for ``decl``.

    Walks from ``decl`` to the initializer's matching closing brace and
    pulls every ``{"NAME", ...}`` entry, skipping the ``{NULL, 0}``
    sentinel (no quoted name).
    """
    start = source.index(decl)
    brace = source.index("{", start)
    depth = 0
    i = brace
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = source[brace : i + 1]
    return [m.group(1) for m in re.finditer(r'\{\s*"([^"]+)"\s*,', block)]


def test_key_name_table_matches_daemon():
    """COMBO_KEY_NAMES must cover exactly the keys the daemon knows.

    Comparison is case-insensitive: the daemon stores upper-case
    (``SPACE``) and looks up with strcasecmp, while the GUI shows
    display case (``Space``).
    """
    c_keys = {n.lower() for n in _table_names(_CORE_C.read_text(), "KEY_NAMES[]")}
    py_keys = {n.lower() for n in constants.COMBO_KEY_NAMES}
    assert c_keys == py_keys, (
        f"key table drift: only in C={c_keys - py_keys}, only in Py={py_keys - c_keys}"
    )


def test_modifier_alias_table_matches_daemon():
    """Every modifier spelling the daemon accepts must be accepted by the
    GUI parser too (and vice versa)."""
    c_mods = {n.lower() for n in _table_names(_CONFIG_C.read_text(), "MOD_NAMES[]")}
    py_mods = set(key_combo._MOD_ALIASES)
    assert c_mods == py_mods, (
        f"modifier alias drift: only in C={c_mods - py_mods}, only in Py={py_mods - c_mods}"
    )


def test_exec_wire_tokens_match_daemon():
    """The object-form action tokens the GUI emits must match the ones
    the daemon parses. Guards the hand-shared string literals."""
    cfg = _CONFIG_C.read_text()
    assert constants.BTN_ACTION_EXEC == "exec"
    for token in ('"exec"', '"type"', '"cmd"', '"key:"'):
        assert token in cfg, f"daemon config.c no longer contains wire token {token}"
