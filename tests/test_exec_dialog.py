"""Tests for the cmdline parse/format helpers.

The Qt dialog that uses these is exercised by hand; the small pure
functions are the part where the bugs hide and they live in the
Qt-free cmdline module so the pytest job runs without PySide6.
"""

import pytest
from spacemouse_config import cmdline


def test_parse_cmdline_splits_simple_args():
    assert cmdline.parse_cmdline("firefox --new-window https://x.com") == [
        "firefox",
        "--new-window",
        "https://x.com",
    ]


def test_parse_cmdline_honours_quotes_for_spaces():
    # shlex pairs the quotes so the arg with the space stays a single token.
    assert cmdline.parse_cmdline("notify-send 'Hello world' 'Body text'") == [
        "notify-send",
        "Hello world",
        "Body text",
    ]


def test_parse_cmdline_empty_returns_empty_list():
    assert cmdline.parse_cmdline("") == []
    assert cmdline.parse_cmdline("   ") == []
    assert cmdline.parse_cmdline(None) == []


def test_parse_cmdline_unbalanced_quotes_returns_empty():
    # shlex raises ValueError on unbalanced quoting — the dialog
    # surfaces that as "(empty command)" rather than crashing.
    assert cmdline.parse_cmdline('firefox "unterminated') == []


def test_split_cmdline_raises_on_unbalanced_quotes():
    # split_cmdline is the raising variant the exec dialog uses to tell
    # "empty" apart from "malformed" so it can keep OK disabled and show
    # a distinct error instead of silently swallowing the mistake.
    with pytest.raises(ValueError):
        cmdline.split_cmdline('firefox "unterminated')


def test_split_cmdline_returns_argv_on_valid_input():
    assert cmdline.split_cmdline("firefox --new-window") == ["firefox", "--new-window"]


def test_parse_xdg_exec_strips_field_codes():
    # %u, %f etc. carry no meaning when the daemon launches an app
    # without a file context — they must not arrive as literal args.
    assert cmdline.parse_xdg_exec("firefox %u") == ["firefox"]
    assert cmdline.parse_xdg_exec("vlc --some-flag %F") == ["vlc", "--some-flag"]
    assert cmdline.parse_xdg_exec("xdg-open %f %u %i") == ["xdg-open"]


def test_parse_xdg_exec_empty_or_missing():
    assert cmdline.parse_xdg_exec("") == []
    assert cmdline.parse_xdg_exec(None) == []


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
        round_trip = cmdline.parse_cmdline(cmdline.format_cmdline(argv))
        assert round_trip == argv, f"round-trip failed for {argv!r}: got {round_trip!r}"


def test_format_cmdline_empty_argv():
    assert cmdline.format_cmdline([]) == ""
    assert cmdline.format_cmdline(None) == ""
