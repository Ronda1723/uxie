"""
Shared pytest fixtures.

Redirect ~/miniflow to a temp dir so tests never clobber real user data, and
stub out the keyring backend so nothing touches the real macOS Keychain.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Point every CONFIG_DIR / HOTKEY_FILE constant at a throwaway directory."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # The config/hotkey modules cache CONFIG_DIR at import time. Reload them
    # after patching HOME so their constants pick up the new path.
    # Ensure miniflow-engine is on sys.path
    ENGINE_DIR = Path(__file__).resolve().parent.parent
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))

    import config  # noqa: E402
    import hotkey  # noqa: E402
    importlib.reload(config)
    importlib.reload(hotkey)
    yield


class _MemoryKeyring:
    """In-memory keyring replacement so tests never touch the real Keychain."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    """Install the memory keyring in place of the real one."""
    kr = _MemoryKeyring()
    import config
    monkeypatch.setattr(config, "_keyring_module", lambda: kr)
    return kr
