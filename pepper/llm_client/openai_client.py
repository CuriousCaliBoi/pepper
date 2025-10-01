import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from langfuse import Langfuse
from openai import AsyncOpenAI

from pepper.constants import TOOL_DIR
from pepper.llm_client.model import (
    AssistantMessage,
    ToolCall,
    ToolCallResult,
    UserMessage,
)
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager

openai_client = None
langfuse_client = None


async def get_openai_client():
    global openai_client
    if openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; unable to initialize OpenAI client"
            )
        openai_client = AsyncOpenAI(api_key=api_key)
        # Perform a lightweight sanity check to ensure credentials are usable
        try:
            await openai_client.models.list()
        except Exception as e:
            openai_client = None
            raise RuntimeError(
                f"Failed to validate OpenAI client (check API key/network): {e}"
            ) from e
    return openai_client


async def get_langfuse_client():
    global langfuse_client
    if langfuse_client is None:
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        if not secret_key or not public_key:
            # Return None if Langfuse is not configured instead of raising an error
            return None
        try:
            langfuse_client = Langfuse(
                secret_key=secret_key, public_key=public_key, host=host
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Langfuse client: {e}") from e
    return langfuse_client


async def call_openai_api(
    messages, model, max_tokens, temperature, tools, name="openai_api"
) -> AssistantMessage:
    import time

    client = await get_openai_client()
    langfuse_client = await get_langfuse_client()

    # Only use Langfuse if it's available
    generation = None
    if langfuse_client:
        # Prepare metadata for Langfuse generation
        metadata = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "operation": "chat.completions.create",
        }
        generation = langfuse_client.start_generation(
            name=name,
            model=model,
            input=messages,
            metadata=metadata,
        )

    start_time = time.time()
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
    )
    end_time = time.time()

    # Return the assistant message as-is from the API response
    assistant_message = response.choices[0].message
    response_msg = {
        "role": "assistant",
        "content": assistant_message.content,
    }

    if hasattr(assistant_message, "tool_calls") and assistant_message.tool_calls:
        response_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in assistant_message.tool_calls
        ]

    # Only log to Langfuse if it's available
    if generation:
        usage = {
            "promptTokens": getattr(
                getattr(response, "usage", None), "prompt_tokens", 0
            ),
            "completionTokens": getattr(
                getattr(response, "usage", None), "completion_tokens", 0
            ),
            "totalTokens": getattr(getattr(response, "usage", None), "total_tokens", 0),
        }

        # Build a structured output for Langfuse logging
        tool_calls_log = []
        if getattr(response.choices[0].message, "tool_calls", None) is not None:
            for tool_call in response.choices[0].message.tool_calls:
                args_str = getattr(
                    getattr(tool_call, "function", None), "arguments", ""
                )
                try:
                    parsed_args = json.loads(args_str or "{}")
                except Exception:
                    parsed_args = args_str or ""
                tool_calls_log.append(
                    {
                        "id": getattr(tool_call, "id", None),
                        "name": getattr(
                            getattr(tool_call, "function", None), "name", None
                        ),
                        "arguments": parsed_args,
                    }
                )

        log_output = {
            "assistant": assistant_message.content or "",
            "tool_calls": tool_calls_log,
        }

        generation.update(
            output=log_output,
            usage=usage,
            metadata={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "operation": "chat.completions.create",
                "latency_ms": (end_time - start_time) * 1000,
                "finish_reason": response.choices[0].finish_reason,
                "success": True,
            },
        )
        generation.end()

    # Convert the response to the AssistantMessage
    assistant_message = AssistantMessage(
        content=response_msg["content"],
        tool_calls=[
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in response_msg.get("tool_calls", [])
        ],
        finish_reason=response.choices[0].finish_reason,
    )

    return assistant_message


if __name__ == "__main__":

    async def main():
        messages = [
            {
                "role": "user",
                "content": "First tell me what's your name, and then call 2 tools of your choice in parallel",
            }
        ]
        model = "gpt-4.1"
        servers = load_tools_yaml(str(TOOL_DIR / "tools.yaml"))
        resolved = build_stdio_params(servers)
        tool_manager = ToolManager(resolved)
        tools = await tool_manager.list_openai_tools()

        # Test the function
        llm_response = await call_openai_api(messages, model, 1000, 1, tools)
        print("Response:", llm_response.content)
        print("Finish reason:", llm_response.finish_reason)

    asyncio.run(main())
