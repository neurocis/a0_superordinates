"""List all available agent profiles.

Scans both core (/a0/agents/) and user (/a0/usr/agents/) profile directories,
reads each agent.yaml, and returns a list of profile metadata for the UI.

Returns:
    {
        "ok": true,
        "profiles": [
            {"name": "agent0", "title": "Agent 0", "description": "...", "context": "..."},
            ...
        ],
        "current_profile": "agent0"  # only when ctxid is supplied in the request
    }

Profile names starting with `_` (e.g. `_example`) and `default` are excluded.
"""

import os
import yaml
import logging

from helpers.api import ApiHandler, Request, Response
from agent import AgentContext

log = logging.getLogger("a0.superordinates.list_profiles")

PROFILE_DIRS = [
    "/a0/agents",
    "/a0/usr/agents",
]


class SuperordinateListProfiles(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST", "GET"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid", "") or "").strip()
        profiles_by_name: dict[str, dict] = {}

        for base in PROFILE_DIRS:
            if not os.path.isdir(base):
                continue
            try:
                entries = os.listdir(base)
            except OSError:
                continue

            for entry in entries:
                # Skip hidden, underscore-prefixed (private/example), and 'default'
                if entry.startswith(".") or entry.startswith("_") or entry == "default":
                    continue

                profile_dir = os.path.join(base, entry)
                if not os.path.isdir(profile_dir):
                    continue

                yaml_path = os.path.join(profile_dir, "agent.yaml")
                if not os.path.isfile(yaml_path):
                    continue

                try:
                    with open(yaml_path, "r") as f:
                        meta = yaml.safe_load(f) or {}
                except (yaml.YAMLError, OSError) as e:
                    log.warning(f"Failed to read {yaml_path}: {e}")
                    continue

                # User profiles override core profiles with the same name
                profiles_by_name[entry] = {
                    "name": entry,
                    "title": meta.get("title", entry),
                    "description": meta.get("description", ""),
                    "context": meta.get("context", ""),
                }

        # Sort: agent0 first, then alphabetical by title
        def sort_key(p):
            return (0 if p["name"] == "agent0" else 1, p["title"].lower())

        profiles = sorted(profiles_by_name.values(), key=sort_key)

        # Resolve the current profile for the requested context (if any).
        current_profile = ""
        if ctxid:
            ctx = AgentContext.get(ctxid)
            if ctx is not None:
                current_profile = (
                    ctx.data.get("sup_profile")
                    or (ctx.config.profile if ctx.config else "")
                    or ""
                )

        return {
            "ok": True,
            "profiles": profiles,
            "current_profile": current_profile,
        }
