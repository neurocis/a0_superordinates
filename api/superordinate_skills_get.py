"""Get one context's local skills.md and resolved upward-flowing skills."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response


class SuperordinateSkillsGet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}

        try:
            from usr.plugins.a0_superordinates.helpers.skills import (
                build_skills_prompt,
                read_skills_file,
                resolve_descendant_chain,
                resolve_skills_entries,
                skills_path,
            )

            entries = resolve_skills_entries(ctxid)
            return {
                "ok": True,
                "ctxid": ctxid,
                "path": skills_path(ctxid),
                "local_text": read_skills_file(ctxid),
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
                "effective_prompt": build_skills_prompt(ctxid),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
