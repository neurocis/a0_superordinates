"""API endpoint returning hierarchy map for ALL chats on disk.

Returns {ctxid: {parent: str|null, children: [ctxid]}} for every chat
that has hierarchy data, enabling the sidebar to render a tree view.
"""

import json
import os

from helpers.api import ApiHandler, Request, Response


class SuperordinateMap(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        hierarchy_map = {}
        chats_dir = "/a0/usr/chats"

        if not os.path.isdir(chats_dir):
            return {"map": hierarchy_map}

        for d in os.listdir(chats_dir):
            chat_file = os.path.join(chats_dir, d, "chat.json")
            if not os.path.isfile(chat_file):
                continue
            try:
                with open(chat_file, "r") as f:
                    data = json.load(f)
                ctx_data = data.get("data", {})
                parent = ctx_data.get("sup_parent") or None
                children = [
                    c["ctxid"]
                    for c in ctx_data.get("sup_children", [])
                    if "ctxid" in c
                ]
                # Only include chats that actually participate in hierarchy
                if parent is not None or len(children) > 0:
                    hierarchy_map[d] = {"parent": parent, "children": children}
            except (json.JSONDecodeError, OSError, KeyError):
                continue

        return {"map": hierarchy_map}
