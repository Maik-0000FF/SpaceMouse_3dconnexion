"""Tests for the cmdline-parsing helpers in exec_dialog.

The dialog itself needs a running Qt event loop and is exercised by
hand; the small pure functions are the part where the bugs hide.
"""

from spacemouse_config import exec_dialog


def test_parse_cmdline_splits_simple_args():
    assert exec_dialog.parse_cmdline("firefox --new-window https://x.com") == [
        "firefox",
        "--new-window",
        "https://x.com",
    ]


def test_parse_cmdline_honours_quotes_for_spaces():
    # shlex pairs the quotes so the arg with the space stays a single token.
    assert exec_dialog.parse_cmdline("notify-send 'Hello world' 'Body text'") == [
        "notify-send",
        "Hello world",
        "Body text",
    ]


def test_parse_cmdline_empty_returns_empty_list():
    assert exec_dialog.parse_cmdline("") == []
    assert exec_dialog.parse_cmdline("   ") == []
    assert exec_dialog.parse_cmdline(None) == []


def test_parse_cmdline_unbalanced_quotes_returns_empty():
    # shlex raises ValueError on unbalanced quoting — the dialog
    # surfaces that as "(empty command)" rather than crashing.
    assert exec_dialog.parse_cmdline('firefox "unterminated') == []


def test_parse_xdg_exec_strips_field_codes():
    # %u, %f etc. carry no meaning when the daemon launches an app
    # without a file context — they must not arrive as literal args.
    assert exec_dialog.parse_xdg_exec("firefox %u") == ["firefox"]
    assert exec_dialog.parse_xdg_exec("vlc --some-flag %F") == ["vlc", "--some-flag"]
    assert exec_dialog.parse_xdg_exec("xdg-open %f %u %i") == ["xdg-open"]


def test_parse_xdg_exec_empty_or_missing():
    assert exec_dialog.parse_xdg_exec("") == []
    assert exec_dialog.parse_xdg_exec(None) == []


def test_format_cmdline_quotes_spaces():
    # Round-trip property: format_cmdline → parse_cmdline must yield
    # the original argv, regardless of which args contain spaces.
    cases = [
        ["firefox"],
        ["firefox", "--new-window", "https://x.com"],
        ["notify-send", "Hello world", "Body text with 'quotes'"],
        ["sh", "-c", "echo $HOME && ls /tmp"],
    ]
    for argv in cases:
        round_trip = exec_dialog.parse_cmdline(exec_dialog.format_cmdline(argv))
        assert round_trip == argv, f"round-trip failed for {argv!r}: got {round_trip!r}"


def test_format_cmdline_empty_argv():
    assert exec_dialog.format_cmdline([]) == ""
    assert exec_dialog.format_cmdline(None) == ""
