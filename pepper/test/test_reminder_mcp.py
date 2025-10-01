import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from pepper.constants import PEPPER_DIR, REPO_ROOT
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager


async def main():
    servers = load_tools_yaml(PEPPER_DIR / "agent" / "tool" / "worker_tools.yaml")
    resolved = build_stdio_params(servers)
    mgr = ToolManager(resolved)

    # Compute a local send_at 5 seconds from now and let the server convert to UTC with timezone_name
    send_at = (datetime.now(timezone.utc) + timedelta(seconds=5)).replace(microsecond=0)
    send_at_str = send_at.isoformat().replace("+00:00", "Z")
    print(f"Calling tool-reminder.add_reminder for {send_at_str} (timezone=UTC)...")

    result = await mgr.call(
        "tool-reminder",
        "add_reminder",
        {
            "content": "hello world",
            "send_at": send_at_str,
            "timezone_name": "UTC",
        },
    )
    print("Call result:", result)
    created_id = None
    try:
        created_id = json.loads(result.get("result") or "{}").get("id")
    except Exception:
        pass

    # List reminders in the namespace and try to retrieve the created one
    print("Calling tool-reminder.list_reminders...")
    listing = await mgr.call(
        "tool-reminder",
        "list_reminders",
        {},
    )
    print("List result:", listing)

    if created_id:
        try:
            items = json.loads(listing.get("result") or "[]")
            match = next((it for it in items if it.get("id") == created_id), None)
            print("Retrieved created reminder:", match)
        except Exception:
            pass
    created_id = None
    try:
        created_id = json.loads(result.get("result") or "{}").get("id")
    except Exception:
        pass


if __name__ == "__main__":
    import subprocess

    subprocess.Popen(
        [
            "uvicorn",
            "pepper.services.reminder_http:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8060",
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),  # Pass current environment to subprocess
    )
    asyncio.run(main())

    os.system("pkill -f 'pepper.'")
