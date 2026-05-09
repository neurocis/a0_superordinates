"""Get one context's local roles.md and resolved upward-flowing roles."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response


class SuperordinateRolesGet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}

        try:
            from usr.plugins.a0_superordinates.helpers.roles import (
                build_roles_prompt,
                read_roles_file,
                resolve_descendant_chain,
                resolve_roles_entries,
                roles_path,
            )

            entries = resolve_roles_entries(ctxid)
            return {
                "ok": True,
                "ctxid": ctxid,
                "path": roles_path(ctxid),
                "local_text": read_roles_file(ctxid),
                "chain": [node_id for node_id, _depth in resolve_descendant_chain(ctxid)],
                "entries": [
                    {
                        "context_id": e.context_id,
                        "name": e.name,
                        "path": e.path,
                        "text": e.text,
                        "depth": e.depth,
                    }
                    for e in entries
                ],
                "effective_prompt": build_roles_prompt(ctxid),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
