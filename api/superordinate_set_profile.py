"""Set the agent profile of an existing context.

Updates `data.sup_profile` for persistence AND the live agent's
`config.profile` so the change takes effect on the next message loop
(prompts/tools/extensions are resolved by profile via Agent.read_prompt and
subagents.get_paths each iteration).

Accepts:
    ctxid:   target context ID (required)
    profile: profile name (required) - e.g. 'agent0', 'developer', 'researcher'

Returns:
    {"ok": true, "profile": <name>, "display_name": <updated name or null>}

Notes:
- Validates the profile exists on disk before applying.
- If the chat name follows the "<Name> (<old_profile>)" pattern (set by
  superordinate_spawn), the suffix is updated to reflect the new profile.
- Persists via save_tmp_chat so the change survives restart.
"""

import os
import re
import logging

from helpers.api import ApiHandler, Request, Response
from agent import AgentContext
from helpers.persist_chat import save_tmp_chat

log = logging.getLogger("a0.superordinates.set_profile")

PROFILE_DIRS = [
    "/a0/agents",
    "/a0/usr/agents",
]


def _profile_exists(profile: str) -> bool:
    if not profile or profile.startswith("_") or profile.startswith("."):
        return False
    for base in PROFILE_DIRS:
        yaml_path = os.path.join(base, profile, "agent.yaml")
        if os.path.isfile(yaml_path):
            return True
    return False


class SuperordinateSetProfile(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid", "") or "").strip()
        profile = (input.get("profile", "") or "").strip()

        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}
        if not profile:
            return {"ok": False, "error": "Missing profile"}
        if not _profile_exists(profile):
            return {"ok": False, "error": f"Profile '{profile}' not found"}

        ctx = AgentContext.get(ctxid)
        if not ctx:
            try:
                ctx = self.use_context(ctxid, create_if_not_exists=False)
            except Exception:
                ctx = None
        if not ctx:
            return {"ok": False, "error": f"Context '{ctxid}' not found"}

        old_profile = ctx.data.get("sup_profile") or (ctx.config.profile if ctx.config else "") or ""

        # 1. Persistent metadata (survives restart)
        ctx.data["sup_profile"] = profile

        # 2. Live runtime — update the context's config so all agents in this
        # context (agent0 + any subordinates already created from it) pick it
        # up on their next read_prompt / subagents.get_paths call.
        try:
            if ctx.config is not None:
                ctx.config.profile = profile
        except Exception as e:
            log.warning(f"[SET_PROFILE] failed to update ctx.config.profile: {e}")

        # 3. Update the chat display name if it follows "<Name> (<old_profile>)"
        # (the convention used by superordinate_spawn). Leave manually-edited
        # names alone.
        updated_display_name = None
        if old_profile and ctx.name:
            pattern = re.compile(r"^(.*)\s*\(" + re.escape(old_profile) + r"\)\s*$")
            m = pattern.match(ctx.name)
            if m:
                base_name = m.group(1).strip()
                new_name = f"{base_name} ({profile})"
                ctx.name = new_name
                updated_display_name = new_name

        # 4. Update the parent's sup_children entry for this child (so the UI
        # tree shows the new profile).
        try:
            parent_id = ctx.data.get("sup_parent") or None
            if parent_id:
                parent_ctx = AgentContext.get(parent_id)
                if not parent_ctx:
                    try:
                        parent_ctx = self.use_context(parent_id, create_if_not_exists=False)
                    except Exception:
                        parent_ctx = None
                if parent_ctx:
                    children = parent_ctx.data.get("sup_children", [])
                    changed = False
                    for entry in children:
                        if entry.get("ctxid") == ctxid:
                            entry["profile"] = profile
                            changed = True
                            break
                    if changed:
                        parent_ctx.data["sup_children"] = children
                        save_tmp_chat(parent_ctx)
        except Exception as e:
            log.warning(f"[SET_PROFILE] failed to update parent sup_children: {e}")

        # 5. Persist the child context
        save_tmp_chat(ctx)

        log.warning(
            f"[SET_PROFILE] ctx={ctxid} profile: {old_profile!r} -> {profile!r}, display_name={updated_display_name!r}"
        )

        return {
            "ok": True,
            "profile": profile,
            "old_profile": old_profile,
            "display_name": updated_display_name,
        }
