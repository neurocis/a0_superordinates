"""CalDAV client helpers for per-agent CalDAV accounts.

This module replaces the old ICS-subscription logic.  Each Agent context can
register one CalDAV account, discover its calendar collections, select an
active collection, and read/write events on it via PUT/DELETE.

The singleton account is persisted in ``/a0/usr/chats/<ctxid>/calendar/caldav.json``.
Passwords are stored in plaintext alongside the account record because Agent
Zero does not yet expose a per-context secret store; rotate or remove the
account if this is a concern.  Discovery and event operations use the ``caldav`` PyPI
library, which builds on ``requests``/``niquests``, ``lxml``, ``vobject`` and
``icalendar``.

Provider quirks (kept as caveats, not enforced here):

- **Google**: usually requires app passwords or OAuth; plain Google account
  passwords typically fail.
- **iCloud**: requires app-specific passwords; the server URL is
  ``https://caldav.icloud.com``.
- **Nextcloud / Radicale / SOGo**: usually work with the base URL; Nextcloud's
  canonical entry point is ``https://<host>/remote.php/dav``.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("agent_caldav")

CALDAV_FILENAME = "caldav.json"
REGISTRY_VERSION = 1


# ---------------------------------------------------------------------------
# Late imports to avoid circular import with agent_calendar.
# ---------------------------------------------------------------------------

def _calendar_helpers():
    from . import agent_calendar  # type: ignore  # late import
    return agent_calendar


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def caldav_path(ctxid: str, create: bool = True) -> Path:
    return _calendar_helpers().context_calendar_dir(ctxid, create=create) / CALDAV_FILENAME


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "account": None}


def _normalize_account(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    if not entry.get("id") or not entry.get("server_url"):
        return None
    entry.setdefault("label", entry.get("server_url") or "")
    entry.setdefault("username", "")
    entry.setdefault("password", "")
    entry.setdefault("kind", "caldav")
    entry["webui_calendar_url"] = normalize_webui_calendar_url(
        entry.get("webui_calendar_url") or "",
        reject_unsafe=False,
    )
    entry.setdefault("collections", [])
    entry.setdefault("selected_collection_url", "")
    entry.setdefault("selected_collection_name", "")
    entry.setdefault("status", "unverified")
    entry.setdefault("last_error", "")
    entry.setdefault("last_verified", "")
    return entry


def _first_legacy_account(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first valid account from old multi-account data.

    Requirement: per agent/context there is exactly zero or one CalDAV account.
    Older list-shaped data is tolerated defensively and normalized to the first
    valid account so stale/malformed registries do not crash the UI/API.
    """
    direct = _normalize_account(data.get("account") if isinstance(data, dict) else None)
    if direct is not None:
        return direct
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if isinstance(accounts, list):
        for entry in accounts:
            normalized = _normalize_account(entry)
            if normalized is not None:
                return normalized
    return None


def load_caldav_registry(ctxid: str, create: bool = False) -> dict[str, Any]:
    path = caldav_path(ctxid, create=create)
    if not path.exists():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "version": int(data.get("version") or REGISTRY_VERSION),
        "account": _first_legacy_account(data),
    }


def save_caldav_registry(ctxid: str, registry: dict[str, Any]) -> None:
    path = caldav_path(ctxid, create=True)
    singleton = {
        "version": int(registry.get("version") or REGISTRY_VERSION),
        "account": _normalize_account(registry.get("account")),
    }
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
        json.dump(singleton, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def public_account(account: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return an account dict with the password stripped."""
    if not isinstance(account, dict):
        return None
    public = {k: v for k, v in account.items() if k != "password"}
    public["has_password"] = bool(account.get("password"))
    return public


def get_caldav_account(ctxid: str) -> dict[str, Any] | None:
    return public_account(load_caldav_registry(ctxid).get("account"))


def list_caldav_accounts(ctxid: str) -> list[dict[str, Any]]:
    """Backward-compatible one-item list view for older UI/API callers."""
    account = get_caldav_account(ctxid)
    return [account] if account else []


def caldav_account_entry(ctxid: str) -> dict[str, Any] | None:
    """Internal-use raw entry (with password) for indicator/connection logic."""
    try:
        return load_caldav_registry(ctxid, create=False).get("account")
    except Exception:
        return None


def caldav_account_entries(ctxid: str) -> list[dict[str, Any]]:
    """Backward-compatible raw one-item list for older internal callers."""
    account = caldav_account_entry(ctxid)
    return [account] if account else []


def has_active_caldav_source(ctxid: str) -> bool:
    """True if the singleton account has a selected collection URL."""
    acc = caldav_account_entry(ctxid)
    return bool(isinstance(acc, dict) and str(acc.get("selected_collection_url") or "").strip())


def _find_account(ctxid: str, account_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = load_caldav_registry(ctxid, create=False)
    account = registry.get("account")
    if not isinstance(account, dict):
        raise ValueError("no CalDAV account configured")
    clean_id = str(account_id or "").strip()
    # The singleton API does not require an id.  If an old caller supplies one,
    # tolerate it only when it matches the configured singleton.
    if clean_id and clean_id != str(account.get("id") or ""):
        raise ValueError(f"caldav account not found: {clean_id}")
    return registry, account


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def normalize_server_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        raise ValueError("server URL is required")
    if not (clean.startswith("http://") or clean.startswith("https://")):
        clean = "https://" + clean
    parsed = urlparse(clean)
    if not parsed.netloc:
        raise ValueError("server URL must include a host")
    return clean


def normalize_webui_calendar_url(url: str, *, reject_unsafe: bool = True) -> str:
    """Normalize the optional browser-facing calendar URL.

    Blank is allowed.  Nonblank values must be http(s); unsafe schemes such as
    javascript:, data:, file:, etc. are rejected for user-entered values and
    stripped when defensively reading old/malformed persisted data.
    """
    clean = str(url or "").strip()
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        if reject_unsafe:
            raise ValueError("WebUI Calendar URL must be http:// or https://")
        return ""
    return clean


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------

def add_caldav_account(
    ctxid: str,
    label: str,
    server_url: str,
    username: str,
    password: str,
    webui_calendar_url: str = "",
) -> dict[str, Any] | None:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    clean_url = normalize_server_url(server_url)
    clean_webui_url = normalize_webui_calendar_url(webui_calendar_url)
    clean_label = (str(label or "").strip()) or clean_url
    clean_username = str(username or "").strip()
    clean_password = str(password or "")
    if not clean_username:
        raise ValueError("username is required")
    if not clean_password:
        raise ValueError("password is required")

    previous = caldav_account_entry(ctxid) or {}
    registry = load_caldav_registry(ctxid, create=True)
    entry = _normalize_account({
        "id": str(previous.get("id") or uuid.uuid4().hex[:12]),
        "label": clean_label,
        "server_url": clean_url,
        "username": clean_username,
        "password": clean_password,
        "webui_calendar_url": clean_webui_url,
        "kind": "caldav",
        "created": previous.get("created") or cal.iso_now(),
        "updated": cal.iso_now(),
        # Replacing the account clears stale discovery/selection from the old
        # provider unless the user re-tests and selects a collection again.
        "collections": [],
        "selected_collection_url": "",
        "selected_collection_name": "",
        "status": "unverified",
        "last_error": "",
        "last_verified": "",
    })
    assert entry is not None
    registry["account"] = entry
    save_caldav_registry(ctxid, registry)
    cal.persist_calendar_indicator(ctxid)
    return public_account(entry)


def set_caldav_account(
    ctxid: str,
    label: str,
    server_url: str,
    username: str,
    password: str,
    webui_calendar_url: str = "",
) -> dict[str, Any] | None:
    """Create or replace the singleton CalDAV account for a context."""
    return add_caldav_account(ctxid, label, server_url, username, password, webui_calendar_url)


def remove_caldav_account(ctxid: str, account_id: str | None = None) -> bool:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    registry = load_caldav_registry(ctxid, create=False)
    account = registry.get("account")
    if not isinstance(account, dict):
        return False
    clean_id = str(account_id or "").strip()
    if clean_id and clean_id != str(account.get("id") or ""):
        return False
    registry["account"] = None
    save_caldav_registry(ctxid, registry)
    cal.persist_calendar_indicator(ctxid)
    return True


def _save_with_indicator(ctxid: str, registry: dict[str, Any]) -> None:
    cal = _calendar_helpers()
    save_caldav_registry(ctxid, registry)
    cal.persist_calendar_indicator(ctxid)


# ---------------------------------------------------------------------------
# Network operations
# ---------------------------------------------------------------------------

def _connect(account: dict[str, Any]):
    import caldav  # local import keeps module load light when unused
    return caldav.DAVClient(
        url=account["server_url"],
        username=account.get("username") or "",
        password=account.get("password") or "",
    )


def _calendar_object(account: dict[str, Any]):
    selected = str(account.get("selected_collection_url") or "").strip()
    if not selected:
        raise ValueError("no CalDAV collection selected for this account")
    client = _connect(account)
    return client.calendar(url=selected)


def _serialize_collections(calendars) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cal in calendars:
        try:
            url = str(getattr(cal, "url", "") or "")
            display = ""
            if hasattr(cal, "get_display_name"):
                try:
                    display = str(cal.get_display_name() or "") or ""
                except Exception:
                    display = ""
            name = str(getattr(cal, "name", "") or "")
            out.append({
                "url": url,
                "name": name or display or url,
                "display_name": display or name or url,
            })
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("caldav: skipping collection due to error: %s", exc)
    return out


def test_caldav_account(ctxid: str, account_id: str | None = None) -> dict[str, Any]:
    """Verify credentials and discover calendar collections."""
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    registry, account = _find_account(ctxid, account_id)
    try:
        client = _connect(account)
        principal = client.principal()
        calendars = principal.calendars()
        collections = _serialize_collections(calendars)
        account["collections"] = collections
        account["status"] = "ok"
        account["last_error"] = ""
        account["last_verified"] = cal.iso_now()
        if not account.get("selected_collection_url") and len(collections) == 1:
            account["selected_collection_url"] = collections[0]["url"]
            account["selected_collection_name"] = collections[0]["display_name"]
        _save_with_indicator(ctxid, registry)
        return {
            "ok": True,
            "account": public_account(account),
            "collections": collections,
        }
    except Exception as exc:
        account["status"] = "error"
        account["last_error"] = str(exc)
        save_caldav_registry(ctxid, registry)
        return {"ok": False, "error": str(exc), "account": public_account(account)}


def list_caldav_collections(ctxid: str, account_id: str | None = None) -> dict[str, Any]:
    return test_caldav_account(ctxid, account_id)


def select_caldav_collection(ctxid: str, account_id: str | None = None, collection_url: str = "") -> dict[str, Any]:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    registry, account = _find_account(ctxid, account_id)
    clean_url = str(collection_url or "").strip()
    if not clean_url:
        raise ValueError("collection_url is required")
    matched = None
    for col in account.get("collections") or []:
        if str(col.get("url") or "") == clean_url:
            matched = col
            break
    if matched is None:
        matched = {"url": clean_url, "name": clean_url, "display_name": clean_url}
    account["selected_collection_url"] = clean_url
    account["selected_collection_name"] = matched.get("display_name") or matched.get("name") or clean_url
    _save_with_indicator(ctxid, registry)
    return {"ok": True, "account": public_account(account)}


# ---------------------------------------------------------------------------
# Event listing / CRUD
# ---------------------------------------------------------------------------

def _summarize_event(ev) -> dict[str, Any]:
    summary = ""
    dtstart = ""
    dtend = ""
    uid = ""
    rrule = ""
    component_kind = "event"
    try:
        ical = ev.icalendar_instance
        for sub in getattr(ical, "subcomponents", []) or []:
            name = getattr(sub, "name", "") or ""
            if name in ("VEVENT", "VTODO"):
                component_kind = "event" if name == "VEVENT" else "todo"
                summary = str(sub.get("summary") or "") or summary
                uid = str(sub.get("uid") or "") or uid
                ds = sub.get("dtstart")
                de = sub.get("dtend") or sub.get("due")
                rrule_val = sub.get("rrule")
                try:
                    if ds is not None:
                        dtstart = ds.to_ical().decode()
                except Exception:
                    dtstart = str(ds) if ds is not None else ""
                try:
                    if de is not None:
                        dtend = de.to_ical().decode()
                except Exception:
                    dtend = str(de) if de is not None else ""
                try:
                    if rrule_val is not None:
                        rrule = rrule_val.to_ical().decode()
                except Exception:
                    rrule = str(rrule_val) if rrule_val is not None else ""
                break
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("caldav: failed to summarize event: %s", exc)
    return {
        "uid": uid,
        "summary": summary,
        "dtstart": dtstart,
        "dtend": dtend,
        "rrule": rrule,
        "is_recurring": bool(rrule),
        "component_kind": component_kind,
        "href": str(getattr(ev, "url", "") or ""),
        "etag": str(getattr(ev, "etag", "") or ""),
    }


def list_caldav_events(ctxid: str, account_id: str | None = None) -> dict[str, Any]:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    registry, account = _find_account(ctxid, account_id)
    try:
        cal_obj = _calendar_object(account)
        events = []
        try:
            iterable = cal_obj.events()
        except Exception:
            iterable = []
        for ev in iterable:
            events.append(_summarize_event(ev))
        try:
            for todo in cal_obj.todos(include_completed=True):
                events.append(_summarize_event(todo))
        except Exception:
            pass
        account["status"] = "ok"
        account["last_error"] = ""
        account["last_verified"] = cal.iso_now()
        save_caldav_registry(ctxid, registry)
        return {
            "ok": True,
            "events": events,
            "account": public_account(account),
        }
    except Exception as exc:
        account["status"] = "error"
        account["last_error"] = str(exc)
        save_caldav_registry(ctxid, registry)
        return {"ok": False, "error": str(exc), "account": public_account(account)}


def get_caldav_event(ctxid: str, account_id: str | None = None, href: str = "") -> dict[str, Any]:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    _registry, account = _find_account(ctxid, account_id)
    clean_href = str(href or "").strip()
    if not clean_href:
        raise ValueError("href is required")
    cal_obj = _calendar_object(account)
    ev = cal_obj.event_by_url(clean_href)
    return {
        "ok": True,
        "href": str(getattr(ev, "url", "") or clean_href),
        "etag": str(getattr(ev, "etag", "") or ""),
        "ics": str(getattr(ev, "data", "") or ""),
    }


def _wrap_in_vcalendar(component_block: str) -> str:
    body = (component_block or "").strip()
    if not body:
        raise ValueError("empty component block")
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Agent Zero//Superordinates Calendar//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        + body.replace("\r\n", "\n").replace("\n", "\r\n")
        + "\r\nEND:VCALENDAR\r\n"
    )


def _build_ics_from_payload(payload: dict[str, Any]) -> str:
    cal = _calendar_helpers()
    raw = str(payload.get("ics") or "").strip()
    if raw:
        return raw if raw.upper().startswith("BEGIN:VCALENDAR") else _wrap_in_vcalendar(raw)

    event = payload.get("event") if isinstance(payload.get("event"), dict) else None
    todo = payload.get("todo") if isinstance(payload.get("todo"), dict) else None
    if event:
        block, _uid = cal.build_vevent(event, existing_lines=None)
        return _wrap_in_vcalendar(block)
    if todo:
        block, _uid = cal.build_vtodo(todo, existing_lines=None)
        return _wrap_in_vcalendar(block)
    raise ValueError("upsert payload must include one of: ics, event, todo")


def upsert_caldav_event(
    ctxid: str,
    account_id: str | None = None,
    payload: dict[str, Any] | None = None,
    href: str | None = None,
) -> dict[str, Any]:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    _registry, account = _find_account(ctxid, account_id)
    payload = payload or {}
    ics_text = _build_ics_from_payload(payload)
    cal_obj = _calendar_object(account)
    clean_href = str(href or "").strip()
    if clean_href:
        try:
            existing = cal_obj.event_by_url(clean_href)
            existing.data = ics_text
            existing.save()
            return {
                "ok": True,
                "href": str(getattr(existing, "url", "") or clean_href),
                "etag": str(getattr(existing, "etag", "") or ""),
                "created": False,
            }
        except Exception as exc:
            log.warning("caldav: update via href failed (%s); falling back to create", exc)
    ev = cal_obj.save_event(ics_text)
    return {
        "ok": True,
        "href": str(getattr(ev, "url", "") or ""),
        "etag": str(getattr(ev, "etag", "") or ""),
        "created": True,
    }


def delete_caldav_event(ctxid: str, account_id: str | None = None, href: str = "") -> dict[str, Any]:
    cal = _calendar_helpers()
    cal.validate_context_id(ctxid)
    _registry, account = _find_account(ctxid, account_id)
    clean_href = str(href or "").strip()
    if not clean_href:
        raise ValueError("href is required")
    cal_obj = _calendar_object(account)
    ev = cal_obj.event_by_url(clean_href)
    ev.delete()
    return {"ok": True, "href": clean_href}
