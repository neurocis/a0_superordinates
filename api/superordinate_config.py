"""API endpoint for WebUI stores to read a0_superordinates plugin config."""

from helpers.api import ApiHandler, Request, Response


DEFAULT_CLOSED_ENTITIES_FOLDER_NAME = "Closed Entities"
DEFAULT_DISPLAY_INHERITANCE_INDICATOR = True
DEFAULT_DISPLAY_CALENDAR_INDICATOR = True
DEFAULT_DISPLAY_CALENDAR_PROMPTS_INDICATOR = True
DEFAULT_DISPLAY_PROMPT_SPEECH_TOGGLE = True
DEFAULT_DISPLAY_CONTEXT_COUNTERS = True
DEFAULT_HERO_MODE_DESIGNATED_HERO = "Disabled"
DEFAULT_HERO_HANDLER_NAME = ""
DEFAULT_HERO_MODE_REPLIES_TO_HERO_INFORMATIONAL = True
DEFAULT_KEEP_EVERYBODY_IN_THE_LOOP = True
DEFAULT_VISIBLE_MESSAGE_BODY_TRUNCATE_SIZE = 1000


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", ""}:
            return False
    return default


def _parse_int_nonneg(value: object, default: int) -> int:
    """Return a non-negative int from value, falling back to default."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else default


def _normalize_hero_handler_name(value: object) -> str:
    text = str(value or DEFAULT_HERO_HANDLER_NAME).strip()
    # Keep this as display text only; do not use it for routing identity.
    return " ".join(text.split())[:80]


def _normalize_hero_mode_designated_hero(value: object) -> str:
    text = str(value or DEFAULT_HERO_MODE_DESIGNATED_HERO).strip()
    if not text or text.lower() == "disabled":
        return DEFAULT_HERO_MODE_DESIGNATED_HERO
    return text


class SuperordinateConfig(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from helpers import plugins
            try:
                config = plugins.get_plugin_config("a0_superordinates") or {}
            except TypeError:
                config = plugins.get_plugin_config("a0_superordinates", agent=None) or {}
        except Exception:
            config = {}

        if not isinstance(config, dict):
            config = {}

        closed_name = str(
            config.get("closed_entities_folder_name")
            or DEFAULT_CLOSED_ENTITIES_FOLDER_NAME
        ).strip() or DEFAULT_CLOSED_ENTITIES_FOLDER_NAME

        display_inheritance_indicator = _parse_bool(
            config.get("display_inheritance_indicator"),
            DEFAULT_DISPLAY_INHERITANCE_INDICATOR,
        )
        display_calendar_indicator = _parse_bool(
            config.get("display_calendar_indicator"),
            DEFAULT_DISPLAY_CALENDAR_INDICATOR,
        )
        display_calendar_prompts_indicator = _parse_bool(
            config.get("display_calendar_prompts_indicator"),
            DEFAULT_DISPLAY_CALENDAR_PROMPTS_INDICATOR,
        )
        display_prompt_speech_toggle = _parse_bool(
            config.get("display_prompt_speech_toggle"),
            DEFAULT_DISPLAY_PROMPT_SPEECH_TOGGLE,
        )
        display_context_counters = _parse_bool(
            config.get("display_context_counters"),
            DEFAULT_DISPLAY_CONTEXT_COUNTERS,
        )
        hero_handler_name = _normalize_hero_handler_name(
            config.get("hero_handler_name"),
        )
        hero_mode_designated_hero = _normalize_hero_mode_designated_hero(
            config.get("hero_mode_designated_hero"),
        )
        hero_mode_replies_to_hero_informational = _parse_bool(
            config.get("hero_mode_replies_to_hero_informational"),
            DEFAULT_HERO_MODE_REPLIES_TO_HERO_INFORMATIONAL,
        )
        keep_everybody_in_the_loop = _parse_bool(
            config.get("keep_everybody_in_the_loop"),
            DEFAULT_KEEP_EVERYBODY_IN_THE_LOOP,
        )
        visible_message_body_truncate_size = _parse_int_nonneg(
            config.get("visible_message_body_truncate_size"),
            DEFAULT_VISIBLE_MESSAGE_BODY_TRUNCATE_SIZE,
        )

        normalized_config = {
            **config,
            "closed_entities_folder_name": closed_name,
            "display_inheritance_indicator": display_inheritance_indicator,
            "display_calendar_indicator": display_calendar_indicator,
            "display_calendar_prompts_indicator": display_calendar_prompts_indicator,
            "display_prompt_speech_toggle": display_prompt_speech_toggle,
            "display_context_counters": display_context_counters,
            "hero_handler_name": hero_handler_name,
            "hero_mode_designated_hero": hero_mode_designated_hero,
            "hero_mode_replies_to_hero_informational": hero_mode_replies_to_hero_informational,
            "keep_everybody_in_the_loop": keep_everybody_in_the_loop,
            "visible_message_body_truncate_size": visible_message_body_truncate_size,
        }

        return {
            "ok": True,
            "closed_entities_folder_name": closed_name,
            "display_inheritance_indicator": display_inheritance_indicator,
            "display_calendar_indicator": display_calendar_indicator,
            "display_calendar_prompts_indicator": display_calendar_prompts_indicator,
            "display_prompt_speech_toggle": display_prompt_speech_toggle,
            "display_context_counters": display_context_counters,
            "hero_handler_name": hero_handler_name,
            "hero_mode_designated_hero": hero_mode_designated_hero,
            "hero_mode_replies_to_hero_informational": hero_mode_replies_to_hero_informational,
            "keep_everybody_in_the_loop": keep_everybody_in_the_loop,
            "visible_message_body_truncate_size": visible_message_body_truncate_size,
            "config": normalized_config,
        }
