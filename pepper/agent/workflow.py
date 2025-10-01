import asyncio
import json
from typing import Any, Dict, Optional, List

from pepper.constants import AGENT_DIR
from pepper.llm_client.llm_client import create_completion
from pepper.llm_client.model import AssistantMessage, ToolCallResult
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager

WORKFLOW_SYSTEM_PROMPT_TEMPLATE = (
    AGENT_DIR / "prompt" / "workflow_system_prompt.md"
).read_text(encoding="utf-8")
TOOL_CONFIG_PATH = AGENT_DIR / "tool" / "workflow_tools.yaml"

MODEL = "gpt-4.1"


class WorkflowAgent:
    def __init__(self, config_path: str = TOOL_CONFIG_PATH):
        """
        Initialize a WorkflowAgent that can execute various workflows.
        """
        # Load workflow tools configuration (includes worker agent)
        tool_config = load_tools_yaml(config_path)
        tool_resolved = build_stdio_params(tool_config)
        self.tool_manager = ToolManager(tool_resolved)
        self.tools = None
        self.max_steps = 15  # Higher limit for complex workflows

    async def _ensure_tools(self):
        if self.tools is None:
            self.tools = await self.tool_manager.list_openai_tools()
            # Add the workflow completion tool
            self.tools += [
                {
                    "type": "function",
                    "function": {
                        "name": "return_workflow_output",
                        "description": "Return the final output of the workflow in the specified format.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "output": {
                                    "type": "string",
                                    "description": "The final workflow output in the specified format",
                                }
                            },
                            "required": ["output"],
                        },
                    },
                },
            ]

    async def execute(self, task: str, output_format: str) -> str:
        """
        Execute the workflow and return the formatted output.

        Args:
            task: The workflow task description
            output_format: The expected output format specification

        Returns:
            str: The workflow output in the specified format
        """
        await self._ensure_tools()

        # Prepare the system prompt with task and output format
        system_prompt = WORKFLOW_SYSTEM_PROMPT_TEMPLATE.replace(
            "[TASK_PLACEHOLDER]", task
        ).replace("[OUTPUT_FORMAT_PLACEHOLDER]", output_format)

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Execute the workflow as specified in your task definition.",
            },
        ]

        steps = 0

        while steps < self.max_steps:
            steps += 1
            # Call OpenAI API to get the next action
            assistant_msg: AssistantMessage = await create_completion(
                messages, MODEL, 8000, 0.2, self.tools, name="workflow_call"
            )
            # Append the assistant message to the conversation
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in assistant_msg.tool_calls
                if assistant_msg.tool_calls
            ]

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content,
                    "tool_calls": tool_calls,
                }
            )

            # Check if the assistant made any tool calls
            if assistant_msg.tool_calls:
                tool_call_tasks = []
                for tool_call in assistant_msg.tool_calls:
                    fn_name = tool_call.name
                    fn_args = tool_call.arguments

                    # Check if this is the workflow completion tool
                    if fn_name == "return_workflow_output":
                        try:
                            payload = (
                                json.loads(fn_args)
                                if isinstance(fn_args, str)
                                else fn_args
                            )
                        except Exception:
                            payload = {}
                        output = (payload or {}).get("output", "")
                        return output
                    else:
                        tool_call_tasks.append(self.tool_manager.call_openai_tool(tool_call))
                
                if tool_call_tasks:
                    tool_result_msgs: List[ToolCallResult] = await asyncio.gather(*tool_call_tasks)

                    for tool_result_msg in tool_result_msgs:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_result_msg.id,
                                "content": tool_result_msg.result,
                            }
                        )

        # Fallback: no workflow output produced
        last_assistant = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                last_assistant = msg.get("content")
                break
        return last_assistant or "Workflow failed to complete within step limit."
