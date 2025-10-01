import asyncio
import json
import os
import time
from tzlocal import get_localzone_name
from zoneinfo import ZoneInfo  # Python 3.9+
from datetime import datetime
from episodic import ContextFilter, ContextStore, ContextSubscriber, ContextUpdate
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
    Wait,
)
from pepper.services.state_tracker import SchedulerStateTracker
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager
from pepper.services.user_profile_service import UserProfileService

SCHEDULER_SYSTEM_PROMPT = (
    AGENT_DIR / "prompt" / "scheduler_system_prompt.md"
).read_text(encoding="utf-8")
TOOL_CONFIG_PATH = AGENT_DIR / "tool" / "scheduler_tools.yaml"

MODEL = "gpt-4.1"

class SchedulerAgent:
    def __init__(self, config_path: str = TOOL_CONFIG_PATH):
        tool_config = load_tools_yaml(config_path)
        tool_resolved = build_stdio_params(tool_config)
        self.tool_manager = ToolManager(tool_resolved)
        self.tools = None
        self.max_batch_size = 4

        self.cs = ContextStore(
            endpoint=os.environ.get("CONTEXT_STORE_ENDPOINT", "http://localhost:8000"),
            api_key=os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here"),
        )
        self.user_profile_service = UserProfileService(self.cs)
        self.subscriber = ContextSubscriber(self.cs)

        self.event_queue = asyncio.Queue()
        self.tool_call_queue = asyncio.Queue()

        self.state_tracker = SchedulerStateTracker(self.cs)
        self.debug_enabled = True  # Enable debug logging

    async def log_debug(self, event_type: str, data: dict):
        """Log debug information to context store"""
        if not self.debug_enabled or not self.cs:
            return

        debug_data = {"event_type": event_type, "timestamp": time.time(), "data": data}

        print(f"[SCHEDULER] Debugging event: {debug_data}")
        await self.cs.store(
            context_id=f"scheduler_debug_{event_type}_{time.time()}",
            data=debug_data,
            tags=["scheduler_debug", event_type],
            namespace="scheduler_debug",
            context_type="debug_log",
        )
    
    async def get_user_profile(self):
        result = await self.user_profile_service.get_profile_data()
        if not result:
            result = await self.user_profile_service.refresh()
        return result

    async def start(self):
        await self.cs.health_check()

        await self.state_tracker.retrieve_history()

        self.subscriber.on_context_update(
            namespaces=["important_email", "user_message", "reminder.inbox"]
        )(self.add_to_queue)
        self.tools = await self.tool_manager.list_openai_tools()
        self.tools += [
            {
                "type": "function",
                "function": {
                    "name": "wait",
                    "description": "No-op tool that yields control and does nothing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Optional note about what you are waiting for",
                            }
                        },
                    },
                },
            },
        ]
        await self.subscriber.start()

        print(f"[SCHEDULER] Getting user profile, if this is the first time, it might take a while")
        await self.get_user_profile()

        print(f"[SCHEDULER] Scheduler agent started! Ready to receive messages")
        await asyncio.gather(self.tool_call_task(), self.schedule_loop())

    async def stop(self):
        await self.state_tracker.store_events()
        await self.subscriber.stop()
        await self.cs.close()

    async def schedule_loop(self):
        """Main loop that waits for triggers before processing steps"""
        while True:
            await self.step()

    async def tool_call_task(self):

        async def schedule_tool_call_and_put_result(tool_call: ToolCall):
            await self.log_debug(
                "tool_call_start",
                {"tool_name": tool_call.name, "arguments": tool_call.arguments},
            )
            tool_result: ToolCallResult = await self.tool_manager.call_openai_tool(
                tool_call
            )
            print(f"[SCHEDULER] Get tool result: {tool_result}")
            await self.log_debug(
                "tool_call_result",
                {"tool_name": tool_call.name, "result": tool_result.result},
            )
            await self.event_queue.put(tool_result)

        while True:
            tool_call = await self.tool_call_queue.get()
            asyncio.create_task(schedule_tool_call_and_put_result(tool_call))

    async def add_to_queue(self, update: ContextUpdate):
        data = update.context.data
        if update.namespace == "user_message":
            user_message = data["content"]
            tz_name = get_localzone_name()            # e.g., "America/Los_Angeles"
            local_tz = ZoneInfo(tz_name)  
            now_in_zone = datetime.now(local_tz)
            await self.event_queue.put(UserMessage(content=user_message + f"\n\nUser is in {tz_name}, Current time: {now_in_zone}"))
            await self.log_debug(
                "event_received",
                {"type": "user_message", "content": update.context.data},
            )
        elif update.namespace == "important_email":
            important_email = GenericEvent(type="important_email", content=data)
            await self.event_queue.put(important_email)
            await self.log_debug(
                "event_received",
                {"type": "important_email", "content": update.context.data},
            )
        elif update.namespace == "reminder.inbox":
            reminder_job = GenericEvent(type="reminder_job", content=data)
            await self.event_queue.put(reminder_job)
            await self.log_debug(
                "event_received",
                {"type": "reminder_job", "content": update.context.data},
            )

    async def get_batch_events(self, max_batch_size):
        events = [await self.event_queue.get()]
        while not self.event_queue.empty() and len(events) < max_batch_size:
            new_event = await self.event_queue.get()
            events.append(new_event)
        return events

    async def step(self):
        # Phase 1: Collect events
        events = await self.get_batch_events(self.max_batch_size)
        print(f"[SCHEDULER] Start processing {len(events)} events")
        if not events:
            return

        # Phase 2: Update state and call LLM
        for event in events:
            await self.state_tracker.add_event(event)

        user_profile = await self.get_user_profile()

        messages = [
            {"role": "system", "content": SCHEDULER_SYSTEM_PROMPT + f"\n\nUser profile: {user_profile}"},
            {"role": "user", "content": self.state_tracker.user_prompt},
        ]

        response: AssistantMessage = await create_completion(
            messages, MODEL, 8000, 1, self.tools, name="scheduler_step"
        )

        # Phase 3: Process response
        if response.content:
            await self.state_tracker.add_event(
                AssistantMessage(content=response.content)
            )
            await self.send_to_user(response.content)
            await self.log_debug("send_to_user", {"content": response.content})

        # Phase 4: Handle tool calls
        if not response.tool_calls:
            return

        for tool_call in response.tool_calls:
            fn_name = tool_call.name
            fn_args = tool_call.arguments

            if fn_name == "wait":
                # Track and log wait intention with optional reason
                reason = None
                try:
                    args = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                    reason = (args or {}).get("reason")
                except Exception:
                    reason = None
                await self.state_tracker.add_event(
                    Wait(content=reason or "")
                )
                await self.log_debug("wait", {"reason": reason or ""})
            else:
                await self.state_tracker.add_event(tool_call)
                await self.tool_call_queue.put(tool_call)

    async def send_to_user(self, message):
        await self.cs.store(
            context_id=f"send_to_user_{time.time()}",
            data={"message": message},
            namespace="send_to_user",
            context_type="user_message",
        )


if __name__ == "__main__":

    async def main():
        agent = SchedulerAgent()
        try:
            await agent.start()
        except (KeyboardInterrupt, SystemExit):
            # Handle both Ctrl+C and SIGTERM
            print("[SCHEDULER] Shutting down gracefully...")
        finally:
            # Always save state on exit
            print("[SCHEDULER] Saving state...")
            await agent.stop()
            print("[SCHEDULER] State saved successfully.")

    asyncio.run(main())
