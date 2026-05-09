"""API endpoint for WebUI stores to read a0_superordinates plugin config."""

from helpers.api import ApiHandler, Request, Response


DEFAULT_CLOSED_ENTITIES_FOLDER_NAME = "Closed Entities"
DEFAULT_DISPLAY_INHERITANCE_INDICATOR = True
DEFAULT_DISPLAY_CALENDAR_INDICATOR = True
DEFAULT_DISPLAY_CALENDAR_PROMPTS_INDICATOR = True
DEFAULT_HERO_MODE_DESIGNATED_HERO = "Disabled"


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
        hero_mode_designated_hero = _normalize_hero_mode_designated_hero(
            config.get("hero_mode_designated_hero"),
        )

        normalized_config = {
            **config,
            "closed_entities_folder_name": closed_name,
            "display_inheritance_indicator": display_inheritance_indicator,
            "display_calendar_indicator": display_calendar_indicator,
            "display_calendar_prompts_indicator": display_calendar_prompts_indicator,
            "hero_mode_designated_hero": hero_mode_designated_hero,
        }

        return {
            "ok": True,
            "closed_entities_folder_name": closed_name,
            "display_inheritance_indicator": display_inheritance_indicator,
            "display_calendar_indicator": display_calendar_indicator,
            "display_calendar_prompts_indicator": display_calendar_prompts_indicator,
            "hero_mode_designated_hero": hero_mode_designated_hero,
            "config": normalized_config,
        }
