"""API endpoint for UI to fetch the superordinate hierarchy tree."""

from helpers.api import ApiHandler, Request, Response


class SuperordinateHierarchy(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = input.get("context", "")

        if not ctxid:
            return {"error": "Missing 'context' parameter"}

        # use_context loads from disk if not in memory
        context = self.use_context(ctxid, create_if_not_exists=False)
        if not context:
            return {"error": f"Context '{ctxid}' not found"}

        # Build full hierarchy tree (uses disk fallback for unloaded contexts)
        from usr.plugins.a0_superordinates.helpers.hierarchy import get_hierarchy
        hierarchy = get_hierarchy(ctxid)

        return {"hierarchy": hierarchy}
