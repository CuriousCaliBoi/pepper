from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Set, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pepper.llm_client.model import ToolCall, ToolCallResult

from .types import ResolvedServer


def with_timeout(timeout_seconds: float):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await asyncio.wait_for(
                func(*args, **kwargs), timeout=timeout_seconds
            )

        return wrapper

    return decorator


logger = logging.getLogger(__name__)


class ToolManager:
    def __init__(
        self,
        server_configs: List[ResolvedServer],
        *,
        timeout_seconds: float = 900,
        tool_blacklist: Set[Tuple[str, str]] | None = None,
    ) -> None:
        self.server_configs = server_configs
        self.server_dict: Dict[str, StdioServerParameters] = {
            cfg.name: cfg.params for cfg in server_configs
        }
        self.timeout_seconds = timeout_seconds
        self.tool_blacklist = tool_blacklist or set()
        logger.info(
            "ToolManager initialized with servers: %s",
            list(self.server_dict.keys()),
        )

        self.openai_tools = None
        self.openai_dispatch = None

    async def list_openai_tools(self):
        tools = await self.list_tools()
        self.openai_tools, self.openai_dispatch = self._convert_mcp_to_openai_tools(
            tools
        )
        return self.openai_tools

    async def list_tools(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for cfg in self.server_configs:
            server_name = cfg.name
            params = cfg.params
            server_entry: Dict[str, Any] = {"name": server_name, "tools": []}
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(
                        read, write, sampling_callback=None
                    ) as session:
                        await session.initialize()
                        tools_response = await session.list_tools()
                        for tool in tools_response.tools:
                            if (server_name, tool.name) in self.tool_blacklist:
                                continue
                            server_entry["tools"].append(
                                {
                                    "name": tool.name,
                                    "description": tool.description,
                                    "schema": tool.inputSchema,
                                }
                            )
            except Exception as e:
                logger.exception("Failed to list tools for server %s", server_name)
                server_entry["tools"] = [{"error": str(e)}]
            results.append(server_entry)
        return results

    @with_timeout(900)
    async def call(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = self.server_dict.get(server_name)
        if params is None:
            return {"error": f"Unknown server '{server_name}'"}

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(
                    read, write, sampling_callback=None
                ) as session:
                    await session.initialize()
                    tool_result = await session.call_tool(
                        tool_name, arguments=arguments
                    )
                    result_text = (
                        tool_result.content[-1].text if tool_result.content else ""
                    )
                    if result_text is None or result_text == "":
                        result_text = ""
                    return {
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": result_text,
                    }
        except Exception as e:
            logger.exception("Tool call failed for %s.%s", server_name, tool_name)
            return {"error": str(e)}

    def _convert_mcp_to_openai_tools(
        self, mcp_servers: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Tuple[str, str]]]:
        """
        Convert ToolManager.list_tools() output into OpenAI Chat Completions 'tools' and
        a dispatch map {function_name: (server_name, tool_name)}.
        """

        def _sanitize(name: str) -> str:
            # Only letters/numbers/_/- allowed; trim to 64 chars.
            return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]

        tools: List[Dict[str, Any]] = []
        dispatch: Dict[str, Tuple[str, str]] = {}

        for server in mcp_servers or []:
            server_name = str(server.get("name", "server")).strip() or "server"
            for t in server.get("tools", []):
                if "error" in t:
                    continue
                tool_name = str(t.get("name", "tool")).strip() or "tool"
                description = (t.get("description") or f"{server_name}.{tool_name}")[
                    :512
                ]
                schema = t.get("schema") or {}

                # Ensure parameters is an object schema
                if not isinstance(schema, dict) or schema.get("type") != "object":
                    parameters = {
                        "type": "object",
                        "properties": {
                            "input": (
                                schema
                                if isinstance(schema, dict)
                                else {"type": "string"}
                            )
                        },
                        "required": ["input"],
                        "additionalProperties": True,
                    }
                else:
                    parameters = schema

                fn_name = _sanitize(f"{server_name}__{tool_name}")

                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "description": description,
                            "parameters": parameters,
                        },
                    }
                )
                dispatch[fn_name] = (server_name, tool_name)

        return tools, dispatch

    async def call_openai_tool(
        self,
        tool_call: ToolCall,
    ) -> ToolCallResult:
        """
        Execute OpenAI tool calls via MCP ToolManager and return Chat Completions tool messages.

        Returns a list of {role:"tool", tool_call_id: str, content: str} messages.
        """
        # Build dispatch map if not provided
        dispatch = self.openai_dispatch

        # Handle the new format where tool_call has structure:
        # {"id": "call_123", "function": {"name": "tool_name", "arguments": "..."}}
        tc_id = tool_call.id
        fn_name = tool_call.name
        args_str = tool_call.arguments
        try:
            if isinstance(args_str, str):
                args = json.loads(args_str or "{}")
            else:
                args = args_str
        except Exception:
            args = {}

        if fn_name not in dispatch:
            content = json.dumps({"error": f"Unknown tool function: {fn_name}"})
            tool_result = ToolCallResult(id=tc_id, name=fn_name, result=content)
            return tool_result

        server_name, tool_name = dispatch[fn_name]
        result = await self.call(server_name, tool_name, args)

        tool_result = ToolCallResult(id=tc_id, name=fn_name, result=json.dumps(result))
        return tool_result
