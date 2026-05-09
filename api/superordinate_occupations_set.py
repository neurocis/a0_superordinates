"""Set one context's local single-file occupations.md."""
from __future__ import annotations

import os

from helpers.api import ApiHandler, Request, Response

MAX_WRITE_BYTES = 256 * 1024


class SuperordinateOccupationsSet(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = (input.get("ctxid") or input.get("context") or "").strip()
        text = input.get("text", "")
        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}
        if not isinstance(text, str):
            return {"ok": False, "error": "text must be a string"}
        if len(text.encode("utf-8")) > MAX_WRITE_BYTES:
            return {"ok": False, "error": "occupations.md is too large"}

        try:
            from usr.plugins.a0_superordinates.helpers.occupations import occupations_path

            path = occupations_path(ctxid)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return {"ok": True, "ctxid": ctxid, "path": path, "bytes": len(text.encode("utf-8"))}
        except Exception as e:
            return {"ok": False, "error": str(e)}
