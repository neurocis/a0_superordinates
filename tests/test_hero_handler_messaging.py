import sys
import types
from types import SimpleNamespace

sys.path.insert(0, "/a0")

# Minimal runtime stubs so the helper functions in the tool module can be
# imported without loading the full Agent Zero runtime/dependencies.
helpers_pkg = types.ModuleType("helpers")
tool_mod = types.ModuleType("helpers.tool")
message_queue_mod = types.ModuleType("helpers.message_queue")
agent_mod = types.ModuleType("agent")

class Tool:
    pass

class Response:
    def __init__(self, message="", break_loop=False, additional=None):
        self.message = message
        self.break_loop = break_loop
        self.additional = additional or {}

class AgentContext:
    @staticmethod
    def get(_ctxid):
        return None

class UserMessage:
    def __init__(self, message="", id=""):
        self.message = message
        self.id = id

tool_mod.Tool = Tool
tool_mod.Response = Response
agent_mod.AgentContext = AgentContext
agent_mod.UserMessage = UserMessage
message_queue_mod.log_user_message = lambda *args, **kwargs: None
helpers_pkg.tool = tool_mod
helpers_pkg.message_queue = message_queue_mod

sys.modules.setdefault("helpers", helpers_pkg)
sys.modules.setdefault("helpers.tool", tool_mod)
sys.modules.setdefault("helpers.message_queue", message_queue_mod)
sys.modules.setdefault("agent", agent_mod)

from usr.plugins.a0_superordinates.tools.superordinate_message import (  # noqa: E402
    _prompt_envelope,
    _resolve_handler_alias,
    _source_display_name,
)


def test_handler_name_resolves_as_hero_alias_with_normalized_match():
    config = {
        "hero_handler_name": "neurocis.ai",
        "hero_mode_designated_hero": "rlO1iMV7",
    }

    assert _resolve_handler_alias("Neurocis AI", config) == "rlO1iMV7"
    assert _resolve_handler_alias("neurocis.ai", config) == "rlO1iMV7"


def test_handler_alias_does_not_resolve_without_configured_hero():
    assert _resolve_handler_alias("neurocis", {"hero_handler_name": "neurocis"}) == ""
    assert _resolve_handler_alias("neurocis", {"hero_mode_designated_hero": "rlO1iMV7"}) == ""
    assert _resolve_handler_alias("other", {"hero_handler_name": "neurocis", "hero_mode_designated_hero": "rlO1iMV7"}) == ""


def test_hero_source_display_uses_handler_name_with_hero_context_id():
    config = {
        "hero_handler_name": "neurocis",
        "hero_mode_designated_hero": "rlO1iMV7",
    }
    hero_ctx = SimpleNamespace(id="rlO1iMV7", name="AIme")

    assert _source_display_name(hero_ctx, config, target_id="Sl17xkus") == "neurocis"
    assert _prompt_envelope("neurocis", "rlO1iMV7", "hello", "Prompt").startswith('{From: "neurocis" (rlO1iMV7), Reply: Prompt}')


def test_hero_source_display_keeps_hero_name_when_target_is_hero():
    config = {
        "hero_handler_name": "neurocis",
        "hero_mode_designated_hero": "rlO1iMV7",
    }
    hero_ctx = SimpleNamespace(id="rlO1iMV7", name="AIme")

    assert _source_display_name(hero_ctx, config, target_id="rlO1iMV7") == "AIme"


def test_non_hero_source_display_keeps_agent_name():
    config = {
        "hero_handler_name": "neurocis",
        "hero_mode_designated_hero": "rlO1iMV7",
    }
    other_ctx = SimpleNamespace(id="Sl17xkus", name="Hero Mode")

    assert _source_display_name(other_ctx, config, target_id="rlO1iMV7") == "Hero Mode"


def test_verified_reply_source_observer_copy_uses_compact_monologue_notice():
    import usr.plugins.a0_superordinates.tools.superordinate_message as msg

    captured = []
    contexts = {
        "replyer": SimpleNamespace(id="replyer"),
        "source": SimpleNamespace(id="source"),
    }

    original_get = msg.AgentContext.get
    original_display = msg._display_inbound_message
    original_add = msg._add_context_message_without_prompt
    original_path = msg._hierarchy_path_between
    try:
        msg.AgentContext.get = staticmethod(lambda ctxid: contexts.get(ctxid))
        msg._hierarchy_path_between = lambda source_id, target_id: []

        def fake_display(ctx, envelope, source=" (from superordinate_message)"):
            captured.append((ctx.id, envelope))
            return f"msg-{ctx.id}"

        msg._display_inbound_message = fake_display
        msg._add_context_message_without_prompt = lambda ctx, envelope, message_id: True

        informed = msg._inform_hierarchy_intermediates(
            "replyer",
            "Replyer",
            "source",
            "Source",
            "Full monologue details that should not be duplicated locally.",
            "Info",
            include_intermediaries=True,
            source_observer_message="Monologue details sent.",
        )
    finally:
        msg.AgentContext.get = original_get
        msg._display_inbound_message = original_display
        msg._add_context_message_without_prompt = original_add
        msg._hierarchy_path_between = original_path

    assert informed == ["replyer"]
    assert captured == [("replyer", '{To: "Source" (source)}\n\nMonologue details sent.')]
    assert "Full monologue details" not in captured[0][1]


def test_verified_reply_target_display_override_preserves_handler_name_in_to_envelope():
    import usr.plugins.a0_superordinates.tools.superordinate_message as msg

    envelope = msg._source_inform_envelope(
        "neurocis",
        "rlO1iMV7",
        "Monologue details sent.",
        "Info",
    )

    assert envelope == '{To: "neurocis" (rlO1iMV7)}\n\nMonologue details sent.'


def test_process_chain_end_passes_original_from_name_as_target_display_override():
    import sys
    import types

    # Isolate-import the process_chain_end hook with lightweight stubs so we can
    # assert the reverse-route tool arguments without loading the full runtime.
    module_name = "usr.plugins.a0_superordinates.extensions.python.process_chain_end._50_route_superordinate_reply"
    sys.modules.pop(module_name, None)

    extension_mod = types.ModuleType("helpers.extension")
    agent_mod = sys.modules.get("agent") or types.ModuleType("agent")
    super_msg_mod_name = "usr.plugins.a0_superordinates.tools.superordinate_message"
    super_msg_mod = sys.modules[super_msg_mod_name]

    class Extension:
        def __init__(self, agent=None, *args, **kwargs):
            self.agent = agent

    class LoopData:
        pass

    calls = []

    class FakeSuperordinateMessage:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def execute(self, **kwargs):
            calls.append(kwargs)
            return None

    original_superordinate_message = super_msg_mod.SuperordinateMessage
    extension_mod.Extension = Extension
    agent_mod.AgentContext = getattr(super_msg_mod, "AgentContext")
    agent_mod.LoopData = LoopData
    super_msg_mod.SuperordinateMessage = FakeSuperordinateMessage
    sys.modules["helpers.extension"] = extension_mod
    sys.modules["agent"] = agent_mod

    try:
        import importlib
        hook = importlib.import_module(module_name)

        class FakeTargetContext:
            id = "rlO1iMV7"

        class FakeAgentContext:
            @staticmethod
            def get(ctxid):
                return FakeTargetContext() if ctxid == "rlO1iMV7" else None

        hook.AgentContext = FakeAgentContext

        context = SimpleNamespace(
            id="replyer",
            data={
                "_superordinate_pending_reply_routes": {
                    "msg-1": {
                        "from_name": "neurocis",
                        "from_id": "rlO1iMV7",
                        "reply": "Info",
                    }
                },
                "_superordinate_last_response": {
                    "user_message_id": "msg-1",
                    "text": "Full reply body",
                },
            },
            log=SimpleNamespace(log=lambda **kwargs: None),
        )
        fake_agent = SimpleNamespace(
            context=context,
            last_user_message=SimpleNamespace(id="msg-1"),
            loop_data=SimpleNamespace(last_response=""),
        )
        ext = hook.RouteSuperordinateReplyOnProcessEnd(agent=fake_agent)

        import asyncio
        asyncio.run(ext.execute(loop_data=LoopData()))
    finally:
        super_msg_mod.SuperordinateMessage = original_superordinate_message

    assert calls
    assert calls[0]["_target_display_name_override"] == "neurocis"
    assert calls[0]["superordinate_id"] == "rlO1iMV7"
    assert calls[0]["_verified_superordinate_reply"] is True
