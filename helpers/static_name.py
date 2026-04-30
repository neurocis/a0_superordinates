"""Helpers for the hidden per-agent StaticName rename lock.

StaticName is stored in context.data for persistence/authoritative plugin state
and mirrored into context.output_data so the normal WebUI context snapshot exposes
it without requiring superordinate_map to reread chat.json metadata.
"""
from __future__ import annotations

from typing import Any

STATIC_NAME_DATA_KEY = "StaticName"
STATIC_NAME_ALT_DATA_KEY = "static_name"


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse boolean-ish values without making string 'false' truthy."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", ""}:
            return False
    return default


def _read_static_value(mapping: dict | None) -> Any:
    if not isinstance(mapping, dict):
        return None
    if STATIC_NAME_DATA_KEY in mapping:
        return mapping.get(STATIC_NAME_DATA_KEY)
    return mapping.get(STATIC_NAME_ALT_DATA_KEY)


def is_static_name_locked(context: Any) -> bool:
    """Return true when a context has StaticName enabled.

    Check output_data first because that is what the normal context snapshot
    exposes to the WebUI, then fall back to data for older persisted contexts.
    """
    output_data = getattr(context, "output_data", None)
    if parse_bool(_read_static_value(output_data), False):
        return True

    getter = getattr(context, "get_data", None)
    if callable(getter):
        value = getter(STATIC_NAME_DATA_KEY)
        if value is None:
            value = getter(STATIC_NAME_ALT_DATA_KEY)
        if parse_bool(value, False):
            return True

    data = getattr(context, "data", None)
    return parse_bool(_read_static_value(data), False)


def set_static_name(context: Any, value: Any) -> bool:
    """Set StaticName on both persistent data and normal output snapshot data."""
    locked = parse_bool(value, False)

    data = getattr(context, "data", None)
    if isinstance(data, dict):
        data[STATIC_NAME_DATA_KEY] = locked

    output_data = getattr(context, "output_data", None)
    if isinstance(output_data, dict):
        output_data[STATIC_NAME_DATA_KEY] = locked
        output_data[STATIC_NAME_ALT_DATA_KEY] = locked

    return locked



def sync_static_name_output(context: Any) -> bool:
    """Mirror any existing StaticName value into output_data for snapshots.

    This is intentionally memory-only and cheap. It lets already-loaded contexts
    that have data.StaticName from older plugin versions expose the flag through
    AgentContext.output() without requiring superordinate_map to reread disk.
    """
    data = getattr(context, "data", None)
    output_data = getattr(context, "output_data", None)

    has_static = False
    if isinstance(data, dict) and (
        STATIC_NAME_DATA_KEY in data or STATIC_NAME_ALT_DATA_KEY in data
    ):
        has_static = True
    if isinstance(output_data, dict) and (
        STATIC_NAME_DATA_KEY in output_data or STATIC_NAME_ALT_DATA_KEY in output_data
    ):
        has_static = True

    if not has_static:
        return False

    locked = parse_bool(_read_static_value(data), False) or parse_bool(
        _read_static_value(output_data), False
    )
    set_static_name(context, locked)
    return locked
