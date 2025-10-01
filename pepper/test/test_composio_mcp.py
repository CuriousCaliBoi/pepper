import asyncio
import json
import os
from pathlib import Path

from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager


async def call_direct():
    pepper_dir = Path(__file__).resolve().parents[2]
    servers = load_tools_yaml(str(pepper_dir / "agent" / "tool" / "worker_tools.yaml"))
    resolved = build_stdio_params(servers)
    mgr = ToolManager(resolved)

    print("Listing tools to build dispatch map...")
    tools = await mgr.list_openai_tools()
    print(f"Discovered {len(tools)} OpenAI-style tools.")

    print("Calling tool-composio.gmail_fetch_emails_compact directly via MCP...")
    args = {
        "max_results": 1,
        "ids_only": False,
        "include_payload": False,
        "include_spam_trash": False,
        "label_ids": None,
        "query": None,
        "verbose": False,
        "preview_chars": 120,
        "include_body": False,
    }
    result = await mgr.call("tool-composio", "gmail_fetch_emails_compact", args)
    print("Direct call result (compact messages only):")
    compact_json = result.get("result")
    try:
        compact = (
            json.loads(compact_json) if isinstance(compact_json, str) else compact_json
        )
        print(
            json.dumps(
                compact.get("data", {}).get("messages", []),
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception:
        # Fallback: show raw if parsing failed
        print(json.dumps(result, ensure_ascii=False, indent=2))


async def call_openai_style():
    pepper_dir = Path(__file__).resolve().parents[2]
    servers = load_tools_yaml(str(pepper_dir / "tool" / "tools_with_worker.yaml"))
    resolved = build_stdio_params(servers)
    mgr = ToolManager(resolved)

    print("Listing tools to build dispatch map...")
    tools = await mgr.list_openai_tools()
    print(f"Discovered {len(tools)} OpenAI-style tools.")

    tool_call = {
        "id": "call_test_gmail",
        "function": {
            "name": "tool-composio__gmail_fetch_emails_compact",
            "arguments": json.dumps(
                {
                    "max_results": 1,
                    "ids_only": False,
                    "include_payload": False,
                    "include_spam_trash": False,
                    "label_ids": None,
                    "query": None,
                    "verbose": False,
                    "preview_chars": 120,
                    "include_body": False,
                }
            ),
        },
    }

    print("Calling via OpenAI-style dispatch...")
    msgs = await mgr.call_openai_tool(tool_call)
    print("Tool message(s), compact messages only:")

    # Find the tool response content and print only messages
    def _extract_messages(messages):
        for m in messages:
            if m.get("role") == "tool":
                content = m.get("content")
                try:
                    j = json.loads(content) if isinstance(content, str) else content
                    data = j.get("data", {})
                    return data.get("messages", [])
                except Exception:
                    continue
        return []

    only = _extract_messages(msgs)
    print(json.dumps(only, ensure_ascii=False, indent=2))


async def main():
    mode = os.environ.get("MODE", "direct").lower()
    if mode == "openai":
        await call_openai_style()
    else:
        await call_direct()


if __name__ == "__main__":
    asyncio.run(main())
