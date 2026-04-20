"""API endpoint returning ALL chats from disk, merged with running context metadata.

Returns list of chat objects suitable for merging into chatsStore.contexts.
"""

import json
import os
from datetime import datetime
from helpers.api import ApiHandler, Request, Response


class AllChats(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict:
        """Return all chats from disk with minimal metadata."""
        chats = []
        chats_dir = "/a0/usr/chats"

        if not os.path.isdir(chats_dir):
            return {"chats": chats}

        # Scan all chat directories
        for d in os.listdir(chats_dir):
            chat_dir = os.path.join(chats_dir, d)
            if not os.path.isdir(chat_dir):
                continue

            chat_file = os.path.join(chat_dir, "chat.json")
            if not os.path.isfile(chat_file):
                continue

            try:
                with open(chat_file, "r") as f:
                    data = json.load(f)

                # Extract minimal metadata for sidebar
                name = data.get("name", f"Chat #{data.get('no', '?')}")
                no = data.get("no", 0)
                project = data.get("project", {})
                running = data.get("running", False)

                chat_obj = {
                    "id": d,
                    "name": name,
                    "no": no,
                    "running": running,
                    "project": project,
                }

                chats.append(chat_obj)
            except (json.JSONDecodeError, OSError, KeyError):
                # Skip corrupted chats
                continue

        return {"chats": chats}
