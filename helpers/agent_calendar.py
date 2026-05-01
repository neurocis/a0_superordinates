"""Per-agent calendar storage helpers.

- each Agent ContextID gets a calendar folder under /a0/usr/chats/<ctxid>/calendar
- local writable calendars are plain *.ics files in that folder, each holding at
  most one VEVENT or VTODO
- CalDAV accounts (server + credentials + selected collection) are stored in
  caldav.json in that same folder; see helpers/agent_caldav.py for the client.

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
CALDAV_REGISTRY_FILENAME = "caldav.json"
LEGACY_SUBSCRIPTIONS_FILENAME = "subscriptions.json"
REGISTRY_VERSION = 1
CALENDAR_INDICATOR_KEY = "has_calendar"
CALENDAR_INDICATOR_ALT_KEY = "calendar_indicator"

_CTXID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BAD_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_. -]+")


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


def chat_json_path(ctxid: str) -> Path:
    return CHATS_ROOT / validate_context_id(ctxid) / "chat.json"


def _parse_bool(value: Any, default: bool = False) -> bool:
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


def local_ics_file_paths(ctxid: str) -> list[Path]:
    """Return actual local .ics files for a context without trusting metadata."""
    clean = validate_context_id(ctxid)
    calendar_dir = context_calendar_dir(clean, create=False)
    if not calendar_dir.exists() or not calendar_dir.is_dir():
        return []
    try:
        return [
            path for path in sorted(calendar_dir.glob("*.ics"), key=lambda p: p.name.lower())
            if path.is_file()
        ]
    except OSError:
        return []


def derive_has_calendar(ctxid: str) -> bool:
    """Derive the indicator from real sources, not from stale state.

    True when the agent has at least one local *.ics file or at least one
    CalDAV account with an active (selected) collection.
    """
    clean = validate_context_id(ctxid)
    if local_ics_file_paths(clean):
        return True
    try:
        from . import agent_caldav  # late import to avoid circular dep
        if agent_caldav.has_active_caldav_source(clean):
            return True
    except Exception:
        pass
    return False


def _set_calendar_indicator_on_context(clean_ctxid: str, has_calendar: bool) -> bool:
    """Mirror the indicator into any loaded AgentContext data/output_data."""
    changed = False
    try:
        from agent import AgentContext

        ctx = AgentContext.get(clean_ctxid)
        if ctx is not None:
            data = getattr(ctx, "data", None)
            if isinstance(data, dict):
                if data.get(CALENDAR_INDICATOR_KEY) is not has_calendar:
                    data[CALENDAR_INDICATOR_KEY] = has_calendar
                    changed = True
                if data.get(CALENDAR_INDICATOR_ALT_KEY) is not has_calendar:
                    data[CALENDAR_INDICATOR_ALT_KEY] = has_calendar
                    changed = True
            output_data = getattr(ctx, "output_data", None)
            if isinstance(output_data, dict):
                if output_data.get(CALENDAR_INDICATOR_KEY) is not has_calendar:
                    output_data[CALENDAR_INDICATOR_KEY] = has_calendar
                    changed = True
                if output_data.get(CALENDAR_INDICATOR_ALT_KEY) is not has_calendar:
                    output_data[CALENDAR_INDICATOR_ALT_KEY] = has_calendar
                    changed = True
    except Exception:
        pass
    return changed


def persist_calendar_indicator(ctxid: str, has_calendar: bool | None = None) -> bool:
    """Persist/reconcile the per-agent Calendar indicator.

    If has_calendar is omitted, derive it from actual local .ics files and Web
    CalDAV accounts with an active collection.  The value is written to chat.json data/output_data and
    mirrored into any loaded AgentContext so both persisted and in-memory UI
    snapshots converge on the real source state.

    To keep sidebar map polling cheap, chats with no calendar sources and no
    previous indicator metadata are left untouched.  Once a context has ever
    advertised the indicator, false is persisted too so stale true values are
    cleared after the last calendar source is removed.
    """
    clean = validate_context_id(ctxid)
    derived = derive_has_calendar(clean) if has_calendar is None else bool(has_calendar)
    _set_calendar_indicator_on_context(clean, derived)

    path = chat_json_path(clean)
    if path.exists():
        try:
            chat = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(chat, dict):
                data = chat.get("data")
                if not isinstance(data, dict):
                    data = {}
                output_data = chat.get("output_data")
                if not isinstance(output_data, dict):
                    output_data = {}

                has_existing_metadata = any(
                    key in data or key in output_data
                    for key in (CALENDAR_INDICATOR_KEY, CALENDAR_INDICATOR_ALT_KEY)
                )
                if derived or has_existing_metadata:
                    changed = False
                    if chat.get("data") is not data:
                        chat["data"] = data
                        changed = True
                    if chat.get("output_data") is not output_data:
                        chat["output_data"] = output_data
                        changed = True
                    for mapping in (data, output_data):
                        if mapping.get(CALENDAR_INDICATOR_KEY) is not derived:
                            mapping[CALENDAR_INDICATOR_KEY] = derived
                            changed = True
                        if mapping.get(CALENDAR_INDICATOR_ALT_KEY) is not derived:
                            mapping[CALENDAR_INDICATOR_ALT_KEY] = derived
                            changed = True
                    if changed:
                        with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
                            json.dump(chat, tmp, indent=2)
                            tmp.write("\n")
                            tmp_path = Path(tmp.name)
                        tmp_path.replace(path)
        except Exception:
            # Indicator persistence is useful UI metadata, but calendar CRUD
            # should not fail solely because chat.json is temporarily unreadable.
            pass
    return derived


def calendar_indicator_from_metadata(ctxid: str) -> bool:
    """Best-effort read of persisted indicator; reconciles before returning."""
    return persist_calendar_indicator(ctxid)


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
    if value in {".ics", LEGACY_SUBSCRIPTIONS_FILENAME, CALDAV_REGISTRY_FILENAME}:
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
    summary = ""
    component_uid = ""
    is_recurring = False
    component_kind = ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        events = list_ics_events_from_text(text)
        todos = list_ics_todos_from_text(text)
        head: dict[str, Any] | None = None
        if events:
            head = events[0] or {}
            component_kind = "event"
        elif todos:
            head = todos[0] or {}
            component_kind = "todo"
        if head is not None:
            summary = str(head.get("summary") or "").strip()
            component_uid = str(head.get("uid") or "").strip()
            is_recurring = bool(head.get("is_recurring"))
    except Exception:
        pass
    return {
        "name": path.name,
        "kind": "ics_file",
        "relative_path": path.relative_to(base_dir).as_posix(),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "component_kind": component_kind,
        "summary": summary,
        "uid": component_uid,
        "event_summary": summary if component_kind == "event" else "",
        "event_uid": component_uid if component_kind == "event" else "",
        "todo_summary": summary if component_kind == "todo" else "",
        "todo_uid": component_uid if component_kind == "todo" else "",
        "is_recurring": is_recurring,
        **components,
    }


def list_calendar_stack(ctxid: str) -> dict[str, Any]:
    clean_ctxid = validate_context_id(ctxid)
    calendar_dir = context_calendar_dir(clean_ctxid, create=True)
    files = [file_info(path, calendar_dir) for path in local_ics_file_paths(clean_ctxid)]
    try:
        from . import agent_caldav  # late import to avoid circular dep
        caldav_account = agent_caldav.get_caldav_account(clean_ctxid)
        caldav_accounts = [caldav_account] if caldav_account else []
    except Exception:
        caldav_account = None
        caldav_accounts = []
    has_calendar = persist_calendar_indicator(clean_ctxid)
    return {
        "ok": True,
        "ctxid": clean_ctxid,
        "agent_name": get_agent_display_name(clean_ctxid),
        "calendar_dir": str(calendar_dir),
        "files": files,
        "caldav_account": caldav_account,
        "caldav_accounts": caldav_accounts,
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }


def create_local_calendar(ctxid: str, filename: str, title: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    calendar_dir = context_calendar_dir(ctxid, create=True)
    safe_name = sanitize_calendar_filename(filename)
    path = calendar_dir / safe_name
    if path.exists() and not overwrite:
        raise ValueError(f"calendar file already exists: {safe_name}")
    calendar_name = title or Path(safe_name).stem.replace("_", " ").strip() or "Agent Calendar"
    path.write_text(build_empty_calendar(calendar_name), encoding="utf-8")
    persist_calendar_indicator(ctxid)
    info = file_info(path, calendar_dir)
    info["has_calendar"] = True
    info["calendar_indicator"] = True
    return info


def delete_local_calendar(ctxid: str, filename: str) -> dict[str, Any]:
    """Delete a local .ics file and reconcile the Calendar indicator."""
    path, calendar_dir = calendar_file_path(ctxid, filename)
    deleted_name = path.name
    path.unlink()
    has_calendar = persist_calendar_indicator(ctxid)
    files = [file_info(item, calendar_dir) for item in local_ics_file_paths(ctxid)]
    try:
        from . import agent_caldav  # late import to avoid circular dep
        caldav_account = agent_caldav.get_caldav_account(ctxid)
        caldav_accounts = [caldav_account] if caldav_account else []
    except Exception:
        caldav_account = None
        caldav_accounts = []
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "calendar_dir": str(calendar_dir),
        "deleted": deleted_name,
        "files": files,
        "caldav_account": caldav_account,
        "caldav_accounts": caldav_accounts,
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }


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
    has_calendar = persist_calendar_indicator(ctxid)
    events = list_ics_events_from_text(text)
    todos = list_ics_todos_from_text(text)
    event = events[0] if events else None
    todo = todos[0] if todos else None
    component_kind = "event" if event else ("todo" if todo else "")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": text,
        "events": events,
        "todos": todos,
        "event": event,
        "todo": todo,
        "component_kind": component_kind,
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }


def save_calendar_file(ctxid: str, filename: str, content: str) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = normalize_ics_content(content)
    coerced, dropped = enforce_single_component_text(text)
    if dropped:
        raise ValueError(
            "this calendar file may contain at most one VEVENT or VTODO; "
            f"found {dropped + 1} components. Split them into separate .ics files."
        )
    final_text = coerced
    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(final_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    has_calendar = persist_calendar_indicator(ctxid)
    events = list_ics_events_from_text(final_text)
    todos = list_ics_todos_from_text(final_text)
    event = events[0] if events else None
    todo = todos[0] if todos else None
    component_kind = "event" if event else ("todo" if todo else "")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": final_text,
        "events": events,
        "todos": todos,
        "event": event,
        "todo": todo,
        "component_kind": component_kind,
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
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


def property_lines_from_event_lines(lines: list[str], prop: str) -> list[str]:
    target = prop.upper()
    found: list[str] = []
    for line in lines:
        name, _params, _value = split_content_line(line)
        if name == target:
            found.append(line)
    return found


def property_values_from_event_lines(lines: list[str], prop: str) -> list[str]:
    target = prop.upper()
    found: list[str] = []
    for line in lines:
        name, _params, value = split_content_line(line)
        if name == target:
            found.append(value)
    return found


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


def parse_rrule_parts(rrule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in str(rrule or "").strip().split(";"):
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key:
            parts[key] = value
    return parts


def recurrence_frequency_from_rrule(rrule: str) -> str:
    clean = str(rrule or "").strip()
    if not clean:
        return "none"
    parts = parse_rrule_parts(clean)
    freq = parts.get("FREQ", "").upper()
    mapping = {
        "MINUTELY": "minutely",
        "HOURLY": "hourly",
        "DAILY": "daily",
        "WEEKLY": "weekly",
        "MONTHLY": "monthly",
        "YEARLY": "yearly",
    }
    # Only expose the RRULE through the simple UI controls when the rule can be
    # round-tripped by those controls.  Anything with BYDAY/BYMONTHDAY/WKST/etc.
    # stays custom so a form save does not silently simplify the recurrence.
    simple_keys = {"FREQ", "INTERVAL", "COUNT", "UNTIL"}
    if freq in mapping and set(parts).issubset(simple_keys):
        return mapping[freq]
    return "custom"


def parse_rrule_until_for_ui(value: str) -> str:
    raw = str(value or "").strip().rstrip("Z")
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def recurrence_summary(rrule: str, rdate_lines: list[str] | None = None, exdate_lines: list[str] | None = None) -> str:
    clean_rrule = str(rrule or "").strip()
    rdates = rdate_lines or []
    exdates = exdate_lines or []
    if not clean_rrule and not rdates and not exdates:
        return ""

    parts = parse_rrule_parts(clean_rrule)
    freq = parts.get("FREQ", "").upper()
    freq_label = {
        "MINUTELY": "minute",
        "HOURLY": "hour",
        "DAILY": "day",
        "WEEKLY": "week",
        "MONTHLY": "month",
        "YEARLY": "year",
    }.get(freq, "custom")
    if clean_rrule:
        interval = parts.get("INTERVAL", "1") or "1"
        if freq_label == "custom":
            label = "Repeats custom"
        elif interval in {"", "1"}:
            label = f"Repeats every {freq_label}"
        else:
            plural = freq_label if freq_label.endswith("s") else f"{freq_label}s"
            label = f"Repeats every {interval} {plural}"
        if parts.get("COUNT"):
            label += f", {parts['COUNT']} times"
        elif parts.get("UNTIL"):
            until = parse_rrule_until_for_ui(parts["UNTIL"])
            if until:
                label += f", until {until}"
    else:
        label = "Repeats on selected dates"
    if exdates:
        label += f"; {len(exdates)} exception date line{'s' if len(exdates) != 1 else ''}"
    return label


def recurrence_payload_from_event_lines(event_lines: list[str]) -> dict[str, Any]:
    rrule_values = property_values_from_event_lines(event_lines, "RRULE")
    rrule = rrule_values[0] if rrule_values else ""
    rdate_lines = property_lines_from_event_lines(event_lines, "RDATE")
    exdate_lines = property_lines_from_event_lines(event_lines, "EXDATE")
    parts = parse_rrule_parts(rrule)
    frequency = recurrence_frequency_from_rrule(rrule)
    if not rrule and (rdate_lines or exdate_lines):
        frequency = "custom"
    return {
        "rrule": rrule,
        "rdate": "\n".join(rdate_lines),
        "exdate": "\n".join(exdate_lines),
        "recurrence_frequency": frequency,
        "recurrence_interval": parts.get("INTERVAL", "1") or "1",
        "recurrence_count": parts.get("COUNT", ""),
        "recurrence_until": parse_rrule_until_for_ui(parts.get("UNTIL", "")),
        "recurrence_summary": recurrence_summary(rrule, rdate_lines, exdate_lines),
        "is_recurring": bool(rrule or rdate_lines or exdate_lines),
    }


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
                recurrence = recurrence_payload_from_event_lines(event_lines)
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
                    **recurrence,
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


def normalize_rrule_value(value: str) -> str:
    clean = str(value or "").strip()
    if clean.upper().startswith("RRULE:"):
        clean = clean.split(":", 1)[1].strip()
    if not clean:
        return ""
    if "\n" in clean or "\r" in clean:
        raise ValueError("RRULE must be a single line")
    if ":" in clean:
        raise ValueError("RRULE value must not contain ':'")
    if "FREQ=" not in clean.upper():
        raise ValueError("RRULE must include FREQ=")
    return clean


def event_has_recurrence_controls(event: dict[str, Any]) -> bool:
    return any(
        key in event
        for key in (
            "rrule",
            "rdate",
            "exdate",
            "recurrence_frequency",
            "recurrence",
            "recurrence_interval",
            "recurrence_count",
            "recurrence_until",
        )
    )


def build_rrule_from_event(event: dict[str, Any]) -> str:
    explicit = str(event.get("rrule") or "").strip()
    frequency = str(event.get("recurrence_frequency") or event.get("recurrence") or "").strip().lower()
    if explicit and (frequency in {"", "custom"}):
        return normalize_rrule_value(explicit)
    if frequency in {"", "none", "no", "false"}:
        return ""
    freq_map = {
        "minutely": "MINUTELY",
        "hourly": "HOURLY",
        "daily": "DAILY",
        "weekly": "WEEKLY",
        "monthly": "MONTHLY",
        "yearly": "YEARLY",
    }
    if frequency == "custom":
        return normalize_rrule_value(explicit)
    if frequency not in freq_map:
        if explicit:
            return normalize_rrule_value(explicit)
        raise ValueError("recurrence_frequency must be none, minutely, hourly, daily, weekly, monthly, yearly, or custom")

    parts = [f"FREQ={freq_map[frequency]}"]
    try:
        interval = int(str(event.get("recurrence_interval") or "1"))
    except ValueError as exc:
        raise ValueError("recurrence interval must be a number") from exc
    if interval < 1:
        raise ValueError("recurrence interval must be at least 1")
    if interval > 1:
        parts.append(f"INTERVAL={interval}")

    count = str(event.get("recurrence_count") or "").strip()
    until = str(event.get("recurrence_until") or "").strip()
    if count:
        try:
            count_int = int(count)
        except ValueError as exc:
            raise ValueError("recurrence count must be a number") from exc
        if count_int < 1:
            raise ValueError("recurrence count must be at least 1")
        parts.append(f"COUNT={count_int}")
    elif until:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", until):
            raise ValueError("recurrence until date must use YYYY-MM-DD")
        parts.append(f"UNTIL={until.replace('-', '')}T235959Z")
    return ";".join(parts)


def normalize_recurrence_property_lines(value: str, prop: str) -> list[str]:
    target = prop.upper()
    lines: list[str] = []
    for raw in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        clean = raw.strip()
        if not clean:
            continue
        if "\n" in clean or "\r" in clean:
            raise ValueError(f"{target} must contain one property per line")
        name, params, line_value = split_content_line(clean)
        if name == target and line_value:
            suffix = f";{params}" if params else ""
            lines.append(f"{target}{suffix}:{line_value}")
        else:
            if ":" in clean:
                raise ValueError(f"{target} lines must be {target}:... or values only")
            lines.append(f"{target}:{clean}")
    return lines


_EDITABLE_EVENT_PROPERTIES = {
    "UID",
    "DTSTAMP",
    "DTSTART",
    "DTEND",
    "SUMMARY",
    "LOCATION",
    "DESCRIPTION",
    "RRULE",
    "RDATE",
    "EXDATE",
}


def preserved_top_level_event_lines(existing_lines: list[str] | None) -> list[str]:
    if not existing_lines:
        return []
    preserved: list[str] = []
    nested_depth = 0
    for line in existing_lines:
        upper = line.upper()
        if upper in {"BEGIN:VEVENT", "END:VEVENT"}:
            continue
        name, _params, value = split_content_line(line)
        if nested_depth > 0:
            preserved.append(line)
            if name == "BEGIN":
                nested_depth += 1
            elif name == "END":
                nested_depth = max(0, nested_depth - 1)
            continue
        if name == "BEGIN" and value.upper() != "VEVENT":
            preserved.append(line)
            nested_depth = 1
            continue
        if name in _EDITABLE_EVENT_PROPERTIES:
            continue
        preserved.append(line)
    return preserved


def build_vevent(event: dict[str, Any], existing_lines: list[str] | None = None) -> tuple[str, str]:
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
    if existing_lines is not None and not event_has_recurrence_controls(event):
        # Backward-compatible safety: callers that edit simple fields without
        # sending recurrence controls must not accidentally flatten a recurring
        # event into a one-time event.  The WebUI sends explicit controls, so it
        # can still intentionally remove or change recurrence.
        rrule_values = property_values_from_event_lines(existing_lines, "RRULE")
        rrule = rrule_values[0] if rrule_values else ""
        rdate_lines = property_lines_from_event_lines(existing_lines, "RDATE")
        exdate_lines = property_lines_from_event_lines(existing_lines, "EXDATE")
    else:
        rrule = build_rrule_from_event(event)
        rdate_lines = normalize_recurrence_property_lines(str(event.get("rdate") or ""), "RDATE")
        exdate_lines = normalize_recurrence_property_lines(str(event.get("exdate") or ""), "EXDATE")

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
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines.extend(rdate_lines)
    lines.extend(exdate_lines)
    lines.extend(preserved_top_level_event_lines(existing_lines))
    lines.append("END:VEVENT")

    folded: list[str] = []
    for line in lines:
        folded.extend(fold_ics_line(line))
    return uid, "\r\n".join(folded)

def parse_todo_status(value: str) -> str:
    clean = str(value or "").strip().upper()
    valid = {"NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"}
    if clean in valid:
        return clean
    return ""


def list_ics_todos_from_text(text: str) -> list[dict[str, Any]]:
    """Parse VTODO components from raw ICS text into UI-friendly dicts."""
    lines = unfold_ics_lines(text)
    todos: list[dict[str, Any]] = []
    current: list[str] | None = None
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VTODO":
            current = [line]
            continue
        if current is not None:
            current.append(line)
            if upper == "END:VTODO":
                tlines = current
                current = None
                uid = property_from_event_lines(tlines, "UID")
                summary = property_from_event_lines(tlines, "SUMMARY")
                description = property_from_event_lines(tlines, "DESCRIPTION")
                location = property_from_event_lines(tlines, "LOCATION")
                dtstart = property_from_event_lines(tlines, "DTSTART")
                due = property_from_event_lines(tlines, "DUE")
                status = property_from_event_lines(tlines, "STATUS")
                priority = property_from_event_lines(tlines, "PRIORITY")
                percent = property_from_event_lines(tlines, "PERCENT-COMPLETE")
                completed = property_from_event_lines(tlines, "COMPLETED")
                start = parse_ics_datetime_for_ui(dtstart[1], dtstart[0]) if dtstart else {"date": "", "time": "", "all_day": False, "raw": ""}
                due_p = parse_ics_datetime_for_ui(due[1], due[0]) if due else {"date": "", "time": "", "all_day": False, "raw": ""}
                recurrence = recurrence_payload_from_event_lines(tlines)
                todos.append({
                    "uid": uid[1] if uid else "",
                    "summary": unescape_ics_text(summary[1]) if summary else "(No title)",
                    "description": unescape_ics_text(description[1]) if description else "",
                    "location": unescape_ics_text(location[1]) if location else "",
                    "start_date": start.get("date", ""),
                    "start_time": start.get("time", ""),
                    "due_date": due_p.get("date", ""),
                    "due_time": due_p.get("time", ""),
                    "all_day": bool(due_p.get("all_day") or start.get("all_day")),
                    "dtstart": start.get("raw", ""),
                    "due": due_p.get("raw", ""),
                    "status": parse_todo_status(status[1]) if status else "",
                    "priority": str(priority[1]).strip() if priority else "",
                    "percent_complete": str(percent[1]).strip() if percent else "",
                    "completed": completed[1] if completed else "",
                    **recurrence,
                })
    return todos


_EDITABLE_TODO_PROPERTIES = {
    "UID",
    "DTSTAMP",
    "DTSTART",
    "DUE",
    "SUMMARY",
    "LOCATION",
    "DESCRIPTION",
    "STATUS",
    "PRIORITY",
    "PERCENT-COMPLETE",
    "COMPLETED",
    "RRULE",
    "RDATE",
    "EXDATE",
}


def preserved_top_level_todo_lines(existing_lines: list[str] | None) -> list[str]:
    if not existing_lines:
        return []
    preserved: list[str] = []
    nested_depth = 0
    for line in existing_lines:
        upper = line.upper()
        if upper in {"BEGIN:VTODO", "END:VTODO"}:
            continue
        name, _params, value = split_content_line(line)
        if nested_depth > 0:
            preserved.append(line)
            if name == "BEGIN":
                nested_depth += 1
            elif name == "END":
                nested_depth = max(0, nested_depth - 1)
            continue
        if name == "BEGIN" and value.upper() != "VTODO":
            preserved.append(line)
            nested_depth = 1
            continue
        if name in _EDITABLE_TODO_PROPERTIES:
            continue
        preserved.append(line)
    return preserved


def build_vtodo(todo: dict[str, Any], existing_lines: list[str] | None = None) -> tuple[str, str]:
    uid = str(todo.get("uid") or "").strip() or uuid.uuid4().hex
    summary = str(todo.get("summary") or "").strip() or "Untitled Todo"
    description = str(todo.get("description") or "")
    location = str(todo.get("location") or "")
    all_day = bool(todo.get("all_day"))

    lines = [
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"DTSTAMP:{ics_timestamp()}",
    ]

    start_date = str(todo.get("start_date") or "").strip()
    if start_date:
        start_time = str(todo.get("start_time") or "").strip() or "00:00"
        sp, sv = format_ics_datetime(start_date, start_time, all_day)
        lines.append(f"DTSTART{sp}:{sv}")

    due_date = str(todo.get("due_date") or "").strip()
    if due_date:
        due_time = str(todo.get("due_time") or "").strip() or "00:00"
        dp, dv = format_ics_datetime(due_date, due_time, all_day)
        lines.append(f"DUE{dp}:{dv}")

    lines.append(f"SUMMARY:{escape_ics_text(summary)}")
    if location.strip():
        lines.append(f"LOCATION:{escape_ics_text(location)}")
    if description.strip():
        lines.append(f"DESCRIPTION:{escape_ics_text(description)}")

    status = parse_todo_status(str(todo.get("status") or ""))
    if status:
        lines.append(f"STATUS:{status}")

    priority = str(todo.get("priority") or "").strip()
    if priority:
        try:
            pi = int(priority)
            if 0 <= pi <= 9:
                lines.append(f"PRIORITY:{pi}")
            else:
                raise ValueError
        except ValueError as exc:
            raise ValueError("priority must be an integer between 0 and 9") from exc

    percent = str(todo.get("percent_complete") or "").strip()
    if percent:
        try:
            pc = int(percent)
            if 0 <= pc <= 100:
                lines.append(f"PERCENT-COMPLETE:{pc}")
            else:
                raise ValueError
        except ValueError as exc:
            raise ValueError("percent_complete must be an integer between 0 and 100") from exc

    if existing_lines is not None and not event_has_recurrence_controls(todo):
        rrule_values = property_values_from_event_lines(existing_lines, "RRULE")
        rrule = rrule_values[0] if rrule_values else ""
        rdate_lines = property_lines_from_event_lines(existing_lines, "RDATE")
        exdate_lines = property_lines_from_event_lines(existing_lines, "EXDATE")
    else:
        rrule = build_rrule_from_event(todo)
        rdate_lines = normalize_recurrence_property_lines(str(todo.get("rdate") or ""), "RDATE")
        exdate_lines = normalize_recurrence_property_lines(str(todo.get("exdate") or ""), "EXDATE")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines.extend(rdate_lines)
    lines.extend(exdate_lines)

    lines.extend(preserved_top_level_todo_lines(existing_lines))
    lines.append("END:VTODO")

    folded: list[str] = []
    for line in lines:
        folded.extend(fold_ics_line(line))
    return uid, "\r\n".join(folded)


def split_calendar_component_blocks(text: str) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """Generic VEVENT/VTODO splitter.

    Returns (skeleton, components) where components is a list of
    (kind, uid, lines).  kind is 'VEVENT' or 'VTODO'.
    """
    lines = unfold_ics_lines(text)
    skeleton: list[str] = []
    components: list[tuple[str, str, list[str]]] = []
    current: list[str] | None = None
    current_kind = ""
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = [line]
            current_kind = "VEVENT"
            continue
        if upper == "BEGIN:VTODO":
            current = [line]
            current_kind = "VTODO"
            continue
        if current is not None:
            current.append(line)
            if upper == f"END:{current_kind}":
                uid_prop = property_from_event_lines(current, "UID")
                components.append((current_kind, uid_prop[1] if uid_prop else "", current))
                current = None
                current_kind = ""
            continue
        skeleton.append(line)
    return skeleton, components


def enforce_single_component_text(text: str) -> tuple[str, int]:
    """Keep at most the first VEVENT or VTODO component in the calendar.

    Returns (calendar_text, dropped_count).  Dropped count counts every extra
    VEVENT/VTODO beyond the first.
    """
    skeleton, components = split_calendar_component_blocks(text)
    if len(components) <= 1:
        return text, 0
    _kind, _uid, first_lines = components[0]
    first_block = "\r\n".join(first_lines)
    return render_calendar_with_events(skeleton, [first_block]), len(components) - 1


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


def enforce_single_vevent_text(text: str) -> tuple[str, int]:
    """Backward-compatible wrapper around enforce_single_component_text.

    Local .ics files now hold a single VEVENT *or* a single VTODO.  Older
    callers still ask about "single VEVENT" enforcement, so route them to the
    generic component enforcer.
    """
    return enforce_single_component_text(text)


def extract_single_event_summary(events: list[dict]) -> str:
    if not events:
        return ""
    head = events[0] or {}
    summary = str(head.get("summary") or "").strip()
    return summary


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
    skeleton, components = split_calendar_component_blocks(text)

    target_uid = str(old_uid or event.get("uid") or "").strip()
    existing_lines: list[str] | None = None
    for kind, comp_uid, lines in components:
        if kind == "VEVENT" and target_uid and comp_uid == target_uid:
            existing_lines = lines
            break
    if existing_lines is None:
        for kind, _comp_uid, lines in components:
            if kind == "VEVENT":
                existing_lines = lines
                break

    uid_value = str(event.get("uid") or "").strip() or uuid.uuid4().hex
    event_with_uid = {**event, "uid": uid_value}
    uid_value, block = build_vevent(event_with_uid, existing_lines=existing_lines)

    new_text = render_calendar_with_events(skeleton, [block])
    new_text, _dropped = enforce_single_component_text(new_text)

    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    has_calendar = persist_calendar_indicator(ctxid)
    events = list_ics_events_from_text(new_text)
    todos = list_ics_todos_from_text(new_text)
    event_payload = events[0] if events else None
    todo_payload = todos[0] if todos else None
    component_kind = "event" if event_payload else ("todo" if todo_payload else "")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": new_text,
        "events": events,
        "todos": todos,
        "event": event_payload,
        "todo": todo_payload,
        "component_kind": component_kind,
        "saved_event_uid": uid_value,
        "saved_component_kind": "event",
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }


def delete_calendar_event(ctxid: str, filename: str, uid: str | None = None) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = path.read_text(encoding="utf-8", errors="replace")
    skeleton, components = split_calendar_component_blocks(text)
    if not components:
        raise ValueError("event not found")

    requested_uid = str(uid or "").strip()
    if requested_uid:
        match = next((c for c in components if c[1] == requested_uid), None)
        if match is None:
            raise ValueError("event not found")
        deleted_kind, deleted_uid, _lines = match
    else:
        deleted_kind, deleted_uid, _lines = components[0]

    new_text = render_calendar_with_events(skeleton, [])

    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    has_calendar = persist_calendar_indicator(ctxid)
    events = list_ics_events_from_text(new_text)
    todos = list_ics_todos_from_text(new_text)
    event_payload = events[0] if events else None
    todo_payload = todos[0] if todos else None
    component_kind = "event" if event_payload else ("todo" if todo_payload else "")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": new_text,
        "events": events,
        "todos": todos,
        "event": event_payload,
        "todo": todo_payload,
        "component_kind": component_kind,
        "deleted_event_uid": deleted_uid,
        "deleted_component_uid": deleted_uid,
        "deleted_component_kind": "event" if deleted_kind == "VEVENT" else "todo",
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }

def upsert_calendar_todo(ctxid: str, filename: str, todo: dict[str, Any], old_uid: str | None = None) -> dict[str, Any]:
    path, calendar_dir = calendar_file_path(ctxid, filename)
    text = path.read_text(encoding="utf-8", errors="replace")
    skeleton, components = split_calendar_component_blocks(text)

    target_uid = str(old_uid or todo.get("uid") or "").strip()
    existing_lines: list[str] | None = None
    for kind, comp_uid, lines in components:
        if kind == "VTODO" and target_uid and comp_uid == target_uid:
            existing_lines = lines
            break
    if existing_lines is None:
        for kind, _comp_uid, lines in components:
            if kind == "VTODO":
                existing_lines = lines
                break

    uid_value = str(todo.get("uid") or "").strip() or uuid.uuid4().hex
    todo_with_uid = {**todo, "uid": uid_value}
    uid_value, block = build_vtodo(todo_with_uid, existing_lines=existing_lines)

    new_text = render_calendar_with_events(skeleton, [block])
    new_text, _dropped = enforce_single_component_text(new_text)

    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(calendar_dir), delete=False) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    has_calendar = persist_calendar_indicator(ctxid)
    events = list_ics_events_from_text(new_text)
    todos = list_ics_todos_from_text(new_text)
    event_payload = events[0] if events else None
    todo_payload = todos[0] if todos else None
    component_kind = "event" if event_payload else ("todo" if todo_payload else "")
    return {
        "ok": True,
        "ctxid": validate_context_id(ctxid),
        "file": file_info(path, calendar_dir),
        "content": new_text,
        "events": events,
        "todos": todos,
        "event": event_payload,
        "todo": todo_payload,
        "component_kind": component_kind,
        "saved_todo_uid": uid_value,
        "saved_component_kind": "todo",
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
    }


def delete_calendar_todo(ctxid: str, filename: str, uid: str | None = None) -> dict[str, Any]:
    """Compatibility wrapper: clears the file's component (event or todo)."""
    result = delete_calendar_event(ctxid, filename, uid)
    return result
