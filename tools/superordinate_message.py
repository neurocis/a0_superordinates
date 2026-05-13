"""Send a message to a related persistent superordinate context.

Allowed targets, relative to the calling context:
- descendant: any superordinate spawned beneath this context (children, grandchildren, ...)
- ancestor:   the parent context, grandparent, etc.
- sibling:    a context that shares the same immediate `sup_parent`
"""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage
from helpers import message_queue
import uuid


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



def _direct_parent_id(ctx) -> str:
    """Return the immediate parent ctxid for a context, or an empty string."""
    if not ctx:
        return ""
    return ctx.data.get("sup_parent") or ""


def _parent_notification_message(ctxid: str) -> str:
    """Exact lightweight notification allowed when parent messaging is disabled."""
    return f"{ctxid} has sent you a message"


def _display_inbound_message(target_context, message: str, *, source: str = " (from superordinate_message)") -> str:
    """Log an inbound superordinate_message in the recipient chat UI.

    ``AgentContext.communicate()`` starts processing but, unlike the normal UI/API
    message path, it does not create the visible user-log row that appears in the
    recipient chat immediately. Mirror the framework's message_queue/API pattern:
    log the user message to the target context first, then pass the same id into
    ``UserMessage`` so history/log correlation remains stable.
    """
    msg_id = str(uuid.uuid4())
    message_queue.log_user_message(
        target_context,
        message or "",
        [],
        message_id=msg_id,
        source=source,
    )
    return msg_id


def _add_context_message_without_prompt(target_context, message: str, message_id: str) -> bool:
    """Append a visible/logged message to agent history without prompting.

    This is used for source/intermediate observer copies and for final ``To``
    delivery when the envelope ``Type`` is ``Info``. The message becomes context
    for future turns, but no ``AgentContext.communicate()`` call is made.
    """
    try:
        target_context.get_agent().hist_add_user_message(UserMessage(message=message, id=message_id))
        return True
    except Exception:
        return False


def _remember_pending_reply_route(
    target_context,
    *,
    inbound_message_id: str,
    source_id: str,
    source_name: str,
    target_id: str,
    target_name: str,
    reply: str,
) -> None:
    """Persist reverse-route metadata for the prompted target context.

    The completion hook should not have to parse rendered history to determine
    where a routed prompt came from. Store the route against the exact inbound
    message id used for ``communicate()`` so process_chain_end can route the
    completed response back deterministically.
    """
    if not target_context or not inbound_message_id:
        return
    routes = target_context.data.setdefault("_superordinate_pending_reply_routes", {})
    if not isinstance(routes, dict):
        routes = {}
        target_context.data["_superordinate_pending_reply_routes"] = routes
    routes[inbound_message_id] = {
        "from_id": source_id,
        "from_name": source_name,
        "to_id": target_id,
        "to_name": target_name,
        "reply": reply or "Info",
    }


def _normalize_message_type(value: object) -> str:
    """Return a safe non-empty envelope Type label, defaulting to Prompt."""
    text = str(value or "Prompt").strip()
    if not text:
        return "Prompt"
    # Keep the envelope header single-line and compact.
    return " ".join(text.split())


def _reply_fragment(message_type: str) -> str:
    """Return compact Reply fragment, omitting Info."""
    reply_label = _normalize_message_type(message_type)
    return "" if reply_label.lower() == "info" else f", Reply: {reply_label}"


def _prompt_envelope(
    from_name: str,
    from_id: str,
    message: str,
    message_type: str = "Prompt",
) -> str:
    """Return the final recipient-facing routed-message envelope."""
    reply_fragment = _reply_fragment(message_type)
    return f'{{From: "{from_name}" ({from_id}){reply_fragment}}}\n\n{message or ""}'


def _inform_envelope(
    from_name: str,
    from_id: str,
    to_name: str,
    to_id: str,
    message: str,
    message_type: str = "Info",
) -> str:
    """Return the non-prompt informational envelope for hierarchy intermediates."""
    reply_fragment = _reply_fragment(message_type)
    return (
        f'{{From: "{from_name}" ({from_id}), To: "{to_name}" ({to_id}){reply_fragment}}}'
        f"\n\n{message or ''}"
    )


def _source_inform_envelope(
    to_name: str,
    to_id: str,
    message: str,
    message_type: str = "Info",
) -> str:
    """Return the non-prompt informational envelope for the source/From agent."""
    reply_fragment = _reply_fragment(message_type)
    return f'{{To: "{to_name}" ({to_id}){reply_fragment}}}\n\n{message or ""}'

def _ancestor_chain(ctxid: str, max_depth: int = 64) -> list[str]:
    """Return ctxid followed by its parents up to the root/known boundary."""
    chain: list[str] = []
    cur = ctxid
    seen: set[str] = set()
    for _ in range(max_depth):
        if not cur or cur in seen:
            break
        seen.add(cur)
        chain.append(cur)
        ctx = AgentContext.get(cur)
        if not ctx:
            break
        cur = ctx.data.get("sup_parent") or ""
    return chain


def _hierarchy_path_between(source_id: str, target_id: str) -> list[str]:
    """Return hierarchy path nodes strictly between source and target.

    Uses authoritative parent links to find the source→target path for ancestor,
    descendant, and sibling/cousin relationships. If there is no common loaded
    ancestor, there are no hierarchy intermediates to inform.
    """
    if not source_id or not target_id or source_id == target_id:
        return []

    source_chain = _ancestor_chain(source_id)
    target_chain = _ancestor_chain(target_id)
    if not source_chain or not target_chain:
        return []

    source_index = {ctxid: idx for idx, ctxid in enumerate(source_chain)}
    lca = ""
    target_lca_index = -1
    for idx, ctxid in enumerate(target_chain):
        if ctxid in source_index:
            lca = ctxid
            target_lca_index = idx
            break
    if not lca:
        return []

    up_from_source = source_chain[:source_index[lca] + 1]
    down_to_target = list(reversed(target_chain[:target_lca_index]))
    full_path = up_from_source + down_to_target
    return full_path[1:-1]


def _inform_hierarchy_intermediates(
    source_id: str,
    source_name: str,
    target_id: str,
    target_name: str,
    message: str,
    message_type: str = "Info",
    include_intermediaries: bool = True,
) -> list[str]:
    """Log observer messages to source/intermediates without prompting.

    The source always needs awareness/context for the routed message. Hierarchy
    intermediaries are included only when ``keep_everybody_in_the_loop`` is
    enabled. None of these observers are the addressed ``To`` agent, so they must
    not start processing this as a prompt.
    """
    informed: list[str] = []
    intermediate_envelope = _inform_envelope(
        source_name,
        source_id,
        target_name,
        target_id,
        message,
        message_type,
    )
    source_envelope = _source_inform_envelope(target_name, target_id, message, message_type)
    observer_ids = [source_id]
    if include_intermediaries:
        observer_ids.extend(_hierarchy_path_between(source_id, target_id))
    seen: set[str] = set()
    for ctxid in observer_ids:
        if not ctxid or ctxid in seen or ctxid == target_id:
            continue
        seen.add(ctxid)
        ctx = AgentContext.get(ctxid)
        if not ctx:
            continue
        envelope = source_envelope if ctxid == source_id else intermediate_envelope
        msg_id = _display_inbound_message(ctx, envelope)
        if not _add_context_message_without_prompt(ctx, envelope, msg_id):
            # Visible logging is the critical behavior; history/context append is
            # best-effort so an observer notification cannot break delivery to
            # the final target.
            pass
        informed.append(ctxid)
    return informed


def _is_ancestor_notification_fallback(relationship: str, agent, target_ctx) -> bool:
    """True when disabled parent messaging should become notify-ancestor/local-output.

    When `allow_parent_messaging` is false, a descendant may still *attempt* to
    report completion to any ancestor/addressee in its hierarchy. The full
    message is not sent upward; `execute()` sends only a lightweight notifier
    to the addressed ancestor and returns the full message locally to the
    sender's context.

    This intentionally supports arbitrary ancestor depth, not only direct
    parent relationships, while still relying on the already-classified
    relationship so unrelated contexts cannot receive fallback notifications.
    """
    caller_ctx = getattr(agent, "context", None)
    caller_id = getattr(caller_ctx, "id", "") or ""
    target_id = getattr(target_ctx, "id", "") or ""

    if relationship != "ancestor":
        return False
    if not caller_id or not target_id:
        return False
    return _is_ancestor(target_id, caller_id)


def _relationship_allowed(relationship: str, agent, target_ctx=None, message: str = "") -> tuple[bool, str, bool]:
    """Return whether the classified relationship is enabled by settings.

    Returns ``(allowed, denial_reason, parent_notification_fallback)``.

    Descendant messaging is the original/core behavior and remains always
    enabled. Ancestor and sibling messaging are optional features exposed in
    the plugin settings UI. When parent messaging is disabled, descendant-to-
    ancestor sends are allowed only as a fallback: the addressed ancestor
    receives ``{ContextID} has sent you a message`` and the caller's full
    message is returned locally to the sender context instead of being sent
    upward.
    """
    if relationship == "descendant":
        return True, "", False

    config = _get_config(agent)

    if relationship == "ancestor" and not _setting_enabled(config, "allow_parent_messaging", False):
        if _is_ancestor_notification_fallback(relationship, agent, target_ctx):
            return True, "", True
        return False, (
            "Parent / ancestor messaging is disabled in the a0_superordinates settings. "
            "Only ancestor notification fallback is allowed; the full message "
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
        delivery_type = _normalize_message_type(kwargs.get("Type", "Prompt"))
        message_type = _normalize_message_type(kwargs.get("reply", "Prompt"))
        if delivery_type.lower() == "info":
            message_type = "Info"

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
            if kwargs.get("_allow_unrelated_route"):
                relationship = "routed"
            else:
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
        # monologue conclusion upward. Notify the addressed ancestor only, then
        # return the full message locally so it is output in the sender context.
        if parent_notification_fallback:
            notification = _parent_notification_message(caller_ctxid)
            notification_id = _display_inbound_message(target_context, notification)
            target_context.communicate(UserMessage(message=notification, id=notification_id))
            local_message = message or ""
            return Response(
                message=(
                    "Parent / ancestor messaging is disabled, so your full message was not sent upward. "
                    "Sent this notification to ancestor '{}': {}\n\n"
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

        config = _get_config(self.agent)
        keep_everybody_in_the_loop = _setting_enabled(
            config,
            "keep_everybody_in_the_loop",
            True,
        )
        informed_intermediates = _inform_hierarchy_intermediates(
            caller_ctxid,
            caller_name,
            superordinate_id,
            target_label,
            message or "",
            message_type,
            include_intermediaries=keep_everybody_in_the_loop,
        )

        forwarded_message = _prompt_envelope(
            caller_name,
            caller_ctxid,
            message or "",
            message_type,
        )

        # Show the same conforming inbound prompt envelope in the recipient chat
        # before dispatching it, matching the standard UI/API message path.
        inbound_message_id = _display_inbound_message(target_context, forwarded_message)

        # Type=Info is context-only delivery even for the final To agent: show it
        # and add it to history/context, but do not trigger processing.
        if delivery_type.lower() == "info":
            history_added = _add_context_message_without_prompt(
                target_context,
                forwarded_message,
                inbound_message_id,
            )
            return Response(
                message="Info delivered to {} '{}' without prompting.".format(relationship, target_label),
                break_loop=False,
                additional={
                    "superordinate_id": superordinate_id,
                    "relationship": relationship,
                    "parent_notification_fallback": parent_notification_fallback,
                    "informed_intermediates": informed_intermediates,
                    "keep_everybody_in_the_loop": keep_everybody_in_the_loop,
                    "delivery_type": delivery_type,
                    "reply": message_type,
                    "prompted_target": False,
                    "target_history_added": history_added,
                },
            )

        _remember_pending_reply_route(
            target_context,
            inbound_message_id=inbound_message_id,
            source_id=caller_ctxid,
            source_name=caller_name,
            target_id=superordinate_id,
            target_name=target_label,
            reply=message_type,
        )

        # communicate() handles both cases:
        # - If target is idle: starts a new task and returns it
        # - If target is running: sets intervention message on the running agent
        target_context.communicate(UserMessage(message=forwarded_message, id=inbound_message_id))

        # Do not wait here. The target's process_chain_end hook will route its
        # final response back to the original From agent according to the stored
        # route metadata / inbound envelope's Reply value.
        return Response(
            message=(
                "Message delivered to {} '{}'. Reply routing will occur when "
                "the target finishes its monologue."
            ).format(relationship, target_label),
            break_loop=False,
            additional={
                "superordinate_id": superordinate_id,
                "relationship": relationship,
                "parent_notification_fallback": parent_notification_fallback,
                "informed_intermediates": informed_intermediates,
                "keep_everybody_in_the_loop": keep_everybody_in_the_loop,
                "delivery_type": delivery_type,
                "reply": message_type,
                "prompted_target": True,
            },
        )
