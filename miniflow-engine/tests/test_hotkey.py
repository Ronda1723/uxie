"""Tests for hotkey.py — config schema + validator + SIGHUP."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


def test_default_hotkey_is_fn_hold():
    import hotkey
    assert hotkey.get_hotkey() == {
        "mode": "hold_to_talk",
        "modifier": "fn",
        "key": None,
    }


def test_set_hotkey_valid_modifier_plus_key():
    import hotkey
    result = hotkey.set_hotkey({"mode": "hold_to_talk", "modifier": "option", "key": "space"})
    assert result == {"mode": "hold_to_talk", "modifier": "option", "key": "space"}
    assert hotkey.get_hotkey() == result


def test_set_hotkey_persists_across_reads():
    import hotkey
    hotkey.set_hotkey({"mode": "press_to_toggle", "modifier": "cmd", "key": "d"})
    fresh = json.loads(hotkey.HOTKEY_FILE.read_text())
    assert fresh == {"mode": "press_to_toggle", "modifier": "cmd", "key": "d"}


@pytest.mark.parametrize("bad", [
    {"mode": "invalid", "modifier": "fn", "key": None},
    {"mode": "hold_to_talk", "modifier": "meta", "key": None},       # unknown modifier
    {"mode": "hold_to_talk", "modifier": "cmd", "key": "zz"},        # unknown key
    {"mode": "hold_to_talk", "modifier": None, "key": None},         # must have at least one
    {"mode": "press_to_toggle", "modifier": "fn", "key": None},      # ambiguous toggle
])
def test_set_hotkey_rejects_invalid(bad):
    import hotkey
    with pytest.raises(ValueError):
        hotkey.set_hotkey(bad)


def test_reset_hotkey_restores_default():
    import hotkey
    hotkey.set_hotkey({"mode": "hold_to_talk", "modifier": "shift", "key": "space"})
    reset = hotkey.reset_hotkey()
    assert reset == {"mode": "hold_to_talk", "modifier": "fn", "key": None}
    assert hotkey.get_hotkey() == reset


def test_corrupt_file_falls_back_to_defaults():
    import hotkey
    hotkey.HOTKEY_FILE.parent.mkdir(exist_ok=True)
    hotkey.HOTKEY_FILE.write_text("NOT JSON")
    assert hotkey.get_hotkey() == {
        "mode": "hold_to_talk", "modifier": "fn", "key": None,
    }


def test_missing_fields_backfilled_from_defaults():
    import hotkey
    hotkey.HOTKEY_FILE.parent.mkdir(exist_ok=True)
    hotkey.HOTKEY_FILE.write_text(json.dumps({"modifier": "control"}))
    hk = hotkey.get_hotkey()
    assert hk["modifier"] == "control"
    assert hk["mode"] == "hold_to_talk"
    assert hk["key"] is None


def test_sighup_sent_when_pidfile_exists(tmp_path):
    import hotkey
    pidfile = hotkey.HOTKEY_FILE.parent / "miniflow-fn-helper.pid"
    pidfile.parent.mkdir(exist_ok=True)
    pidfile.write_text("12345")
    with patch("os.kill") as mock_kill:
        hotkey.set_hotkey({"mode": "hold_to_talk", "modifier": "cmd", "key": "f1"})
        mock_kill.assert_called_once()
        pid, sig = mock_kill.call_args[0]
        assert pid == 12345
        import signal
        assert sig == signal.SIGHUP


def test_sighup_noop_when_pidfile_missing():
    import hotkey
    with patch("os.kill") as mock_kill:
        hotkey.set_hotkey({"mode": "hold_to_talk", "modifier": "control", "key": "f2"})
        mock_kill.assert_not_called()
