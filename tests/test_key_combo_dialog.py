"""Tests for the pure parse/format helpers in key_combo_dialog.

The dialog itself needs a Qt event loop and is exercised by hand; the
parser is what the daemon wire format ultimately depends on, so this
is where round-trip and edge-case coverage matters.
"""

from spacemouse_config import key_combo_dialog


def test_parse_typical_combo():
    assert key_combo_dialog.parse_combo_string("Ctrl+Shift+S") == (["Ctrl", "Shift"], "S")


def test_parse_plain_key_no_modifier():
    # Mirrors "key:F" in the daemon wire format — zero modifiers is valid.
    assert key_combo_dialog.parse_combo_string("F") == ([], "F")


def test_parse_is_case_insensitive_and_canonicalises_key():
    # Daemon parser uses strcasecmp; the dialog mirrors that so a
    # hand-edited "key:ctrl+shift+s" round-trips through the GUI.
    # The end key is normalised to the display form from COMBO_KEY_NAMES
    # so the config file always ends up with consistent capitalisation.
    assert key_combo_dialog.parse_combo_string("ctrl+shift+s") == (["Ctrl", "Shift"], "S")
    assert key_combo_dialog.parse_combo_string("CONTROL+ALT+F1") == (["Ctrl", "Alt"], "F1")
    assert key_combo_dialog.parse_combo_string("ctrl+TAB") == (["Ctrl"], "Tab")
    assert key_combo_dialog.parse_combo_string("Meta+pageup") == (["Meta"], "PageUp")


def test_parse_modifier_aliases():
    # Super / Win / Cmd all collapse onto canonical Meta — same as
    # the daemon's modifier lookup table.
    for alias in ("Super", "Win", "Cmd", "Meta"):
        mods, key = key_combo_dialog.parse_combo_string(f"{alias}+L")
        assert mods == ["Meta"], f"alias {alias!r} did not map to Meta"
        assert key == "L"


def test_parse_rejects_unknown_modifier():
    # An unknown modifier word must not just drop silently — the user
    # would otherwise get an unexpectedly bound key. Empty result
    # signals "re-bind required".
    assert key_combo_dialog.parse_combo_string("WTF+S") == ([], "")


def test_parse_rejects_unknown_key():
    # Last token has to be in COMBO_KEY_NAMES; "Banana" isn't.
    assert key_combo_dialog.parse_combo_string("Ctrl+Banana") == ([], "")


def test_parse_rejects_duplicate_modifier():
    # Daemon parser rejects "Ctrl+Ctrl+S" as a typo; mirror that.
    assert key_combo_dialog.parse_combo_string("Ctrl+Ctrl+S") == ([], "")


def test_parse_empty_and_whitespace():
    assert key_combo_dialog.parse_combo_string("") == ([], "")
    assert key_combo_dialog.parse_combo_string("   ") == ([], "")
    assert key_combo_dialog.parse_combo_string(None) == ([], "")


def test_format_canonical_modifier_order():
    # No matter the input order, the format function emits
    # Ctrl → Shift → Alt → Meta so the saved config stays stable
    # diff-wise.
    assert key_combo_dialog.format_combo(["Shift", "Ctrl"], "S") == "Ctrl+Shift+S"
    assert key_combo_dialog.format_combo(["Meta", "Alt", "Ctrl"], "Tab") == "Ctrl+Alt+Meta+Tab"


def test_format_empty_key_returns_empty():
    # The dialog uses this to detect "user hasn't picked anything yet".
    assert key_combo_dialog.format_combo(["Ctrl"], "") == ""
    assert key_combo_dialog.format_combo([], "") == ""


def test_format_drops_unknown_modifiers():
    # Garbage modifier names get filtered out instead of corrupting
    # the daemon wire format.
    assert key_combo_dialog.format_combo(["Ctrl", "Bogus"], "S") == "Ctrl+S"


def test_round_trip_property():
    # parse → format must be the identity on any valid input we'd
    # ever emit ourselves.
    cases = [
        "S",
        "Ctrl+S",
        "Ctrl+Shift+S",
        "Ctrl+Shift+Alt+Meta+Tab",
        "Alt+F4",
        "Meta+L",
    ]
    for canonical in cases:
        mods, key = key_combo_dialog.parse_combo_string(canonical)
        assert key_combo_dialog.format_combo(mods, key) == canonical, (
            f"round-trip failed for {canonical!r}"
        )
