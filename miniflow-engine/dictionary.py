"""Dictionary — word replacement mappings."""

import json
from pathlib import Path

DICT_FILE = Path.home() / "miniflow" / "dictionary.json"


def _read() -> dict:
    try:
        if DICT_FILE.exists():
            return json.loads(DICT_FILE.read_text())
    except Exception:
        pass
    return {}


def _write(data: dict):
    DICT_FILE.parent.mkdir(exist_ok=True)
    DICT_FILE.write_text(json.dumps(data, indent=2))


def get_dictionary() -> dict:
    return _read()


def add_word(from_word: str, to_word: str):
    d = _read()
    d[from_word] = to_word
    _write(d)


def remove_word(from_word: str):
    d = _read()
    d.pop(from_word, None)
    _write(d)


def import_dictionary(entries: dict):
    d = _read()
    d.update(entries)
    _write(d)


def apply(text: str) -> str:
    """Replace every dictionary key with its value, case-insensitive, on word
    boundaries so 'ny' doesn't rewrite letters inside 'any' / 'many'."""
    import re
    d = _read()
    if not d:
        return text
    for frm in sorted(d.keys(), key=len, reverse=True):
        to = d[frm]
        pattern = r"\b" + re.escape(frm) + r"\b"
        text = re.sub(pattern, lambda _: to, text, flags=re.IGNORECASE)
    return text
