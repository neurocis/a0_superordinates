"""Deprecated hook location for superordinate reply routing.

Reply routing now runs from:

    extensions/python/process_chain_end/_50_route_superordinate_reply.py

Agent Zero only calls named ``monologue_end`` extensions while the context task is
still alive, so routed task completions can skip it. ``process_chain_end`` is the
reliable completion hook for this behavior.
"""

from helpers.extension import Extension


class RouteSuperordinateReplyDeprecated(Extension):
    async def execute(self, **kwargs):
        return
