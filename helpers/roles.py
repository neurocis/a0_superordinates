"""Hierarchical upward-flowing roles for A0 Superordinates.

Each superordinate context may define one Markdown roles file:

    /a0/usr/chats/<context_id>/superordinate/roles.md

Roles flow upward through the superordinate hierarchy: a focused agent sees its
own roles plus the roles of every descendant/subordinate, with attribution to
the agent that owns each description. This lets parents understand what their
superordinates can do for delegation purposes.

For compatibility with the short-lived previous feature names, existing
``occupations.md`` and ``skills.md`` files are read as fallbacks when
``roles.md`` is absent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from usr.plugins.a0_superordinates.helpers.inheritance import (
    CHATS_DIR,
    SUPERORDINATE_DIRNAME,
    get_context_data,
    get_context_name,
)

ROLES_FILENAME = "roles.md"
LEGACY_OCCUPATIONS_FILENAME = "occupations.md"
LEGACY_SKILLS_FILENAME = "skills.md"
MAX_ROLES_BYTES_PER_NODE = 64 * 1024
MAX_ROLES_NODES = 512


@dataclass(frozen=True)
class RolesEntry:
    """One resolved roles.md contribution."""

    context_id: str
    name: str
    path: str
    text: str
    depth: int


def roles_dir(ctxid: str) -> str:
    return os.path.join(CHATS_DIR, ctxid, SUPERORDINATE_DIRNAME)


def roles_path(ctxid: str) -> str:
    return os.path.join(roles_dir(ctxid), ROLES_FILENAME)


def legacy_occupations_path(ctxid: str) -> str:
    return os.path.join(roles_dir(ctxid), LEGACY_OCCUPATIONS_FILENAME)


def legacy_skills_path(ctxid: str) -> str:
    return os.path.join(roles_dir(ctxid), LEGACY_SKILLS_FILENAME)


def readable_roles_path(ctxid: str) -> str:
    """Return roles.md, or a legacy file when it is the only file present."""
    path = roles_path(ctxid)
    if os.path.isfile(path):
        return path
    occupations_path = legacy_occupations_path(ctxid)
    if os.path.isfile(occupations_path):
        return occupations_path
    skills_path = legacy_skills_path(ctxid)
    if os.path.isfile(skills_path):
        return skills_path
    return path


def ensure_roles_file(ctxid: str) -> str:
    """Create the superordinate roles file if missing and return its path."""
    path = roles_path(ctxid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        legacy_path = readable_roles_path(ctxid)
        if legacy_path != path and os.path.isfile(legacy_path):
            return legacy_path
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "# Superordinate Roles\n\n"
                "Describe this agent's roles, responsibilities, domains, capabilities, "
                "and delegation suitability. These descriptions flow upward to parents.\n"
            )
    return path


def read_roles_file(ctxid: str) -> str:
    """Read one context's roles.md, with legacy fallback and safeguards."""
    path = readable_roles_path(ctxid)
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        if size <= 0:
            return ""
        with open(path, "rb") as f:
            raw = f.read(MAX_ROLES_BYTES_PER_NODE + 1)
        if len(raw) > MAX_ROLES_BYTES_PER_NODE:
            raw = raw[:MAX_ROLES_BYTES_PER_NODE]
            raw += b"\n\n[Truncated: roles.md exceeded per-node size limit.]\n"
        return raw.decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _chat_exists(ctxid: str) -> bool:
    if not ctxid:
        return False
    try:
        from agent import AgentContext

        if AgentContext.get(ctxid) is not None:
            return True
    except Exception:
        pass
    return os.path.isfile(os.path.join(CHATS_DIR, ctxid, "chat.json"))


def _all_context_ids() -> list[str]:
    ids: set[str] = set()
    try:
        from agent import AgentContext

        for ctx in getattr(AgentContext, "_contexts", {}).values():
            ctxid = getattr(ctx, "id", "")
            if ctxid:
                ids.add(ctxid)
    except Exception:
        pass

    try:
        for name in os.listdir(CHATS_DIR):
            if os.path.isfile(os.path.join(CHATS_DIR, name, "chat.json")):
                ids.add(name)
    except OSError:
        pass

    return sorted(ids)


def resolve_descendant_chain(ctxid: str) -> list[tuple[str, int]]:
    """Return focused context plus descendants as (ctxid, depth), breadth-first.

    Descendant membership is derived from each context's authoritative
    ``sup_parent`` value rather than trusting potentially stale parent caches.
    """
    if not ctxid or not _chat_exists(ctxid):
        return []

    children_by_parent: dict[str, list[str]] = {}
    for candidate in _all_context_ids():
        parent = get_context_data(candidate).get("sup_parent")
        if isinstance(parent, str) and parent.strip():
            children_by_parent.setdefault(parent.strip(), []).append(candidate)

    ordered: list[tuple[str, int]] = []
    queue: list[tuple[str, int]] = [(ctxid, 0)]
    seen: set[str] = set()

    while queue and len(ordered) < MAX_ROLES_NODES:
        current, depth = queue.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        ordered.append((current, depth))
        for child in children_by_parent.get(current, []):
            if child not in seen:
                queue.append((child, depth + 1))

    return ordered


def resolve_roles_entries(ctxid: str) -> list[RolesEntry]:
    """Return non-empty roles entries from current -> descendants."""
    entries: list[RolesEntry] = []
    for node_id, depth in resolve_descendant_chain(ctxid):
        text = read_roles_file(node_id)
        if not text:
            continue
        entries.append(
            RolesEntry(
                context_id=node_id,
                name=get_context_name(node_id),
                path=readable_roles_path(node_id),
                text=text,
                depth=depth,
            )
        )
    return entries


def build_roles_prompt(ctxid: str) -> str:
    """Build the prompt block injected for upward-flowing roles."""
    entries = resolve_roles_entries(ctxid)
    if not entries:
        return ""

    parts = [
        "## Superordinate Upward-Flowing Roles",
        "The following Markdown role descriptions belong to this agent and its descendants/subordinates.",
        "Use these attributed role descriptions to decide whether and how to delegate work. They are descriptive delegation context, not permission grants.",
    ]

    for idx, entry in enumerate(entries, start=1):
        parts.append(
            "\n".join(
                [
                    f"### {idx}. {entry.name}",
                    f"Context ID: `{entry.context_id}`",
                    f"Hierarchy Depth Below Focus: {entry.depth}",
                    "",
                    entry.text,
                ]
            )
        )

    return "\n\n".join(parts).strip()
