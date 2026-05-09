"""Return ROOT superordinates eligible for Hero Mode selection.

Hero Mode is keyed by immutable ContextID.  This endpoint avoids relying on
settings-modal frontend store timing by deriving ROOT candidates server-side
from chat metadata and returning stable {id, name, label} options.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from helpers.api import ApiHandler, Request, Response


CHATS_DIR = Path("/a0/usr/chats")
DEFAULT_CLOSED_NAMES = {"closed entities", "closed entries"}


def _norm(value: object) -> str:
    return str(value or "").strip()


def _norm_name(value: object) -> str:
    return _norm(value).lower()


def _read_plugin_closed_name() -> str:
    try:
        from helpers import plugins
        try:
            config = plugins.get_plugin_config("a0_superordinates") or {}
        except TypeError:
            config = plugins.get_plugin_config("a0_superordinates", agent=None) or {}
        if isinstance(config, dict):
            return _norm(config.get("closed_entities_folder_name")) or "Closed Entities"
    except Exception:
        pass
    return "Closed Entities"


def _load_disk_chats() -> dict[str, dict]:
    chats: dict[str, dict] = {}
    if not CHATS_DIR.is_dir():
        return chats

    for entry in os.listdir(CHATS_DIR):
        if entry.startswith("_"):
            continue
        chat_file = CHATS_DIR / entry / "chat.json"
        if not chat_file.is_file():
            continue
        try:
            with chat_file.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                continue
            data = raw.get("data", {}) or {}
            chats[entry] = {
                "id": entry,
                "name": _norm(raw.get("name")) or f"Chat #{raw.get('no', '?')}",
                "no": raw.get("no", 0),
                "data": data if isinstance(data, dict) else {},
            }
        except Exception:
            continue
    return chats


def _merge_memory_chats(chats: dict[str, dict]) -> None:
    try:
        from agent import AgentContext
        for ctx in AgentContext.all():
            if not getattr(ctx, "id", ""):
                continue
            ctxid = ctx.id
            data = ctx.data if isinstance(getattr(ctx, "data", None), dict) else {}
            existing = chats.get(ctxid, {})
            chats[ctxid] = {
                "id": ctxid,
                "name": _norm(getattr(ctx, "name", "")) or existing.get("name") or ctxid,
                "no": getattr(ctx, "no", existing.get("no", 0)),
                "data": data or existing.get("data", {}),
            }
    except Exception:
        # Disk data is sufficient for the settings picker if memory is unavailable.
        return


def _load_root_order() -> list[str]:
    root_order_file = CHATS_DIR / "_sup_root_order.dat"
    if not root_order_file.is_file():
        return []
    try:
        with root_order_file.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        if isinstance(parsed, list):
            return [_norm(item) for item in parsed if _norm(item)]
    except Exception:
        pass
    return []


class SuperordinateHeroRoots(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        chats = _load_disk_chats()
        _merge_memory_chats(chats)

        closed_names = set(DEFAULT_CLOSED_NAMES)
        configured_closed_name = _read_plugin_closed_name()
        if configured_closed_name:
            closed_names.add(_norm_name(configured_closed_name))

        # ROOT means no sup_parent, or parent does not exist in the known chats.
        root_ids: list[str] = []
        for ctxid, chat in chats.items():
            data = chat.get("data", {}) if isinstance(chat.get("data"), dict) else {}
            parent = _norm(data.get("sup_parent")) or None
            if parent is None or parent not in chats:
                root_ids.append(ctxid)

        saved_order = _load_root_order()
        ordered: list[str] = []
        for ctxid in saved_order:
            if ctxid in root_ids and ctxid not in ordered:
                ordered.append(ctxid)
        for ctxid in sorted(root_ids, key=lambda cid: (_norm_name(chats[cid].get("name")), cid)):
            if ctxid not in ordered:
                ordered.append(ctxid)

        roots: list[dict] = []
        for ctxid in ordered:
            chat = chats.get(ctxid, {})
            name = _norm(chat.get("name")) or ctxid
            if _norm_name(name) in closed_names:
                continue
            roots.append({
                "id": ctxid,
                "ctxid": ctxid,
                "name": name,
                "label": f"{name} ({ctxid})",
            })

        return {
            "ok": True,
            "roots": roots,
            "options": roots,
            "closed_names": sorted(closed_names),
        }
