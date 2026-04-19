"""Snippets — trigger → expansion mappings."""

import json
from pathlib import Path

SNIPPETS_FILE = Path.home() / "miniflow" / "snippets.json"


def _read() -> dict:
    try:
        if SNIPPETS_FILE.exists():
            return json.loads(SNIPPETS_FILE.read_text())
    except Exception:
        pass
    return {}


def _write(data: dict):
    SNIPPETS_FILE.parent.mkdir(exist_ok=True)
    SNIPPETS_FILE.write_text(json.dumps(data, indent=2))


def get_snippets() -> dict:
    return _read()


def add_snippet(trigger: str, expansion: str):
    s = _read()
    s[trigger] = expansion
    _write(s)


def remove_snippet(trigger: str):
    s = _read()
    s.pop(trigger, None)
    _write(s)


def apply(text: str) -> str:
    """Expand snippet triggers inside `text`, respecting word boundaries so
    we don't replace 'sig' inside 'signal' when the trigger is 'sig'."""
    import re
    s = _read()
    if not s:
        return text
    # Longest trigger first so overlapping keys don't stomp on each other.
    for trigger in sorted(s.keys(), key=len, reverse=True):
        expansion = s[trigger]
        pattern = r"\b" + re.escape(trigger) + r"\b"
        text = re.sub(pattern, lambda _: expansion, text, flags=re.IGNORECASE)
    return text
