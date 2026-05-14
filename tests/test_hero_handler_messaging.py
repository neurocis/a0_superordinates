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
