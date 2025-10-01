import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import aiohttp
from fastmcp import FastMCP

mcp = FastMCP("reminder-mcp-server")

REMINDER_BASE_URL = os.environ.get("REMINDER_BASE_URL", "http://localhost:8060")
REMINDER_API_KEY = os.environ.get("REMINDER_API_KEY", "")
REMINDER_TIMEZONE = "UTC"


async def _request(method: str, path: str, json_payload: Optional[dict] = None) -> str:
    url = f"{REMINDER_BASE_URL.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if REMINDER_API_KEY:
        headers["X-API-Key"] = REMINDER_API_KEY
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            if method == "GET":
                async with session.get(url) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        return f"[ERROR]: HTTP {resp.status}: {text}"
                    return text
            elif method == "POST":
                async with session.post(url, json=json_payload) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        return f"[ERROR]: HTTP {resp.status}: {text}"
                    return text
            elif method == "DELETE":
                async with session.delete(url) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        return f"[ERROR]: HTTP {resp.status}: {text}"
                    return text
            else:
                return f"[ERROR]: Unsupported method {method}"
        except Exception as e:
            return f"[ERROR]: request failed: {e}"


def _normalize_tz_name(name: str) -> str:
    """Normalize common timezone aliases to IANA names.

    Supports: 'UTC', 'Z', 'PT'/ 'PST' / 'PDT' -> 'America/Los_Angeles',
    'ET' / 'EST' / 'EDT' -> 'America/New_York'. Falls back to the provided name.
    """
    upper = (name or "").strip().upper()
    if upper in ("UTC", "Z"):
        return "UTC"
    if upper in ("PT", "PST", "PDT"):
        return "America/Los_Angeles"
    if upper in ("ET", "EST", "EDT"):
        return "America/New_York"
    return name


def _to_utc_iso(send_at: str, tz_hint: Optional[str]) -> str:
    """Resolve a provided timestamp string into UTC ISO-8601 with 'Z'.

    - If send_at already includes a timezone (e.g., ends with 'Z' or has an offset), convert to UTC.
    - If send_at is naive (no offset), interpret it in tz_hint (or REMINDER_TIMEZONE), then convert to UTC.
    - Accept common aliases for PT/ET.
    """
    if not send_at:
        raise ValueError("send_at must be provided")

    # Use specified timezone or fall back to env/default
    tz_name = _normalize_tz_name(tz_hint or REMINDER_TIMEZONE)

    # If input has 'Z', swap to +00:00 for fromisoformat
    s = send_at.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        # If dt is naive (no tzinfo), localize with tz_name
        if dt.tzinfo is None:
            if tz_name.upper() == "UTC":
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                if ZoneInfo is None:
                    raise ValueError("zoneinfo not available to resolve local timezone")
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        # Convert to UTC
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception as e:
        raise ValueError(f"Invalid send_at format: {send_at}. Error: {e}")


@mcp.tool()
async def add_reminder(
    content: str,
    send_at: str,
    repeat_seconds: Optional[int] = None,
    timezone_name: Optional[str] = None,
) -> str:
    """Create a reminder.


    Arguments:
    - content (str): Arbitrary string payload to be written when the reminder fires.
    - send_at (str): First run time for the reminder. ISO-8601 is recommended, e.g. "2025-09-26T16:00:00Z".
    - repeat_seconds (int, optional): Fixed interval in seconds for repeated delivery. When provided, the reminder
      repeats indefinitely on that cadence. Must be >= 1 if set.
    - timezone_name (str, optional): Timezone hint used only when "send_at" has no timezone. Accepts common aliases
      like "UTC", "Z", "PT"/"PST"/"PDT" (America/Los_Angeles), and "ET"/"EST"/"EDT" (America/New_York),
      as well as full IANA names (e.g., "America/Los_Angeles"). Defaults to UTC.

    Returns:
    - str: JSON string from the server. For scheduled reminders: {"id": "<reminder_id>"}. For immediate delivery
      (past send_at with no repeat): {"id": ""}.

    Example:
    - content: "pay rent"
    - send_at: "2025-10-01T09:00:00" with timezone_name="PT" → will be scheduled for 9am Pacific, converted to UTC.
    """
    send_at_utc = _to_utc_iso(send_at, timezone_name)
    payload = {
        "content": content,
        "send_at_utc": send_at_utc,
    }
    if repeat_seconds is not None:
        payload["repeat_seconds"] = int(repeat_seconds)
    return await _request("POST", "/reminders", json_payload=payload)


@mcp.tool()
async def list_reminders() -> str:
    """List all reminders.

    Returns:
    - str: JSON string representing a list of reminder objects. Each object typically includes:
      id, namespace (server-configured), content, send_at_utc, repeat_seconds, next_run_at.
    """
    return await _request("GET", "/reminders")


@mcp.tool()
async def cancel_reminder(reminder_id: str) -> str:
    """Cancel and delete a reminder by id.

    Arguments:
    - reminder_id (str): Identifier returned by the server when the reminder was created.

    Returns:
    - str: JSON string like {"id": "<reminder_id>", "cancelled": true}.
    """
    return await _request("DELETE", f"/reminders/{reminder_id}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
