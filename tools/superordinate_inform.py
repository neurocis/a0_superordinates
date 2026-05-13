"""Send an informational message to a related superordinate context.

This is a convenience wrapper around ``superordinate_message`` that forces the
routed envelope ``Type`` field to ``Info``.
"""

from usr.plugins.a0_superordinates.tools.superordinate_message import SuperordinateMessage


class SuperordinateInform(SuperordinateMessage):
    async def execute(self, **kwargs):
        kwargs = dict(kwargs)
        kwargs["reply"] = "Info"
        return await super().execute(**kwargs)
