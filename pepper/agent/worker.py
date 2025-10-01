import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional, List

from episodic import ContextFilter, ContextStore
from pepper.constants import AGENT_DIR
from pepper.llm_client.llm_client import create_completion
from pepper.llm_client.model import (
    AssistantMessage,
    Event,
    GenericEvent,
    SendToUser,
    ToolCall,
    ToolCallResult,
    UserMessage,
)
from pepper.services.state_tracker import WorkerStateTracker
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager

WORKER_SYSTEM_PROMPT = (AGENT_DIR / "prompt" / "worker_system_prompt.md").read_text(
    encoding="utf-8"
)
TOOL_CONFIG_PATH = AGENT_DIR / "tool" / "worker_tools.yaml"

MODEL = "gpt-4.1"  # Using Claude 3.5 Sonnet via Bedrock

""" Shouldn't add any print statements in this file, as this is used by MCP stdio, any print statements will break the MCP stdio server """


class WorkerAgent:
    def __init__(self, config_path: str = TOOL_CONFIG_PATH):
        tool_config = load_tools_yaml(config_path)
        tool_resolved = build_stdio_params(tool_config)
        self.tool_manager = ToolManager(tool_resolved)
        self.tools = None
        self.max_steps = 10
        self.cs = ContextStore(
            endpoint=os.environ.get("CONTEXT_STORE_ENDPOINT", "http://localhost:8000"),
            api_key=os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here"),
        )

    async def _ensure_tools(self):
        if self.tools is None:
            self.tools = await self.tool_manager.list_openai_tools()
            self.tools += [
                {
                    "type": "function",
                    "function": {
                        "name": "return_final_answer",
                        "description": "Publish the final answer for the current task.",
                        "parameters": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                        },
                    },
                },
            ]

    async def call(self, request: str, agent_name: Optional[str] = None) -> str:
        await self._ensure_tools()
        state_tracker = WorkerStateTracker(self.cs, agent_name)
        await state_tracker.retrieve_history()

        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        past_summary = state_tracker.summary
        system_prompt = WORKER_SYSTEM_PROMPT
        if past_summary:
            system_prompt += f"\n\nThe past summary is: {past_summary}"
        system_message = {"role": "system", "content": system_prompt}

        await state_tracker.add_event(
            UserMessage(
                content=request + f"\n\nCurrent time: {time_str} at UTC timezone"
            )
        )

        steps = 0
        while steps < self.max_steps:
            steps += 1
            # create_completion now returns a single assistant message
            assistant_msg: AssistantMessage = await create_completion(
                [system_message] + state_tracker.messages,
                MODEL,
                8000,
                0.2,
                self.tools,
                name="worker_call",
            )
            # Append the assistant message to the conversation
            return_final_answer = False
            return_final_answer_tool_call = None
            if assistant_msg.tool_calls:
                for tool_call in assistant_msg.tool_calls:
                    if tool_call.name == "return_final_answer":
                        return_final_answer = True
                        return_final_answer_tool_call = tool_call
                        break
            if return_final_answer:
                assistant_msg = AssistantMessage(
                    content=assistant_msg.content,
                    tool_calls=[return_final_answer_tool_call],
                )

            await state_tracker.add_event(assistant_msg)

            if assistant_msg.tool_calls:
                tool_call_tasks = []
                for tool_call in assistant_msg.tool_calls:
                    fn_name = tool_call.name
                    fn_args = tool_call.arguments

                    # Check if this is the final answer tool
                    if fn_name == "return_final_answer":
                        try:
                            payload = (
                                json.loads(fn_args)
                                if isinstance(fn_args, str)
                                else fn_args
                            )
                        except Exception:
                            payload = {}
                        answer = (payload or {}).get("answer", "")
                        if answer == "":
                            answer = fn_args
                        await state_tracker.add_event(
                            ToolCallResult(
                                id=tool_call.id,
                                name=tool_call.name,
                                result="SEND SUCCESSFULLY",
                            )
                        )
                        await state_tracker.store_events()
                        return answer
                    else:
                        # Execute the tool and get the result
                        tool_call_tasks.append(self.tool_manager.call_openai_tool(tool_call))

                if tool_call_tasks:
                    tool_result_msgs: List[ToolCallResult] = await asyncio.gather(*tool_call_tasks)
                    for tool_result_msg in tool_result_msgs:
                        await state_tracker.add_event(tool_result_msg)

        last_assistant = None
        for msg in reversed(state_tracker.messages):
            if msg["role"] == "assistant":
                last_assistant = msg["content"]
                break
        return last_assistant or ""
