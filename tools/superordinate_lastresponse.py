"""Retrieve responses from a persistent superordinate's chat log.

Reads directly from the chat.json file on disk — does not block or await
any current processing in the superordinate's context.
"""

import json
import os

from helpers.tool import Tool, Response


def _load_logs(ctxid: str) -> list[dict]:
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return []
    try:
        with open(chat_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    log = data.get("log", {}) or {}
    return log.get("logs", []) or []


def _extract_user_text(entry: dict) -> str:
    """Best-effort extraction of the user's prompt text from a 'user' log entry.

    The log entry's `content` is normally already a string with the prompt,
    but on some monologue cycles it can be a JSON-encoded blob (e.g. a
    user_message object) or contain a wrapper. We try to peel that.
    """
    content = entry.get("content", "")
    if not content:
        # Sometimes the prompt sits in kvps
        kvps = entry.get("kvps") or {}
        if isinstance(kvps, dict):
            for key in ("user_message", "message", "prompt", "content"):
                v = kvps.get(key)
                if isinstance(v, str) and v:
                    content = v
                    break
    if not isinstance(content, str):
        return str(content) if content else ""

    # Try to peel JSON-encoded user_message wrappers
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                for key in ("user_message", "message", "prompt", "content"):
                    v = obj.get(key)
                    if isinstance(v, str) and v:
                        return v
        except (ValueError, TypeError):
            pass
    return content


def _read_responses(ctxid: str, count: int = -1) -> list[str]:
    """Read response-type log entries from a chat.json on disk.

    count = -1: return only the last response (as a 1-element list)
    count =  0: return all responses
    count =  N: return the last N responses
    """
    logs = _load_logs(ctxid)
    if not logs:
        return []

    responses = []
    for entry in logs:
        if entry.get("type") == "response":
            content = entry.get("content", "")
            if content:
                responses.append(content)

    if not responses:
        last = logs[-1]
        content = last.get("content", "")
        return [content] if content else []

    if count == 0:
        return responses
    elif count < 0:
        return responses[-1:]
    else:
        return responses[-count:]


def _read_paired_cycles(ctxid: str, count: int = -1) -> list[dict]:
    """Walk logs in order, emit paired {prompt, response} cycles.

    A cycle is bounded by a 'user' entry → the next 'response' entry.
    Returns a list of {"prompt": str, "response": str} dicts.

    count = -1: return only the last cycle
    count =  0: return all cycles
    count =  N: return the last N cycles
    """
    logs = _load_logs(ctxid)
    if not logs:
        return []

    cycles: list[dict] = []
    pending_prompt: str | None = None
    for entry in logs:
        etype = entry.get("type")
        if etype == "user":
            pending_prompt = _extract_user_text(entry)
        elif etype == "response":
            resp = entry.get("content", "")
            if resp:
                cycles.append({
                    "prompt": pending_prompt or "",
                    "response": resp,
                })
                pending_prompt = None

    if not cycles:
        return []

    if count == 0:
        return cycles
    elif count < 0:
        return cycles[-1:]
    else:
        return cycles[-count:]


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


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return False


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

        # 3rd parameter: with_prompts
        with_prompts = _truthy(kwargs.get("with_prompts", False))

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

        display_name = name or superordinate_id
        progress = _read_last_progress(superordinate_id)
        status_line = " (current status: {})".format(progress) if progress else ""

        # ── paired prompt+response cycles ────────────────────────────
        if with_prompts:
            cycles = _read_paired_cycles(superordinate_id, count)
            if not cycles:
                chat_file = os.path.join("/a0/usr/chats", superordinate_id, "chat.json")
                if not os.path.isfile(chat_file):
                    return Response(
                        message="SuperOrdinate '{}' has no chat data on disk. It may have been removed.".format(display_name),
                        break_loop=False,
                    )
                return Response(
                    message="SuperOrdinate '{}' has no completed prompt+response cycles yet. It may still be processing.".format(display_name),
                    break_loop=False,
                )

            parts = []
            total = len(cycles)
            for i, cyc in enumerate(cycles, 1):
                parts.append(
                    "--- Cycle {}/{} ---\n[USER]\n{}\n\n[RESPONSE]\n{}".format(
                        i, total, cyc["prompt"] or "(prompt not captured)", cyc["response"]
                    )
                )
            body = "\n\n".join(parts)

            if count == 0:
                label = "All {} prompt+response cycles".format(total)
            elif total == 1:
                label = "Last prompt+response cycle"
            else:
                label = "Last {} prompt+response cycles".format(total)

            return Response(
                message="{} from SuperOrdinate '{}':{}\n\n{}".format(
                    label, display_name, status_line, body
                ),
                break_loop=False,
                additional={
                    "superordinate_id": superordinate_id,
                    "name": name,
                    "count": total,
                    "with_prompts": True,
                },
            )

        # ── responses only (legacy behaviour) ────────────────────────
        responses = _read_responses(superordinate_id, count)

        if not responses:
            chat_file = os.path.join("/a0/usr/chats", superordinate_id, "chat.json")
            if not os.path.isfile(chat_file):
                return Response(
                    message="SuperOrdinate '{}' has no chat data on disk. It may have been removed.".format(display_name),
                    break_loop=False,
                )
            return Response(
                message="SuperOrdinate '{}' has no response yet. It may still be processing.".format(display_name),
                break_loop=False,
            )

        if len(responses) == 1:
            return Response(
                message="Last response from SuperOrdinate '{}':{}\n\n{}".format(
                    display_name, status_line, responses[0]
                ),
                break_loop=False,
                additional={"superordinate_id": superordinate_id, "name": name},
            )

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
