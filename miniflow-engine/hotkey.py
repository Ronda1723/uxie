"""
Hotkey config — TWO triggers:

  "dictation"  → grammar-correct the transcript and type it into the focused app
  "command"    → run the transcript through the full agent loop (tools, connectors)

Stored at ~/miniflow/hotkey.json. Read by:
 - The native helper binary (miniflow-fn-helper) on startup and on SIGHUP
 - The Electron main process

New schema (v2):
    {
      "dictation": { "mode": "hold_to_talk", "modifier": "fn",     "key": null },
      "command":   { "mode": "hold_to_talk", "modifier": "option", "key": "space" }
    }

Legacy schema (v1) is auto-migrated: if the root has "mode" / "modifier" / "key"
those fields are moved under "dictation" and a sensible "command" default is added.
"""

from __future__ import annotations

import copy
import json
import logging
import stat
from pathlib import Path
from typing import Any

log = logging.getLogger("hotkey")

HOTKEY_FILE = Path.home() / "miniflow" / "hotkey.json"

VALID_MODES = {"hold_to_talk", "press_to_toggle"}
VALID_MODIFIERS = {"fn", "cmd", "option", "control", "shift", "globe", None}
VALID_KEYS = {
    None,
    "space", "return", "tab", "escape", "delete",
    "up", "down", "left", "right",
    *(chr(c) for c in range(ord("a"), ord("z") + 1)),
    *(str(n) for n in range(10)),
    *(f"f{n}" for n in range(1, 13)),
}

DEFAULT_DICTATION = {"mode": "hold_to_talk",    "modifier": "fn",     "key": None}
# Command mode defaults to press-to-toggle: tap once to start, tap again to stop
# speaking. This lets the user's hand return to the keyboard while the LLM thinks.
DEFAULT_COMMAND   = {"mode": "press_to_toggle", "modifier": "option", "key": "space"}

DEFAULT_HOTKEY: dict[str, Any] = {
    "dictation": dict(DEFAULT_DICTATION),
    "command":   dict(DEFAULT_COMMAND),
}


# ── File IO ───────────────────────────────────────────────────────────────────

def _write(data: dict):
    HOTKEY_FILE.parent.mkdir(exist_ok=True)
    HOTKEY_FILE.write_text(json.dumps(data, indent=2))
    HOTKEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _read_raw() -> dict:
    try:
        if HOTKEY_FILE.exists():
            return json.loads(HOTKEY_FILE.read_text())
    except Exception as e:
        log.warning(f"hotkey.json unreadable, using defaults: {e}")
    return {}


def _migrate(raw: dict) -> dict:
    """Accept old-flat-schema or new-nested-schema and return new-nested."""
    if "dictation" in raw or "command" in raw:
        out = copy.deepcopy(DEFAULT_HOTKEY)
        if isinstance(raw.get("dictation"), dict):
            out["dictation"] = {**DEFAULT_DICTATION, **raw["dictation"]}
        if "command" in raw:
            if raw["command"] is None:
                out["command"] = None
            elif isinstance(raw["command"], dict):
                out["command"] = {**DEFAULT_COMMAND, **raw["command"]}
        return out
    # Legacy flat schema — migrate top-level fields into "dictation"
    legacy = {k: raw[k] for k in ("mode", "modifier", "key") if k in raw}
    return {
        "dictation": {**DEFAULT_DICTATION, **legacy},
        "command":   dict(DEFAULT_COMMAND),
    }


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_single(hk: dict, label: str) -> dict:
    mode = hk.get("mode", "hold_to_talk")
    modifier = hk.get("modifier")
    key = hk.get("key")
    if mode not in VALID_MODES:
        raise ValueError(f"[{label}] invalid mode: {mode!r}")
    if modifier not in VALID_MODIFIERS:
        raise ValueError(f"[{label}] invalid modifier: {modifier!r}")
    if key not in VALID_KEYS:
        raise ValueError(f"[{label}] invalid key: {key!r}")
    if modifier is None and key is None:
        raise ValueError(f"[{label}] at least one of modifier/key must be set")
    if key is None and mode == "press_to_toggle":
        raise ValueError(f"[{label}] press_to_toggle requires a non-modifier key")
    return {"mode": mode, "modifier": modifier, "key": key}


def validate(hk: dict) -> dict:
    """Validate the full two-hotkey config, returning a normalized copy."""
    out: dict = {}
    if "dictation" in hk:
        out["dictation"] = _validate_single(hk["dictation"], "dictation")
    else:
        out["dictation"] = dict(DEFAULT_DICTATION)
    if "command" in hk:
        if hk["command"] is None:
            out["command"] = None
        else:
            out["command"] = _validate_single(hk["command"], "command")
    else:
        out["command"] = dict(DEFAULT_COMMAND)
    # Don't allow the two hotkeys to collide
    d, c = out["dictation"], out["command"]
    if c and d["modifier"] == c["modifier"] and d["key"] == c["key"]:
        raise ValueError("Dictation and command hotkeys must differ")
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def get_hotkey() -> dict:
    return _migrate(_read_raw()) or copy.deepcopy(DEFAULT_HOTKEY)


def set_hotkey(hk: dict) -> dict:
    normalized = validate(_migrate(hk))
    _write(normalized)
    log.info(f"Hotkey updated: {normalized}")
    _signal_helper()
    return normalized


def reset_hotkey() -> dict:
    default = copy.deepcopy(DEFAULT_HOTKEY)
    _write(default)
    log.info("Hotkey reset to defaults")
    _signal_helper()
    return default


def _signal_helper():
    """SIGHUP the native helper so it reloads hotkey.json without a restart."""
    import os, signal
    pidfile = Path.home() / "miniflow" / "miniflow-fn-helper.pid"
    if not pidfile.exists():
        return
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, signal.SIGHUP)
        log.info(f"Sent SIGHUP to native helper pid={pid}")
    except Exception as e:
        log.warning(f"Could not SIGHUP helper: {e}")
