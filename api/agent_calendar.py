"""API endpoint for per-agent calendar files and CalDAV accounts."""

from __future__ import annotations

# Import Agent Zero's framework API helper.  This plugin also has a local
# ``helpers/`` package, and when the plugin directory is current/early on
# ``sys.path`` it can shadow /a0/helpers.  If that happens during plugin API
# discovery, the handler import fails before process() can return JSON and the
# browser sees Flask's generic HTML 500 page.
#
# Temporarily isolate the framework import so top-level ``helpers`` resolves to
# Agent Zero's framework package.  The plugin's own helpers are imported below
# through the fully-qualified ``usr.plugins.a0_superordinates.helpers`` package,
# so removing plugin-root entries during this one import is safe.
import os
import sys
from pathlib import Path

_FRAMEWORK_ROOT = Path("/a0").resolve()
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_HELPERS = (_PLUGIN_ROOT / "helpers").resolve()
_ORIGINAL_SYS_PATH = list(sys.path)


def _path_resolves_to_plugin_root(entry: str) -> bool:
    try:
        candidate = Path(entry or os.getcwd()).resolve()
    except Exception:
        return False
    return candidate == _PLUGIN_ROOT


def _module_file_is_plugin_helper(module: object) -> bool:
    try:
        module_file = Path(str(getattr(module, "__file__", "") or "/")).resolve()
        return module_file == _PLUGIN_HELPERS / "__init__.py" or module_file.is_relative_to(_PLUGIN_HELPERS)
    except Exception:
        return False


try:
    for _name in list(sys.modules):
        if _name == "helpers" or _name.startswith("helpers."):
            if _module_file_is_plugin_helper(sys.modules[_name]):
                sys.modules.pop(_name, None)

    _framework_root_str = str(_FRAMEWORK_ROOT)
    sys.path = [
        p for p in sys.path
        if p != _framework_root_str and not _path_resolves_to_plugin_root(p)
    ]
    sys.path.insert(0, _framework_root_str)

    from helpers.api import ApiHandler, Request
finally:
    sys.path = _ORIGINAL_SYS_PATH

from usr.plugins.a0_superordinates.helpers.agent_calendar import (
    create_local_calendar,
    delete_calendar_event,
    delete_calendar_todo,
    delete_local_calendar,
    list_calendar_stack,
    read_calendar_file,
    save_calendar_file,
    upsert_calendar_event,
    upsert_calendar_todo,
)
from usr.plugins.a0_superordinates.helpers.agent_caldav import (
    add_caldav_account,
    get_caldav_account,
    delete_caldav_event,
    get_caldav_event,
    list_caldav_accounts,
    list_caldav_collections,
    list_caldav_events,
    remove_caldav_account,
    select_caldav_collection,
    test_caldav_account,
    upsert_caldav_event,
)


class AgentCalendar(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "list").strip().lower()
        ctxid = str(input.get("ctxid") or input.get("context_id") or "").strip()

        try:
            # ----- Calendar stack listing -----
            if action == "list":
                return list_calendar_stack(ctxid)

            # ----- Local .ics file lifecycle -----
            if action == "create_ics":
                created = create_local_calendar(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or "local.ics"),
                    title=input.get("title"),
                    overwrite=bool(input.get("overwrite", False)),
                )
                payload = list_calendar_stack(ctxid)
                payload["created"] = created
                return payload

            if action == "read_ics":
                return read_calendar_file(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                )

            if action in {"delete_ics", "delete_local_ics", "delete_calendar"}:
                return delete_local_calendar(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                )

            if action == "save_ics":
                return save_calendar_file(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                    content=str(input.get("content") or ""),
                )

            # ----- Local VEVENT/VTODO editing -----
            if action == "upsert_event":
                return upsert_calendar_event(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                    event=input.get("event") if isinstance(input.get("event"), dict) else {},
                    old_uid=input.get("old_uid"),
                )

            if action == "delete_event":
                return delete_calendar_event(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                    uid=str(input.get("uid") or ""),
                )

            if action == "upsert_todo":
                return upsert_calendar_todo(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                    todo=input.get("todo") if isinstance(input.get("todo"), dict) else (
                        input.get("event") if isinstance(input.get("event"), dict) else {}
                    ),
                    old_uid=input.get("old_uid"),
                )

            if action == "delete_todo":
                return delete_calendar_todo(
                    ctxid=ctxid,
                    filename=str(input.get("filename") or input.get("relative_path") or ""),
                    uid=str(input.get("uid") or ""),
                )

            # ----- CalDAV account lifecycle -----
            if action in {"get_caldav_account", "list_caldav_accounts"}:
                payload = list_calendar_stack(ctxid)
                account = get_caldav_account(ctxid)
                payload["caldav_account"] = account
                payload["caldav_accounts"] = [account] if account else []
                return payload

            if action in {"set_caldav_account", "add_caldav_account"}:
                account = add_caldav_account(
                    ctxid=ctxid,
                    label=str(input.get("label") or ""),
                    server_url=str(input.get("server_url") or input.get("url") or ""),
                    username=str(input.get("username") or ""),
                    password=str(input.get("password") or ""),
                    webui_calendar_url=str(input.get("webui_calendar_url") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["caldav_account"] = account
                payload["caldav_accounts"] = [account] if account else []
                payload["added"] = account
                payload["set"] = account
                return payload

            if action == "remove_caldav_account":
                removed = remove_caldav_account(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["caldav_account"] = None
                payload["caldav_accounts"] = []
                payload["removed"] = removed
                return payload

            if action == "test_caldav_account":
                result = test_caldav_account(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["test"] = result
                return payload

            if action == "list_caldav_collections":
                result = list_caldav_collections(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["collections"] = result.get("collections", [])
                payload["test"] = result
                return payload

            if action == "select_caldav_collection":
                selected = select_caldav_collection(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                    collection_url=str(input.get("collection_url") or input.get("url") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["selected"] = selected
                return payload

            # ----- CalDAV event CRUD -----
            if action == "list_caldav_events":
                return list_caldav_events(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                )

            if action == "get_caldav_event":
                return get_caldav_event(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                    href=str(input.get("href") or ""),
                )

            if action == "upsert_caldav_event":
                payload = {}
                if isinstance(input.get("event"), dict):
                    payload["event"] = input.get("event")
                if isinstance(input.get("todo"), dict):
                    payload["todo"] = input.get("todo")
                if isinstance(input.get("ics"), str):
                    payload["ics"] = input.get("ics")
                return upsert_caldav_event(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                    payload=payload,
                    href=str(input.get("href") or ""),
                )

            if action == "delete_caldav_event":
                return delete_caldav_event(
                    ctxid=ctxid,
                    account_id=str(input.get("account_id") or input.get("id") or ""),
                    href=str(input.get("href") or ""),
                )

            return {"ok": False, "error": f"unknown action: {action}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
