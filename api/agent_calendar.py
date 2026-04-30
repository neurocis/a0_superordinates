"""API endpoint for per-agent calendar files and ICS subscriptions."""

from __future__ import annotations

from helpers.api import ApiHandler, Request
from usr.plugins.a0_superordinates.helpers.agent_calendar import (
    add_subscription,
    create_local_calendar,
    list_calendar_stack,
    remove_subscription,
)


class AgentCalendar(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "list").strip().lower()
        ctxid = str(input.get("ctxid") or input.get("context_id") or "").strip()

        try:
            if action == "list":
                return list_calendar_stack(ctxid)

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

            if action == "add_subscription":
                subscription = add_subscription(
                    ctxid=ctxid,
                    name=str(input.get("name") or ""),
                    url=str(input.get("url") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["added"] = subscription
                return payload

            if action == "remove_subscription":
                removed = remove_subscription(
                    ctxid=ctxid,
                    subscription_id=str(input.get("subscription_id") or input.get("id") or ""),
                )
                payload = list_calendar_stack(ctxid)
                payload["removed"] = removed
                return payload

            return {"ok": False, "error": f"unknown action: {action}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
