"""Retrieve responses from a persistent superordinate's chat log.

Reads directly from the chat.json file on disk — does not block or await
any current processing in the superordinate's context.
"""

import json
import os

from helpers.tool import Tool, Response


def _read_responses(ctxid: str, count: int = -1) -> list[str]:
    """Read response-type log entries from a chat.json on disk.

    count = -1: return only the last response (as a 1-element list)
    count =  0: return all responses
    count =  N: return the last N responses
    """
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return []
    try:
        with open(chat_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    log = data.get("log", {})
    logs = log.get("logs", [])
    if not logs:
        return []

    # Collect all response entries
    responses = []
    for entry in logs:
        if entry.get("type") == "response":
            content = entry.get("content", "")
            if content:
                responses.append(content)

    if not responses:
        # Fallback: return the last log entry content
        last = logs[-1]
        content = last.get("content", "")
        return [content] if content else []

    if count == 0:
        return responses
    elif count < 0:
        return responses[-1:]
    else:
        return responses[-count:]


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

        # Parse count: default -1 (last only), 0 = all, N = last N
        count_raw = kwargs.get("count", "-1")
        try:
            count = int(count_raw)
        except (ValueError, TypeError):
            count = -1

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

        # Read responses from disk (non-blocking)
        responses = _read_responses(superordinate_id, count)

        if not responses:
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

        if len(responses) == 1:
            return Response(
                message="Last response from SuperOrdinate '{}':{}\n\n{}".format(
                    display_name, status_line, responses[0]
                ),
                break_loop=False,
                additional={"superordinate_id": superordinate_id, "name": name},
            )

        # Multiple responses
        parts = []
        for i, resp in enumerate(responses, 1):
            parts.append("--- Response {}/{} ---\n{}".format(i, len(responses), resp))
        body = "\n\n".join(parts)

        if count == 0:
            label = "All {} responses".format(len(responses))
        else:
            label = "Last {} responses".format(len(responses))

        return Response(
            message="{} from SuperOrdinate '{}':{}\n\n{}".format(
                label, display_name, status_line, body
            ),
            break_loop=False,
            additional={"superordinate_id": superordinate_id, "name": name, "count": len(responses)},
        )
