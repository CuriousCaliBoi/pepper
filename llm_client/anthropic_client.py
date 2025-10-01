import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from langfuse import Langfuse

from pepper.llm_client.model import AssistantMessage, ToolCall

anthropic_client = None
langfuse_client = None


async def get_anthropic_client():
    global anthropic_client
    if anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; unable to initialize Anthropic client"
            )
        try:
            # Import inside function to avoid hard dependency if unused
            from anthropic import Anthropic

            anthropic_client = Anthropic(api_key=api_key)
            # Lightweight sanity check: list models (may require proper permissions)
            # If listing models is restricted, perform a 1-token test call instead
            try:
                anthropic_client.models.list()
            except Exception:
                # Fallback to a tiny completion to validate key
                anthropic_client.messages.create(
                    model="claude-3-5-haiku-latest",
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                )
        except Exception as e:
            anthropic_client = None
            raise RuntimeError(
                f"Failed to initialize Anthropic client (check API key/network): {e}"
            ) from e
    return anthropic_client


async def get_langfuse_client():
    global langfuse_client
    if langfuse_client is None:
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        if not secret_key or not public_key:
            return None
        try:
            langfuse_client = Langfuse(
                secret_key=secret_key, public_key=public_key, host=host
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Langfuse client: {e}") from e
    return langfuse_client


def _convert_openai_tools_to_anthropic(tools: Optional[List[Dict[str, Any]]]):
    if not tools:
        return None
    converted = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        fn = tool.get("function", {})
        converted.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {}),
            }
        )
    return converted or None


def _convert_tool_use_to_openai(tool_use: Dict[str, Any]) -> Dict[str, Any]:
    # Anthropic returns {type: "tool_use", id, name, input}
    return {
        "id": tool_use.get("id"),
        "type": "function",
        "function": {
            "name": tool_use.get("name"),
            "arguments": json.dumps(tool_use.get("input", {})),
        },
    }


def _normalize_model_name(model: str) -> str:
    # Map convenient "-direct" aliases to Anthropic's canonical names
    mapping = {
        "claude-3-5-sonnet-direct": "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-direct": "claude-3-5-haiku-latest",
        "claude-3-opus-direct": "claude-3-opus-latest",
    }
    if model in mapping:
        return mapping[model]
    # If user passes claude-*-latest or exact version, leave as-is
    # If user passes older alias without -latest, prefer -latest
    if model.endswith("-sonnet"):
        return model + "-latest"
    if model.endswith("-haiku"):
        return model + "-latest"
    if model.endswith("-opus"):
        return model + "-latest"
    return model


async def call_anthropic_api(
    messages: List[Dict[str, Any]],
    model: str,
    max_tokens: int,
    temperature: float,
    tools: Optional[List[Dict[str, Any]]],
    name: str = "anthropic_api",
) -> AssistantMessage:
    import time

    client = await get_anthropic_client()
    langfuse = await get_langfuse_client()

    # Prepare Anthropic params
    # Anthropic supports tools via tool_choice/tools fields on messages.create
    anthropic_tools = _convert_openai_tools_to_anthropic(tools)

    # Anthropic expects messages as a list of {role, content}
    # System instructions go in the top-level system param.
    system_text = None
    simple_messages: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            # concatenate multiple system messages if present
            text = msg.get("content") or ""
            system_text = f"{system_text}\n\n{text}" if system_text else text
            continue
        if role == "tool":
            # Anthropic tool results use a structured dict in content: {type: "tool_result"}
            tool_text = msg.get("content", "") or ""
            simple_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id"),
                            "content": [
                                {"type": "text", "text": tool_text},
                            ],
                        }
                    ],
                }
            )
            continue
        # user/assistant messages
        if role == "assistant":
            blocks = []
            # Optional assistant text
            content_text = msg.get("content")
            if content_text:
                blocks.append({"type": "text", "text": content_text})
            # Convert any OpenAI-style tool_calls to Anthropic tool_use blocks
            for tc in msg.get("tool_calls", []) or []:
                try:
                    args_str = tc.get("function", {}).get("arguments")
                    args = (
                        json.loads(args_str)
                        if isinstance(args_str, str)
                        else (args_str or {})
                    )
                except Exception:
                    args = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": tc.get("function", {}).get("name"),
                        "input": args or {},
                    }
                )
            # Ensure content is present (Anthropic requires content to be non-null)
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            simple_messages.append({"role": "assistant", "content": blocks})
        else:
            # Treat any non-system, non-tool, non-assistant as a standard text message (e.g., user)
            content = msg.get("content")
            if content is None:
                content = ""
            simple_messages.append({"role": role, "content": content})

    generation = None
    if langfuse:
        metadata = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "operation": "anthropic.messages.create",
            "provider": "anthropic",
        }
        generation = langfuse.start_generation(
            name=name, model=model, input=messages, metadata=metadata
        )

    start_time = time.time()

    # Perform the request (Anthropic SDK is sync; run in thread if needed)
    from anthropic import APIStatusError

    try:
        # messages.create is synchronous in anthropic>=0.30
        response = await asyncio.to_thread(
            client.messages.create,
            model=_normalize_model_name(model),
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_text or None,
            tools=anthropic_tools or None,
            messages=simple_messages,
        )
    except Exception as e:
        raise RuntimeError(f"Anthropic API error: {e}") from e

    end_time = time.time()

    # Parse response
    text_content = ""
    tool_calls_oa: List[Dict[str, Any]] = []

    # response.content is a list of blocks: {type: "text"|"tool_use", ...}
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if block_type == "text":
            # SDK returns an object with .text
            value = getattr(block, "text", None)
            if value is None and isinstance(block, dict):
                value = block.get("text", "")
            # Anthropic can stream multiple text blocks; concatenate
            text_content += (value or "")
        elif block_type == "tool_use":
            if hasattr(block, "dict"):
                tool_use = block.dict()
            elif isinstance(block, dict):
                tool_use = block
            else:
                # Best-effort: extract attributes
                tool_use = {
                    "id": getattr(block, "id", None),
                    "name": getattr(block, "name", None),
                    "input": getattr(block, "input", {}),
                }
            tool_calls_oa.append(_convert_tool_use_to_openai(tool_use))

    # Build AssistantMessage
    assistant = AssistantMessage(
        content=text_content or None,
        tool_calls=[
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in tool_calls_oa
        ],
        finish_reason=getattr(response, "stop_reason", None) or getattr(response, "stop_reason", None),
    )

    if generation:
        usage_obj = getattr(response, "usage", None)
        usage = {
            "promptTokens": getattr(usage_obj, "input_tokens", 0) if usage_obj else 0,
            "completionTokens": getattr(usage_obj, "output_tokens", 0) if usage_obj else 0,
            "totalTokens": (
                (getattr(usage_obj, "input_tokens", 0) + getattr(usage_obj, "output_tokens", 0))
                if usage_obj
                else 0
            ),
        }

        # For logging tool calls, parse args for readability
        tool_calls_log = []
        for tc in tool_calls_oa:
            args_str = tc["function"]["arguments"]
            try:
                parsed_args = json.loads(args_str)
            except Exception:
                parsed_args = args_str
            tool_calls_log.append(
                {
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "arguments": parsed_args,
                }
            )

        log_output = {"assistant": assistant.content or "", "tool_calls": tool_calls_log}
        generation.update(
            output=log_output,
            usage=usage,
            metadata={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "operation": "anthropic.messages.create",
                "provider": "anthropic",
                "latency_ms": (end_time - start_time) * 1000,
                "finish_reason": getattr(response, "stop_reason", None),
                "success": True,
            },
        )
        generation.end()

    return assistant


if __name__ == "__main__":

    async def main():
        msgs = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Say hello and then propose 1 tool call."},
        ]
        # Minimal smoke test; requires ANTHROPIC_API_KEY
        assistant = await call_anthropic_api(
            messages=msgs,
            model="claude-4-sonnet",
            max_tokens=128,
            temperature=0.7,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "demo__echo",
                        "description": "Echo input",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                }
            ],
        )
        print("Response:", assistant.content)
        print("Tool calls:", [tc.name for tc in (assistant.tool_calls or [])])

    asyncio.run(main())


