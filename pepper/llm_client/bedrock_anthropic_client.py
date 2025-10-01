import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from langfuse import Langfuse

from pepper.constants import AGENT_DIR
from pepper.llm_client.model import (
    AssistantMessage,
    ToolCall,
    ToolCallResult,
    UserMessage,
)
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager

bedrock_client = None
langfuse_client = None


class BedrockAnthropicClient:
    """Async client for AWS Bedrock Anthropic API"""

    def __init__(self, api_key: str, region: str = "us-east-1"):
        self.api_key = api_key
        self.region = region
        self.base_url = f"https://bedrock-runtime.{region}.amazonaws.com"
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def create_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.0,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create a completion using Bedrock Anthropic API"""
        if not self.session:
            self.session = aiohttp.ClientSession()

        # Convert model name to Bedrock format if needed
        bedrock_model = self._convert_model_name(model)

        # Convert messages to Bedrock format
        bedrock_messages = self._convert_messages_to_bedrock(messages)

        # Build the request payload
        payload = {
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }

        # Add tools if provided (convert OpenAI format to Bedrock format)
        if tools:
            payload["toolConfig"] = {"tools": self._convert_tools_to_bedrock(tools)}

        # Make the API request
        url = f"{self.base_url}/model/{bedrock_model}/converse"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        async with self.session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(
                    f"Bedrock API error (status {response.status}): {error_text}"
                )

            return await response.json()

    def _convert_model_name(self, model: str) -> str:
        """Convert OpenAI model names to Bedrock Anthropic model IDs"""
        model_mapping = {
            "gpt-4": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "gpt-4o": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "gpt-4.1": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "gpt-3.5-turbo": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            # Direct mappings for Claude models
            "claude-3-5-sonnet": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "claude-3-5-haiku": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "claude-3-opus": "us.anthropic.claude-3-opus-20240229-v1:0",
        }
        return model_mapping.get(model, model)

    def _convert_messages_to_bedrock(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI message format to Bedrock format"""
        bedrock_messages = []

        for msg in messages:
            role = msg["role"]

            # Convert role names
            if role == "system":
                # Bedrock doesn't have system role in messages, handle separately
                # For now, prepend to first user message
                continue
            elif role == "assistant":
                bedrock_role = "assistant"
            else:
                bedrock_role = "user"

            bedrock_msg = {"role": bedrock_role, "content": []}

            # Handle content
            if msg.get("content"):
                bedrock_msg["content"].append({"text": msg["content"]})

            # Handle tool calls (assistant messages)
            if msg.get("tool_calls"):
                for tool_call in msg["tool_calls"]:
                    bedrock_msg["content"].append(
                        {
                            "toolUse": {
                                "toolUseId": tool_call["id"],
                                "name": tool_call["function"]["name"],
                                "input": json.loads(tool_call["function"]["arguments"]),
                            }
                        }
                    )

            # Handle tool results (tool messages)
            if role == "tool":
                bedrock_msg = {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": msg.get("tool_call_id"),
                                "content": [{"text": msg.get("content", "")}],
                            }
                        }
                    ],
                }

            bedrock_messages.append(bedrock_msg)

        # Handle system messages by prepending to first user message
        system_content = None
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
                break

        if system_content and bedrock_messages:
            if bedrock_messages[0]["role"] == "user":
                # Prepend system content to first user message
                first_text = bedrock_messages[0]["content"][0].get("text", "")
                bedrock_messages[0]["content"][0][
                    "text"
                ] = f"{system_content}\n\n{first_text}"

        return bedrock_messages

    def _convert_tools_to_bedrock(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Bedrock format"""
        bedrock_tools = []

        for tool in tools:
            if tool["type"] == "function":
                function = tool["function"]
                bedrock_tool = {
                    "toolSpec": {
                        "name": function["name"],
                        "description": function.get("description", ""),
                        "inputSchema": {"json": function.get("parameters", {})},
                    }
                }
                bedrock_tools.append(bedrock_tool)

        return bedrock_tools


async def get_bedrock_client():
    """Get or create the global Bedrock Anthropic client"""
    global bedrock_client
    if bedrock_client is None:
        api_key = os.environ.get("BEDROCK_API_KEY") or os.environ.get("AWS_API_KEY")
        region = os.environ.get("AWS_REGION", "us-east-1")

        if not api_key:
            raise RuntimeError(
                "BEDROCK_API_KEY or AWS_API_KEY is not set; unable to initialize Bedrock client"
            )

        bedrock_client = BedrockAnthropicClient(api_key=api_key, region=region)

        # Perform a lightweight sanity check
        try:
            async with bedrock_client as client:
                # Test with a simple message
                test_response = await client.create_completion(
                    model="claude-3-5-haiku",
                    messages=[{"role": "user", "content": "Hi"}],
                    max_tokens=10,
                    temperature=0.0,
                )
                if "output" not in test_response:
                    raise RuntimeError("Unexpected response format from Bedrock API")
        except Exception as e:
            bedrock_client = None
            raise RuntimeError(
                f"Failed to validate Bedrock client (check API key/network): {e}"
            ) from e

    return bedrock_client


async def get_langfuse_client():
    """Get or create the global Langfuse client"""
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


async def call_bedrock_api(
    messages, model, max_tokens, temperature, tools, name="bedrock_api"
) -> AssistantMessage:
    """Call Bedrock Anthropic API and return AssistantMessage"""
    import time

    client = await get_bedrock_client()
    langfuse_client = await get_langfuse_client()

    # Only use Langfuse if it's available
    generation = None
    if langfuse_client:
        # Prepare metadata for Langfuse generation
        metadata = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "operation": "bedrock.converse",
            "provider": "anthropic",
        }
        generation = langfuse_client.start_generation(
            name=name,
            model=model,
            input=messages,
            metadata=metadata,
        )

    start_time = time.time()

    async with client as bedrock:
        response = await bedrock.create_completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        )

    end_time = time.time()

    # Parse the Bedrock response
    output = response.get("output", {})
    message_content = output.get("message", {})

    # Extract text content
    text_content = ""
    tool_calls = []

    for content_item in message_content.get("content", []):
        if "text" in content_item:
            text_content = content_item["text"]
        elif "toolUse" in content_item:
            tool_use = content_item["toolUse"]
            tool_calls.append(
                {
                    "id": tool_use["toolUseId"],
                    "type": "function",
                    "function": {
                        "name": tool_use["name"],
                        "arguments": json.dumps(tool_use.get("input", {})),
                    },
                }
            )

    # Build response message
    response_msg = {
        "role": "assistant",
        "content": text_content,
    }

    if tool_calls:
        response_msg["tool_calls"] = tool_calls

    # Log to Langfuse if available
    if generation:
        usage = response.get("usage", {})
        usage_data = {
            "promptTokens": usage.get("inputTokens", 0),
            "completionTokens": usage.get("outputTokens", 0),
            "totalTokens": usage.get("totalTokens", 0),
        }

        # Build structured output for Langfuse
        tool_calls_log = []
        for tool_call in tool_calls:
            args_str = tool_call["function"]["arguments"]
            try:
                parsed_args = json.loads(args_str)
            except Exception:
                parsed_args = args_str

            tool_calls_log.append(
                {
                    "id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "arguments": parsed_args,
                }
            )

        log_output = {
            "assistant": text_content,
            "tool_calls": tool_calls_log,
        }

        generation.update(
            output=log_output,
            usage=usage_data,
            metadata={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "operation": "bedrock.converse",
                "provider": "anthropic",
                "latency_ms": (end_time - start_time) * 1000,
                "stop_reason": response.get("stopReason", "unknown"),
                "success": True,
            },
        )
        generation.end()

    # Convert to AssistantMessage
    assistant_message = AssistantMessage(
        content=text_content,
        tool_calls=[
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in tool_calls
        ],
        finish_reason=response.get("stopReason", "stop"),
    )

    return assistant_message


if __name__ == "__main__":

    async def main():
        # Test the Bedrock client
        messages = [
            {
                "role": "user",
                "content": "First tell me what's your name, and then call 2 tools of your choice in parallel",
            }
        ]
        model = "claude-4-sonnet"

        # Load tools if available
        servers = load_tools_yaml(str(AGENT_DIR / "tool" / "worker_tools.yaml"))
        resolved = build_stdio_params(servers)
        tool_manager = ToolManager(resolved)
        tools = await tool_manager.list_openai_tools()

        # Call the Bedrock API
        llm_response = await call_bedrock_api(messages, model, 1000, 1.0, tools)
        print("Response:", llm_response.content)
        print("Tool calls:", llm_response.tool_calls)
        print("Finish reason:", llm_response.finish_reason)

    asyncio.run(main())
