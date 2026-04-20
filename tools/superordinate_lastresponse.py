"""Retrieve the last conclusive response from a persistent superordinate's chat log.

Reads directly from the chat.json file on disk — does not block or await
any current processing in the superordinate's context.
"""

import json
import os

from helpers.tool import Tool, Response


def _read_last_response(ctxid: str) -> str | None:
    """Read the last response-type log entry from a chat.json on disk."""
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return None
    try:
        with open(chat_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    log = data.get("log", {})
    logs = log.get("logs", [])
    if not logs:
        return None

    # Walk backwards to find the last response entry
    for entry in reversed(logs):
        if entry.get("type") == "response":
            return entry.get("content", "")

    # No response entry found — return the last log entry content
    last = logs[-1]
    return last.get("content", "")


def _read_last_progress(ctxid: str) -> str | None:
    """Read the current progress string from a chat.json on disk."""
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return None
    try:
        with open(chat_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    log = data.get("log", {})
    return log.get("progress", None)


class SuperordinateLastresponse(Tool):

    async def execute(self, **kwargs):
        name = kwargs.get("name", "")
        superordinate_id = kwargs.get("superordinate_id", "")

        # Resolve name to ctxid if name provided
        if name and not superordinate_id:
            from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_name
            resolved = lookup_by_name(name)
            if not resolved:
                return Response(
                    message="No SuperOrdinate found with name '{}'. Use superordinate_list to see available names.".format(name),
                    break_loop=False,
                )
            superordinate_id = resolved

        if not superordinate_id:
            return Response(
                message="Provide either 'name' or 'superordinate_id' to identify the superordinate.",
                break_loop=False,
            )

        # Read last response from disk (non-blocking)
        last_response = _read_last_response(superordinate_id)

        if last_response is None:
            # Check if context exists at all
            chat_file = os.path.join("/a0/usr/chats", superordinate_id, "chat.json")
            if not os.path.isfile(chat_file):
                return Response(
                    message="SuperOrdinate '{}' has no chat data on disk. It may have been removed.".format(name or superordinate_id),
                    break_loop=False,
                )
            return Response(
                message="SuperOrdinate '{}' has no response yet. It may still be processing.".format(name or superordinate_id),
                break_loop=False,
            )

        # Also grab current progress indicator
        progress = _read_last_progress(superordinate_id)
        status_line = ""
        if progress:
            status_line = " (current status: {})".format(progress)

        display_name = name or superordinate_id
        return Response(
            message="Last response from SuperOrdinate '{}':{}\n\n{}".format(
                display_name, status_line, last_response
            ),
            break_loop=False,
            additional={"superordinate_id": superordinate_id, "name": name},
        )
