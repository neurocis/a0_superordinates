"""Get one context's local inheritance.md and resolved effective inheritance."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response


class SuperordinateInheritanceGet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}

        try:
            from usr.plugins.a0_superordinates.helpers.inheritance import (
                build_inheritance_prompt,
                inheritance_path,
                read_inheritance_file,
                resolve_context_chain,
                resolve_inheritance_entries,
            )

            entries = resolve_inheritance_entries(ctxid)
            return {
                "ok": True,
                "ctxid": ctxid,
                "path": inheritance_path(ctxid),
                "local_text": read_inheritance_file(ctxid),
                "chain": resolve_context_chain(ctxid),
                "entries": [
                    {
                        "context_id": e.context_id,
                        "name": e.name,
                        "path": e.path,
                        "text": e.text,
                    }
                    for e in entries
                ],
                "effective_prompt": build_inheritance_prompt(ctxid),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
