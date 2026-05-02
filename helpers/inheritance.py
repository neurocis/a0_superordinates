"""Hierarchical single-file inheritance for A0 Superordinates.

Each superordinate context may define exactly one inheritable Markdown file:

    /a0/usr/chats/<context_id>/superordinate/inheritance.md

The effective inheritance block for a context is resolved by walking the
``sup_parent`` chain, ordering entries root -> current context, and including
only non-empty ``inheritance.md`` files.  This intentionally uses one category
of inherited content instead of separate instruction/knowledge/memory buckets.

Important: inheritance is read-only prompt context.  It does not grant message,
visibility, mutation, sibling, parent, or task permissions.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

CHATS_DIR = "/a0/usr/chats"
SUPERORDINATE_DIRNAME = "superordinate"
INHERITANCE_FILENAME = "inheritance.md"
MAX_INHERITANCE_BYTES_PER_NODE = 64 * 1024
MAX_INHERITANCE_NODES = 64


@dataclass(frozen=True)
class InheritanceEntry:
    """One resolved inheritance.md contribution."""

    context_id: str
    name: str
    path: str
    text: str


def inheritance_dir(ctxid: str) -> str:
    return os.path.join(CHATS_DIR, ctxid, SUPERORDINATE_DIRNAME)


def inheritance_path(ctxid: str) -> str:
    return os.path.join(inheritance_dir(ctxid), INHERITANCE_FILENAME)


def ensure_inheritance_file(ctxid: str) -> str:
    """Create the superordinate inheritance file if missing and return its path."""
    path = inheritance_path(ctxid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "# Superordinate Inheritance\n\n"
                "Add Markdown here to make this agent's inheritable context available "
                "to itself and descendants. This file is resolved root-to-current.\n"
            )
    return path


def read_inheritance_file(ctxid: str) -> str:
    """Read one context's inheritance.md, with size and encoding safeguards."""
    path = inheritance_path(ctxid)
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        if size <= 0:
            return ""
        with open(path, "rb") as f:
            raw = f.read(MAX_INHERITANCE_BYTES_PER_NODE + 1)
        if len(raw) > MAX_INHERITANCE_BYTES_PER_NODE:
            raw = raw[:MAX_INHERITANCE_BYTES_PER_NODE]
            suffix = b"\n\n[Truncated: inheritance.md exceeded per-node size limit.]\n"
            raw += suffix
        return raw.decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _context_from_memory(ctxid: str) -> Any | None:
    try:
        from agent import AgentContext

        return AgentContext.get(ctxid)
    except Exception:
        return None


def _load_disk_chat(ctxid: str) -> dict[str, Any]:
    chat_file = os.path.join(CHATS_DIR, ctxid, "chat.json")
    try:
        with open(chat_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_context_data(ctxid: str) -> dict[str, Any]:
    """Return freshest available context.data for ctxid."""
    ctx = _context_from_memory(ctxid)
    data = getattr(ctx, "data", None) if ctx is not None else None
    if isinstance(data, dict):
        return data

    raw = _load_disk_chat(ctxid)
    data = raw.get("data")
    return data if isinstance(data, dict) else {}


def get_context_name(ctxid: str) -> str:
    """Return a readable context name for labels."""
    ctx = _context_from_memory(ctxid)
    name = getattr(ctx, "name", "") if ctx is not None else ""
    if isinstance(name, str) and name.strip():
        return name.strip()

    raw = _load_disk_chat(ctxid)
    for key in ("name", "title"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    for key in ("sup_name", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ctxid


def resolve_context_chain(ctxid: str) -> list[str]:
    """Resolve parent chain root -> current using sup_parent metadata.

    The function is defensive against missing parents and existing data cycles.
    If a cycle is encountered, traversal stops at the repeated node boundary.
    """
    if not ctxid:
        return []

    chain: list[str] = []
    seen: set[str] = set()
    current = ctxid

    for _ in range(MAX_INHERITANCE_NODES):
        if not current or current in seen:
            break
        seen.add(current)
        chain.append(current)
        parent = get_context_data(current).get("sup_parent")
        current = parent.strip() if isinstance(parent, str) else ""

    chain.reverse()
    return chain


def resolve_inheritance_entries(ctxid: str) -> list[InheritanceEntry]:
    """Return non-empty inheritance.md entries from root -> current."""
    entries: list[InheritanceEntry] = []
    for node_id in resolve_context_chain(ctxid):
        text = read_inheritance_file(node_id)
        if not text:
            continue
        entries.append(
            InheritanceEntry(
                context_id=node_id,
                name=get_context_name(node_id),
                path=inheritance_path(node_id),
                text=text,
            )
        )
    return entries


def build_inheritance_prompt(ctxid: str) -> str:
    """Build the prompt block injected for hierarchical inheritance."""
    entries = resolve_inheritance_entries(ctxid)
    if not entries:
        return ""

    parts = [
        "## Superordinate Hierarchical Inheritance",
        "The following inherited Markdown blocks are resolved from the Superordinate tree in root-to-current order.",
        "This inherited context is read-only guidance. It does not grant messaging, visibility, mutation, sibling, parent, task, filesystem, or tool permissions beyond the permissions already available in this context.",
    ]

    for idx, entry in enumerate(entries, start=1):
        parts.append(
            "\n".join(
                [
                    f"### {idx}. {entry.name}",
                    f"Context ID: `{entry.context_id}`",
                    f"Source: `{entry.path}`",
                    "",
                    entry.text,
                ]
            )
        )

    return "\n\n".join(parts).strip()
