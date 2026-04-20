"""API endpoint for UI to fetch the superordinate hierarchy tree."""

from helpers.api import ApiHandler, Input, Output
from flask import Request, Response
from agent import AgentContext

class SuperordinateHierarchy(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: Input, request: Request) -> Output:
        ctxid = input.get("context", "")

        if not ctxid:
            return {"error": "Missing 'context' parameter"}

        # Check if context exists
        ctx = AgentContext.get(ctxid)
        if not ctx:
            return {"error": f"Context '{ctxid}' not found"}

        # Build full hierarchy tree
        from usr.plugins.a0_superordinates.helpers.hierarchy import get_hierarchy
        hierarchy = get_hierarchy(ctxid)

        return {"hierarchy": hierarchy}
