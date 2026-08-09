"""Plugin state store — reads/writes ~/.code/plugins/installed_plugins.json.

This is the single source of truth for registered marketplaces and installed
plugins. Writes are atomic (temp file + rename) so a crash mid-save never
corrupts the state file.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

_PLUGINS_DIR = Path.home() / ".code" / "plugins"
STATE_FILE = _PLUGINS_DIR / "installed_plugins.json"


def _fresh_empty_state() -> dict[str, Any]:
    """A brand-new empty state. Never returns the shared constant, so callers
    that mutate nested dicts (e.g. ``update_state`` mutators) can never
    corrupt module-level state."""
    return {"marketplaces": {}, "installed": {}}


def state_path() -> Path:
    """Path to the installed_plugins.json state file (creates the dir if needed)."""
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_FILE


def marketplaces_dir() -> Path:
    """Directory holding the full local clones of registered marketplaces.

    ``plugin marketplace add`` clones the marketplace repo here, keyed by its
    alias, so installs can scan the local clone (Claude Code convention).
    """
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLUGINS_DIR / "marketplaces"


def installed_plugins_dir() -> Path:
    """Directory each installed plugin is copied into, namespaced by marketplace.

    Layout: ``installed/<marketplace>/<plugin>/`` containing its own
    ``agents/``, ``skills/``, and ``commands/`` subfolders. Keeping plugins out
    of the raw global agents/skills dirs and namespacing them by marketplace
    prevents naming collisions between plugins.
    """
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLUGINS_DIR / "installed"


def load_state() -> dict[str, Any]:
    """Return the full state dict (marketplaces + installed). Never corrupts on read."""
    path = state_path()
    if not path.exists():
        return _fresh_empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _fresh_empty_state()
        data.setdefault("marketplaces", {})
        data.setdefault("installed", {})
        return data
    except (json.JSONDecodeError, OSError):
        # Reset empty state rather than crash — the CLI path never depends on
        # a pre-existing good file (it recreates on demand).
        return _fresh_empty_state()


def clear_state() -> None:
    """Delete the state file. Used by tests and 'plugin uninstall --all'."""
    path = state_path()
    if path.exists():
        path.unlink()


def save_state(state: dict[str, Any]) -> None:
    """Atomically persist the full state dict to disk."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        Path(tmp).replace(path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def update_state(mutator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Load, apply ``mutator(state)``, and atomically save the result."""
    state = load_state()
    state = mutator(state)
    save_state(state)
    return state