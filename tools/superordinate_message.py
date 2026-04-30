"""Send a message to a related persistent superordinate context and wait for its response.

Allowed targets, relative to the calling context:
- descendant: any superordinate spawned beneath this context (children, grandchildren, ...)
- ancestor:   the parent context, grandparent, etc.
- sibling:    a context that shares the same immediate `sup_parent`
"""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage


def _is_descendant(target_ctxid: str, root_ctxid: str, max_depth: int = 64) -> bool:
    """True if target_ctxid is reachable by walking sup_children from root_ctxid."""
    if not target_ctxid or not root_ctxid or target_ctxid == root_ctxid:
        return False
    seen = set()
    frontier = [root_ctxid]
    depth = 0
    while frontier and depth < max_depth:
        next_frontier = []
        for cid in frontier:
            if cid in seen:
                continue
            seen.add(cid)
            ctx = AgentContext.get(cid)
            if not ctx:
                continue
            children = ctx.data.get("sup_children") or []
            for entry in children:
                child_id = (entry.get("ctxid") or entry.get("id")) if isinstance(entry, dict) else entry
                if not child_id:
                    continue
                if child_id == target_ctxid:
                    return True
                next_frontier.append(child_id)
        frontier = next_frontier
        depth += 1
    return False


def _is_ancestor(target_ctxid: str, start_ctxid: str, max_depth: int = 64) -> bool:
    """True if target_ctxid is reached by walking sup_parent up from start_ctxid."""
    if not target_ctxid or not start_ctxid or target_ctxid == start_ctxid:
        return False
    cur = start_ctxid
    seen = set()
    for _ in range(max_depth):
        if cur in seen:
            return False
        seen.add(cur)
        ctx = AgentContext.get(cur)
        if not ctx:
            return False
        parent = ctx.data.get("sup_parent")
        if not parent:
            return False
        if parent == target_ctxid:
            return True
        cur = parent
    return False


def _is_sibling(target_ctx, self_ctx) -> bool:
    """True if the target shares the same immediate `sup_parent` as the caller.

    Both must have a non-empty `sup_parent` for the relationship to exist; root
    contexts are never considered siblings of each other.
    """
    if not target_ctx or not self_ctx or target_ctx.id == self_ctx.id:
        return False
    self_parent = self_ctx.data.get("sup_parent")
    target_parent = target_ctx.data.get("sup_parent")
    if not self_parent or not target_parent:
        return False
    return self_parent == target_parent


def _classify_relationship(target_ctx, self_ctx) -> str:
    """Return one of 'descendant', 'ancestor', 'sibling', or '' if unrelated."""
    if not target_ctx or not self_ctx:
        return ""
    target_id = target_ctx.id
    self_id = self_ctx.id
    if _is_descendant(target_id, self_id):
        return "descendant"
    if _is_ancestor(target_id, self_id):
        return "ancestor"
    if _is_sibling(target_ctx, self_ctx):
        return "sibling"
    return ""


def _get_config(agent) -> dict:
    """Read a0_superordinates config, falling back safely to defaults."""
    try:
        from helpers import plugins
        config = plugins.get_plugin_config("a0_superordinates", agent=agent) or {}
        return config if isinstance(config, dict) else {}
    except Exception:
        return {}


def _setting_enabled(config: dict, key: str, default: bool = True) -> bool:
    """Return boolean config value with permissive string handling."""
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _reply_wait_seconds(config: dict, default: int = 5) -> int:
    """Return configured superordinate_message reply wait seconds.

    Falls back to 5 seconds and clamps to a sane positive range so broken or
    missing config cannot create an infinite wait or immediate zero-timeout.
    """
    value = config.get("reply_wait_seconds", default)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    return max(1, min(seconds, 600))


def _direct_parent_id(ctx) -> str:
    """Return the immediate parent ctxid for a context, or an empty string."""
    if not ctx:
        return ""
    return ctx.data.get("sup_parent") or ""


def _parent_notification_message(ctxid: str) -> str:
    """Exact lightweight notification allowed when parent messaging is disabled."""
    return f"{ctxid} has a message for you."


def _is_direct_parent_fallback(relationship: str, agent, target_ctx) -> bool:
    """True when disabled parent messaging should become notify-parent/local-output.

    When `allow_parent_messaging` is false, a child may still *attempt* to send
    its real monologue conclusion to its immediate parent. The full message is
    not sent upward; `execute()` sends only a lightweight notification to the
    parent and returns the full message locally to the sender's context.
    """
    caller_ctx = getattr(agent, "context", None)
    caller_id = getattr(caller_ctx, "id", "") or ""
    target_id = getattr(target_ctx, "id", "") or ""

    if relationship != "ancestor":
        return False
    if not caller_id or not target_id:
        return False
    return target_id == _direct_parent_id(caller_ctx)


def _relationship_allowed(relationship: str, agent, target_ctx=None, message: str = "") -> tuple[bool, str, bool]:
    """Return whether the classified relationship is enabled by settings.

    Returns ``(allowed, denial_reason, parent_notification_fallback)``.

    Descendant messaging is the original/core behavior and remains always
    enabled. Ancestor and sibling messaging are optional features exposed in
    the plugin settings UI. When parent messaging is disabled, direct-child to
    immediate-parent sends are allowed only as a fallback: the parent receives
    ``{ContextID} has a message for you.`` and the caller's full message is
    returned locally to the sender context instead of being sent upward.
    """
    if relationship == "descendant":
        return True, "", False

    config = _get_config(agent)

    if relationship == "ancestor" and not _setting_enabled(config, "allow_parent_messaging", False):
        if _is_direct_parent_fallback(relationship, agent, target_ctx):
            return True, "", True
        return False, (
            "Parent / ancestor messaging is disabled in the a0_superordinates settings. "
            "Only immediate-parent notification fallback is allowed; the full message "
            "will not be sent upward."
        ), False

    if relationship == "sibling" and not _setting_enabled(config, "allow_sibling_messaging", False):
        return False, "Sibling messaging is disabled in the a0_superordinates settings.", False

    return True, "", False


class SuperordinateMessage(Tool):

    async def execute(self, **kwargs):
        superordinate_id = kwargs.get("superordinate_id", "")
        name = kwargs.get("name", "")
        message = kwargs.get("message", "")

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
                message="Provide either 'superordinate_id' or 'name' to identify the target context.",
                break_loop=False,
            )

        # Get target context
        target_context = AgentContext.get(superordinate_id)
        if not target_context:
            return Response(
                message="Context '{}' not found. It may have been closed.".format(superordinate_id),
                break_loop=False,
            )

        # Verify the target is related (descendant, ancestor, or sibling)
        if target_context.id == self.agent.context.id:
            return Response(
                message="Cannot send a superordinate_message to yourself.",
                break_loop=False,
            )

        relationship = _classify_relationship(target_context, self.agent.context)
        if not relationship:
            return Response(
                message=(
                    "Context '{}' is not related to this context. Allowed targets are descendants, "
                    "ancestors (parent, grandparent, ...), or siblings sharing the same parent."
                ).format(superordinate_id),
                break_loop=False,
            )

        relationship_allowed, relationship_denial, parent_notification_fallback = _relationship_allowed(
            relationship,
            self.agent,
            target_context,
            message,
        )
        if not relationship_allowed:
            return Response(
                message=(
                    "Cannot send superordinate_message to {} '{}': {}"
                ).format(relationship, target_context.name or superordinate_id, relationship_denial),
                break_loop=False,
            )

        caller_ctxid = self.agent.context.id
        caller_name = self.agent.context.name or f"Chat {caller_ctxid[:6]}"
        target_label = target_context.name or superordinate_id

        # Parent messaging disabled fallback: never send the caller's full
        # monologue conclusion upward. Notify the immediate parent only, then
        # return the full message locally so it is output in the sender context.
        if parent_notification_fallback:
            notification = _parent_notification_message(caller_ctxid)
            target_context.communicate(UserMessage(message=notification))
            local_message = message or ""
            return Response(
                message=(
                    "Parent / ancestor messaging is disabled, so your full message was not sent upward. "
                    "Sent this notification to parent '{}': {}\n\n"
                    "Monologue conclusion for this context:\n{}"
                ).format(target_label, notification, local_message),
                break_loop=False,
                additional={
                    "superordinate_id": superordinate_id,
                    "relationship": relationship,
                    "parent_notification_fallback": True,
                    "notification_sent": notification,
                    "full_message_sent_to_parent": False,
                },
            )

        # Append a callback instruction so the target sends its results back to
        # the calling agent/context when done.
        callback_instruction = (
            "\n\n[Instruction from framework]\n"
            "When you finish this task, send your result back to the calling agent "
            f"using superordinate_message with superordinate_id='{caller_ctxid}' and include your "
            "final result in that message. If parent/ancestor messaging is disabled, "
            "superordinate_message will send only a lightweight notification to your immediate "
            "parent and return your full result locally in your own context; do not replace "
            "your final result with the notification text. "
            f"The calling agent/context is: {caller_name} (relationship to you: "
            f"{'parent/ancestor' if relationship == 'descendant' else ('child/descendant' if relationship == 'ancestor' else 'sibling')})."
        )
        forwarded_message = (message or "") + callback_instruction

        # communicate() handles both cases:
        # - If target is idle: starts a new task and returns it
        # - If target is running: sets intervention message on the running agent
        task = target_context.communicate(UserMessage(message=forwarded_message))

        # Wait for the result with a configurable timeout so we don't block the monologue.
        reply_wait_seconds = _reply_wait_seconds(_get_config(self.agent))
        try:
            result = await task.result(timeout=reply_wait_seconds)
        except Exception as e:
            err = str(e).lower()
            if "timeout" in err or "timed out" in err:
                return Response(
                    message=(
                        "Target '{}' ({}) is still processing (timed out after {}s). "
                        "Continue with your current task and check back later using "
                        "superordinate_getresponse(name='{}')."
                    ).format(target_label, relationship, reply_wait_seconds, name or superordinate_id),
                    break_loop=False,
                )
            return Response(
                message="Error waiting for target '{}' ({}): {}".format(target_label, relationship, str(e)),
                break_loop=False,
            )

        return Response(
            message="Response from {} '{}': {}".format(relationship, target_label, result),
            break_loop=False,
            additional={
                "superordinate_id": superordinate_id,
                "relationship": relationship,
                "parent_notification_fallback": parent_notification_fallback,
            },
        )
