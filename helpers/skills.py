"""Hierarchical upward-flowing skills for A0 Superordinates.

Each superordinate context may define one Markdown skills file:

    /a0/usr/chats/<context_id>/superordinate/skills.md

Skills flow upward through the superordinate hierarchy: a focused agent sees its
own skills plus the skills of every descendant/subordinate, with attribution to
the agent that owns each skill description. This lets parents understand what
their superordinates can do for delegation purposes.
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

SKILLS_FILENAME = "skills.md"
MAX_SKILLS_BYTES_PER_NODE = 64 * 1024
MAX_SKILLS_NODES = 512


@dataclass(frozen=True)
class SkillsEntry:
    """One resolved skills.md contribution."""

    context_id: str
    name: str
    path: str
    text: str
    depth: int


def skills_dir(ctxid: str) -> str:
    return os.path.join(CHATS_DIR, ctxid, SUPERORDINATE_DIRNAME)


def skills_path(ctxid: str) -> str:
    return os.path.join(skills_dir(ctxid), SKILLS_FILENAME)


def ensure_skills_file(ctxid: str) -> str:
    """Create the superordinate skills file if missing and return its path."""
    path = skills_path(ctxid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "# Superordinate Skills\n\n"
                "Describe this agent's skills, strengths, tools, domains, and delegation suitability. "
                "These descriptions flow upward to parents with attribution.\n"
            )
    return path


def read_skills_file(ctxid: str) -> str:
    """Read one context's skills.md, with size and encoding safeguards."""
    path = skills_path(ctxid)
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        if size <= 0:
            return ""
        with open(path, "rb") as f:
            raw = f.read(MAX_SKILLS_BYTES_PER_NODE + 1)
        if len(raw) > MAX_SKILLS_BYTES_PER_NODE:
            raw = raw[:MAX_SKILLS_BYTES_PER_NODE]
            raw += b"\n\n[Truncated: skills.md exceeded per-node size limit.]\n"
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

    while queue and len(ordered) < MAX_SKILLS_NODES:
        current, depth = queue.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        ordered.append((current, depth))
        for child in children_by_parent.get(current, []):
            if child not in seen:
                queue.append((child, depth + 1))

    return ordered


def resolve_skills_entries(ctxid: str) -> list[SkillsEntry]:
    """Return non-empty skills.md entries from current -> descendants."""
    entries: list[SkillsEntry] = []
    for node_id, depth in resolve_descendant_chain(ctxid):
        text = read_skills_file(node_id)
        if not text:
            continue
        entries.append(
            SkillsEntry(
                context_id=node_id,
                name=get_context_name(node_id),
                path=skills_path(node_id),
                text=text,
                depth=depth,
            )
        )
    return entries


def build_skills_prompt(ctxid: str) -> str:
    """Build the prompt block injected for upward-flowing skills."""
    entries = resolve_skills_entries(ctxid)
    if not entries:
        return ""

    parts = [
        "## Superordinate Upward-Flowing Skills",
        "The following Markdown skill descriptions belong to this agent and its descendants/subordinates.",
        "Use these attributed skill descriptions to decide whether and how to delegate work. They are descriptive delegation context, not permission grants.",
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
