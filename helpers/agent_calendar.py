"""Per-agent calendar storage helpers.

Phase 1 keeps this deliberately simple:

- each Agent ContextID gets a calendar folder under /a0/usr/chats/<ctxid>/calendar
- local writable calendars are plain *.ics files in that folder
- subscription links are stored in subscriptions.json in that same folder

This is an interchange/storage layer only; scheduler execution can consume it
later without coupling the Superordinates tree to scheduler internals.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

CHATS_ROOT = Path("/a0/usr/chats")
CALENDAR_DIRNAME = "calendar"
SUBSCRIPTIONS_FILENAME = "subscriptions.json"
REGISTRY_VERSION = 1

_CTXID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BAD_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_. -]+")
_ALLOWED_SUBSCRIPTION_PREFIXES = ("http://", "https://", "webcal://")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def ics_timestamp(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_context_id(ctxid: str) -> str:
    clean = str(ctxid or "").strip()
    if not clean:
        raise ValueError("ctxid is required")
    if not _CTXID_RE.match(clean):
        raise ValueError("invalid ctxid")
    if clean in {".", ".."}:
        raise ValueError("invalid ctxid")
    return clean


def context_calendar_dir(ctxid: str, create: bool = True) -> Path:
    clean = validate_context_id(ctxid)
    path = CHATS_ROOT / clean / CALENDAR_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def subscriptions_path(ctxid: str, create: bool = True) -> Path:
    return context_calendar_dir(ctxid, create=create) / SUBSCRIPTIONS_FILENAME


def sanitize_calendar_filename(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("calendar filename is required")
    value = Path(value).name
    value = _BAD_FILENAME_CHARS_RE.sub("_", value).strip(" ._")
    if not value:
        raise ValueError("calendar filename is required")
    if not value.lower().endswith(".ics"):
        value = f"{value}.ics"
    if value in {".ics", "subscriptions.json"}:
        raise ValueError("invalid calendar filename")
    return value


def escape_ics_text(value: str) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def fold_ics_line(line: str, limit: int = 75) -> list[str]:
    """Fold an iCalendar content line using a simple character limit.

    RFC 5545 defines the limit in octets. For this local builder's initial use,
    a conservative character fold is sufficient and keeps the implementation
    dependency-free.
    """
    if len(line) <= limit:
        return [line]
    folded = [line[:limit]]
    rest = line[limit:]
    continuation_limit = max(1, limit - 1)
    while rest:
        folded.append(" " + rest[:continuation_limit])
        rest = rest[continuation_limit:]
    return folded


def build_empty_calendar(name: str = "Agent Calendar") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Agent Zero//Agent Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(name or 'Agent Calendar')}",
        "END:VCALENDAR",
    ]
    output: list[str] = []
    for line in lines:
        output.extend(fold_ics_line(line))
    return "\r\n".join(output) + "\r\n"


def count_ics_components(path: Path) -> dict[str, int]:
    counts = {"events": 0, "todos": 0, "journals": 0}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return counts
    upper = text.upper()
    counts["events"] = upper.count("BEGIN:VEVENT")
    counts["todos"] = upper.count("BEGIN:VTODO")
    counts["journals"] = upper.count("BEGIN:VJOURNAL")
    return counts


def file_info(path: Path, base_dir: Path) -> dict[str, Any]:
    stat = path.stat()
    components = count_ics_components(path)
    return {
        "name": path.name,
        "kind": "ics_file",
        "relative_path": path.relative_to(base_dir).as_posix(),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        **components,
    }


def load_subscriptions(ctxid: str) -> dict[str, Any]:
    path = subscriptions_path(ctxid, create=True)
    if not path.exists():
        return {"version": REGISTRY_VERSION, "subscriptions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    subscriptions = data.get("subscriptions")
    if not isinstance(subscriptions, list):
        subscriptions = []
    return {"version": int(data.get("version") or REGISTRY_VERSION), "subscriptions": subscriptions}


def save_subscriptions(ctxid: str, registry: dict[str, Any]) -> None:
    path = subscriptions_path(ctxid, create=True)
    registry.setdefault("version", REGISTRY_VERSION)
    registry.setdefault("subscriptions", [])
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
        json.dump(registry, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def list_calendar_stack(ctxid: str) -> dict[str, Any]:
    calendar_dir = context_calendar_dir(ctxid, create=True)
    files = [file_info(path, calendar_dir) for path in sorted(calendar_dir.glob("*.ics"), key=lambda p: p.name.lower())]
    registry = load_subscriptions(ctxid)
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "calendar_dir": str(calendar_dir),
        "files": files,
        "subscriptions": registry.get("subscriptions", []),
    }


def create_local_calendar(ctxid: str, filename: str, title: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    calendar_dir = context_calendar_dir(ctxid, create=True)
    safe_name = sanitize_calendar_filename(filename)
    path = calendar_dir / safe_name
    if path.exists() and not overwrite:
        raise ValueError(f"calendar file already exists: {safe_name}")
    calendar_name = title or Path(safe_name).stem.replace("_", " ").strip() or "Agent Calendar"
    path.write_text(build_empty_calendar(calendar_name), encoding="utf-8")
    return file_info(path, calendar_dir)


def normalize_subscription_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        raise ValueError("subscription URL is required")
    lowered = clean.lower()
    if not lowered.startswith(_ALLOWED_SUBSCRIPTION_PREFIXES):
        raise ValueError("subscription URL must start with http://, https://, or webcal://")
    return clean


def add_subscription(ctxid: str, name: str, url: str) -> dict[str, Any]:
    clean_url = normalize_subscription_url(url)
    clean_name = str(name or "").strip() or clean_url
    registry = load_subscriptions(ctxid)
    subscriptions = registry.setdefault("subscriptions", [])
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": clean_name,
        "url": clean_url,
        "kind": "ics_subscription",
        "created": iso_now(),
    }
    subscriptions.append(entry)
    save_subscriptions(ctxid, registry)
    return entry


def remove_subscription(ctxid: str, subscription_id: str) -> bool:
    clean_id = str(subscription_id or "").strip()
    if not clean_id:
        raise ValueError("subscription_id is required")
    registry = load_subscriptions(ctxid)
    subscriptions = registry.setdefault("subscriptions", [])
    before = len(subscriptions)
    registry["subscriptions"] = [s for s in subscriptions if str(s.get("id") or "") != clean_id]
    save_subscriptions(ctxid, registry)
    return len(registry["subscriptions"]) != before
