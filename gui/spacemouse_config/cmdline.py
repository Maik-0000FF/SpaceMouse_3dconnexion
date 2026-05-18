"""Qt-free helpers for parsing and formatting exec-action command lines.

The exec dialog edits a user-typed command line and the XDG picker
reads ``Exec=`` strings from ``.desktop`` files; both go through these
helpers before the result reaches the daemon's argv slot. Splitting
them out of exec_dialog.py keeps the pytest job runnable without a
PySide6 install — the CI environment intentionally omits Qt.
"""

import shlex

# XDG field codes per the Desktop Entry Spec — the daemon launches
# without any file/url context, so they would arrive as literal
# "%f" / "%u" arguments and confuse the target program. Strip them.
_XDG_FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%i", "%c", "%k", "%v", "%m"}


def parse_cmdline(text):
    """shlex-split a user-typed command line into argv.

    Returns the argv list, or an empty list on parse failure. The
    return is what the daemon will receive in JSON as ``cmd``.
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return []


def parse_xdg_exec(exec_value):
    """Convert an XDG ``Exec=`` value into argv, stripping field codes.

    XDG quoting is shlex-compatible in 99% of real-world entries.
    Field codes (``%f``, ``%U`` etc.) are dropped because there's no
    file/URL context when a button triggers an app launch.
    """
    try:
        tokens = shlex.split(exec_value or "")
    except ValueError:
        return []
    return [t for t in tokens if t not in _XDG_FIELD_CODES]


def format_cmdline(argv):
    """Quote argv back into a single-line command string for display."""
    return " ".join(shlex.quote(a) for a in argv) if argv else ""
