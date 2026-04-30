"""API endpoint for WebUI stores to read a0_superordinates plugin config."""

from helpers.api import ApiHandler, Request, Response


DEFAULT_CLOSED_ENTITIES_FOLDER_NAME = "Closed Entities"


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

        return {
            "ok": True,
            "closed_entities_folder_name": closed_name,
            "config": {
                **config,
                "closed_entities_folder_name": closed_name,
            },
        }
