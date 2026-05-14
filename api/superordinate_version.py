"""API endpoint returning the a0_superordinates plugin version from plugin.yaml.

Uses a lightweight regex read so the plugin does not depend on PyYAML being
installed in the host environment.
"""

from pathlib import Path
import re

from helpers.api import ApiHandler, Request, Response


_PLUGIN_YAML = Path(__file__).resolve().parent.parent / "plugin.yaml"
_VERSION_RE = re.compile(r"^version:\s*([^\s#]+)\s*$", re.MULTILINE)


def _read_version() -> str:
    try:
        text = _PLUGIN_YAML.read_text(encoding="utf-8")
    except Exception:
        return ""
    match = _VERSION_RE.search(text)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


class SuperordinateVersion(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        return {"ok": True, "version": _read_version()}
