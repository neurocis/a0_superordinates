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



def get_agent_display_name(ctxid: str) -> str:
    """Return the best available human-facing name for a context/agent."""
    clean = validate_context_id(ctxid)

    try:
        from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_ctxid

        record = lookup_by_ctxid(clean)
        if isinstance(record, dict):
            for key in ("name", "display_name", "title", "static_name"):
                value = record.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        elif isinstance(record, str) and record.strip():
            return record.strip()
    except Exception:
        pass

    chat_dir = CHATS_ROOT / clean
    for filename in ("chat.json", "context.json"):
        try:
            path = chat_dir / filename
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            for key in ("static_name", "name", "title", "agent_name"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except Exception:
            continue

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
    clean_ctxid = validate_context_id(ctxid)
    calendar_dir = context_calendar_dir(clean_ctxid, create=True)
    files = [file_info(path, calendar_dir) for path in sorted(calendar_dir.glob("*.ics"), key=lambda p: p.name.lower())]
    registry = load_subscriptions(clean_ctxid)
    return {
        "ok": True,
        "ctxid": clean_ctxid,
        "agent_name": get_agent_display_name(clean_ctxid),
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


# ---- Writable ICS file/event editing helpers ----

def calendar_file_path(ctxid: str, filename: str) -> tuple[Path, Path]:
    """Return a safe local .ics path for a context.

    The UI only exposes filenames returned by list_calendar_stack(), but the API
    defensively strips paths and re-applies the same filename rules used when
    creating calendars so callers cannot escape the per-context calendar folder.
    """
    calendar_dir = context_calendar_dir(ctxid, create=True)
    safe_name = sanitize_calendar_filename(filename)
    path = (calendar_dir / safe_name).resolve()
    base = calendar_dir.resolve()
    if path.parent != base:
        raise ValueError("invalid calendar path")
    if not path.exists():
        raise FileNotFoundError(f"calendar file not found: {safe_name}")
    return path, calendar_dir


def read_calendar_file(ctxid: str, filename: str) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": text,
        "events": list_ics_events_from_text(text),
    }


def save_calendar_file(ctxid: str, filename: str, content: str) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = normalize_ics_content(content)
    upper = text.upper()
    if "BEGIN:VCALENDAR" not in upper or "END:VCALENDAR" not in upper:
        raise ValueError("content must contain a VCALENDAR")
    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": text,
        "events": list_ics_events_from_text(text),
    }


def normalize_ics_content(content: str) -> str:
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\r\n".join(line.rstrip() for line in text.split("\n"))
    if not text.endswith("\r\n"):
        text += "\r\n"
    return text


def unfold_ics_lines(text: str) -> list[str]:
    raw_lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for raw in raw_lines:
        if not raw:
            continue
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def split_content_line(line: str) -> tuple[str, str, str]:
    before, sep, value = line.partition(":")
    if not sep:
        return line.upper(), "", ""
    name, _semi, params = before.partition(";")
    return name.upper(), params, value


def unescape_ics_text(value: str) -> str:
    text = str(value or "")
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt in ("n", "N"):
                out.append("\n")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def property_from_event_lines(lines: list[str], prop: str) -> tuple[str, str] | None:
    target = prop.upper()
    for line in lines:
        name, params, value = split_content_line(line)
        if name == target:
            return params, value
    return None


def parse_ics_datetime_for_ui(value: str, params: str = "") -> dict[str, Any]:
    raw = str(value or "").strip()
    all_day = "VALUE=DATE" in str(params or "").upper() or (len(raw) == 8 and "T" not in raw)
    if all_day and len(raw) >= 8:
        return {"date": f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}", "time": "00:00", "all_day": True, "raw": raw}
    compact = raw.rstrip("Z")
    if len(compact) >= 15 and "T" in compact:
        return {
            "date": f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}",
            "time": f"{compact[9:11]}:{compact[11:13]}",
            "all_day": False,
            "raw": raw,
        }
    return {"date": "", "time": "", "all_day": False, "raw": raw}


def list_ics_events_from_text(text: str) -> list[dict[str, Any]]:
    lines = unfold_ics_lines(text)
    events: list[dict[str, Any]] = []
    current: list[str] | None = None
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = [line]
            continue
        if current is not None:
            current.append(line)
            if upper == "END:VEVENT":
                event_lines = current
                current = None
                uid = property_from_event_lines(event_lines, "UID")
                summary = property_from_event_lines(event_lines, "SUMMARY")
                description = property_from_event_lines(event_lines, "DESCRIPTION")
                location = property_from_event_lines(event_lines, "LOCATION")
                dtstart = property_from_event_lines(event_lines, "DTSTART")
                dtend = property_from_event_lines(event_lines, "DTEND")
                start = parse_ics_datetime_for_ui(dtstart[1], dtstart[0]) if dtstart else {"date": "", "time": "", "all_day": False, "raw": ""}
                end = parse_ics_datetime_for_ui(dtend[1], dtend[0]) if dtend else {"date": "", "time": "", "all_day": False, "raw": ""}
                events.append({
                    "uid": uid[1] if uid else "",
                    "summary": unescape_ics_text(summary[1]) if summary else "(No title)",
                    "description": unescape_ics_text(description[1]) if description else "",
                    "location": unescape_ics_text(location[1]) if location else "",
                    "start_date": start.get("date", ""),
                    "start_time": start.get("time", ""),
                    "end_date": end.get("date", ""),
                    "end_time": end.get("time", ""),
                    "all_day": bool(start.get("all_day")),
                    "dtstart": start.get("raw", ""),
                    "dtend": end.get("raw", ""),
                })
    return events


def format_ics_datetime(date_value: str, time_value: str = "", all_day: bool = False, *, end_date: bool = False) -> tuple[str, str]:
    date_clean = str(date_value or "").strip()
    time_clean = str(time_value or "").strip() or "00:00"
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_clean):
        raise ValueError("event date must use YYYY-MM-DD")
    date_part = date_clean.replace("-", "")
    if all_day:
        return ";VALUE=DATE", date_part
    if not re.match(r"^\d{2}:\d{2}$", time_clean):
        raise ValueError("event time must use HH:MM")
    return "", f"{date_part}T{time_clean.replace(':', '')}00"


def build_vevent(event: dict[str, Any]) -> tuple[str, str]:
    uid = str(event.get("uid") or "").strip() or uuid.uuid4().hex
    summary = str(event.get("summary") or "").strip() or "Untitled Event"
    description = str(event.get("description") or "")
    location = str(event.get("location") or "")
    all_day = bool(event.get("all_day"))

    start_date = str(event.get("start_date") or "").strip()
    start_time = str(event.get("start_time") or "").strip() or "00:00"
    end_date = str(event.get("end_date") or start_date).strip() or start_date
    end_time = str(event.get("end_time") or start_time).strip() or start_time

    start_params, start_value = format_ics_datetime(start_date, start_time, all_day)
    end_params, end_value = format_ics_datetime(end_date, end_time, all_day)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{ics_timestamp()}",
        f"DTSTART{start_params}:{start_value}",
        f"DTEND{end_params}:{end_value}",
        f"SUMMARY:{escape_ics_text(summary)}",
    ]
    if location.strip():
        lines.append(f"LOCATION:{escape_ics_text(location)}")
    if description.strip():
        lines.append(f"DESCRIPTION:{escape_ics_text(description)}")
    lines.append("END:VEVENT")

    folded: list[str] = []
    for line in lines:
        folded.extend(fold_ics_line(line))
    return uid, "\r\n".join(folded)


def split_calendar_event_blocks(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    lines = unfold_ics_lines(text)
    skeleton: list[str] = []
    events: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = [line]
            continue
        if current is not None:
            current.append(line)
            if upper == "END:VEVENT":
                uid_prop = property_from_event_lines(current, "UID")
                events.append((uid_prop[1] if uid_prop else "", current))
                current = None
            continue
        skeleton.append(line)
    return skeleton, events


def render_calendar_with_events(skeleton: list[str], event_blocks: list[str]) -> str:
    output: list[str] = []
    inserted = False
    for line in skeleton:
        if line.upper() == "END:VCALENDAR" and not inserted:
            for block in event_blocks:
                output.extend(block.replace("\r\n", "\n").strip("\n").split("\n"))
            inserted = True
        output.append(line)
    if not inserted:
        output.append("BEGIN:VCALENDAR")
        output.extend(block.replace("\r\n", "\n").strip("\n").split("\n") for block in event_blocks)
        output.append("END:VCALENDAR")
    flat: list[str] = []
    for item in output:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return "\r\n".join(flat) + "\r\n"


def upsert_calendar_event(ctxid: str, filename: str, event: dict[str, Any], old_uid: str | None = None) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = path.read_text(encoding="utf-8", errors="replace")
    skeleton, existing = split_calendar_event_blocks(text)
    uid, block = build_vevent(event)
    target_uid = str(old_uid or event.get("uid") or "").strip()
    replaced = False
    blocks: list[str] = []
    for existing_uid, lines in existing:
        if target_uid and existing_uid == target_uid:
            if not replaced:
                blocks.append(block)
                replaced = True
            continue
        blocks.append("\r\n".join(lines))
    if not replaced:
        blocks.append(block)
    new_text = render_calendar_with_events(skeleton, blocks)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": new_text,
        "events": list_ics_events_from_text(new_text),
        "saved_event_uid": uid,
    }


def delete_calendar_event(ctxid: str, filename: str, uid: str) -> dict[str, Any]:
    clean_uid = str(uid or "").strip()
    if not clean_uid:
        raise ValueError("uid is required")
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = path.read_text(encoding="utf-8", errors="replace")
    skeleton, existing = split_calendar_event_blocks(text)
    removed = False
    blocks: list[str] = []
    for existing_uid, lines in existing:
        if existing_uid == clean_uid:
            removed = True
            continue
        blocks.append("\r\n".join(lines))
    if not removed:
        raise ValueError("event not found")
    new_text = render_calendar_with_events(skeleton, blocks)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": new_text,
        "events": list_ics_events_from_text(new_text),
        "deleted_event_uid": clean_uid,
    }
