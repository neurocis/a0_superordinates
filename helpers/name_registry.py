"""Persistent name registry for SuperOrdinates.

Maps SuperOrdinate names to context IDs for name-based referencing.
Registry file: /a0/usr/plugins/a0_superordinates/name_registry.json
"""

import json
import os
from typing import Optional

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "name_registry.json")


def _load_registry() -> dict:
    """Load the name registry from disk."""
    if not os.path.isfile(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry: dict) -> None:
    """Save the name registry to disk."""
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def register_name(name: str, ctxid: str) -> bool:
    """Register a name→ctxid mapping. Returns False if name already taken."""
    registry = _load_registry()
    # Check if name already registered to a DIFFERENT context
    if name in registry and registry[name] != ctxid:
        return False
    registry[name] = ctxid
    _save_registry(registry)
    return True


def unregister_name(name: str) -> None:
    """Remove a name from the registry."""
    registry = _load_registry()
    registry.pop(name, None)
    _save_registry(registry)


def lookup_by_name(name: str) -> Optional[str]:
    """Get ctxid for a given name, or None."""
    registry = _load_registry()
    return registry.get(name)


def lookup_by_ctxid(ctxid: str) -> Optional[str]:
    """Get name for a given ctxid, or None."""
    registry = _load_registry()
    for name, cid in registry.items():
        if cid == ctxid:
            return name
    return None


def name_exists(name: str) -> bool:
    """Check if a name is already registered."""
    return name in _load_registry()


def get_all_names() -> dict:
    """Return the full name→ctxid mapping."""
    return _load_registry()


def cleanup_dead() -> list:
    """Remove entries whose context no longer exists on disk."""
    from agent import AgentContext
    registry = _load_registry()
    removed = []
    for name, ctxid in list(registry.items()):
        # Check if context still exists (in memory or on disk)
        if AgentContext.get(ctxid) is None:
            chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
            if not os.path.isfile(chat_file):
                del registry[name]
                removed.append(name)
    if removed:
        _save_registry(registry)
    return removed
