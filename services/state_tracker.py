import time
from typing import Optional

from pydantic import NonNegativeFloat

from episodic import ContextFilter, ContextStore
from pepper.llm_client.model import (
    AgentState,
    AssistantMessage,
    Event,
    GenericEvent,
    SendToUser,
    ToolCall,
    ToolCallResult,
    UserMessage,
)
from pepper.services.summarizer import Summarizer


class StateTracker:
    def __init__(self, context_store: ContextStore, namespace: Optional[str] = None):
        self.context_store = context_store
        self.namespace = namespace
        self.past_agent_state = None
        self.summarizer = Summarizer()
        self.len_limit = 100
        self.summarize_last_n_events = 60
        self.recent_messages = []
        self.events = []
        self.summary = None
        self.auto_store_every_n_events = 20
        self.auto_store_counter = 0

    async def retrieve_history(self):
        if self.namespace == None:
            return
        latest_state = await self.context_store.query(
            ContextFilter(namespaces=[self.namespace], limit=1)
        )
        if not latest_state:
            return

        latest_state = latest_state[-1]
        self.past_agent_state = AgentState(**latest_state.data)
        self.events = (
            self.past_agent_state.events if self.past_agent_state.events else []
        )
        self.summary = (
            self.past_agent_state.summary if self.past_agent_state.summary else None
        )

    async def add_event(self, event: Event):
        self.events.append(event)
        self.auto_store_counter += 1
        if self.auto_store_counter >= self.auto_store_every_n_events:
            await self.store_events()
            self.auto_store_counter = 0

        if event.__class__.__name__ == "SendToUser":
            self.recent_messages.append(event.content)
            if len(self.recent_messages) > 5:
                self.recent_messages.pop(0)

        if len(self.events) > self.len_limit:
            self.summary = await self.summarizer.summarize_conversation(
                self.events[: self.summarize_last_n_events],
                self.summary,
                use_message_structure=True,
            )
            self.events = self.events[self.summarize_last_n_events :]

    async def store_events(self):
        if self.namespace == None:
            return

        event_group = AgentState(events=self.events, summary=self.summary)
        await self.context_store.store(
            context_id=f"{self.namespace}_{time.time()}",
            data=event_group.model_dump(),
            namespace=self.namespace,
            context_type="AgentState",
        )

    def _format_event(self, event: Event):
        match event.__class__.__name__:
            case "UserMessage":
                return f"<user_message>{event.content}</user_message>"
            case "AssistantMessage":
                if event.content == "WAIT":
                    msgs = []
                else:
                    msgs = [f"<send_to_user>{event.content}</send_to_user>"]
                if event.tool_calls:
                    for tool_call in event.tool_calls:
                        msgs.append(self._format_event(tool_call))
                return "\n".join(msgs)
            case "ToolCall":
                return f"<tool_call>id: {event.id} Function: {event.name} Arguments: {event.arguments}</tool_call>"
            case "ToolCallResult":
                return (
                    f"<tool_result>id: {event.id} Return: {event.result}</tool_result>"
                )
            case "GenericEvent":
                return f'<event type="{event.type}">{event.content}</event>'
            case "Wait":
                return f"<wait>{event.content}</wait>"
            case _:
                return f'<event type="{event.__class__.__name__}">{event.model_dump_json()}</event>'

    def is_meaningful(self, content: str):
        if content in self.recent_messages:
            return False
        if content == "WAIT":
            return False
        return True


class SchedulerStateTracker(StateTracker):
    def __init__(self, context_store: ContextStore):
        super().__init__(context_store, "memory-scheduler")

    @property
    def user_prompt(self):
        if self.summary:
            return (
                "Past conversation summary:\n"
                + self.summary
                + "\n\n"
                + "Recent conversation history:\n"
                + "\n".join([self._format_event(event) for event in self.events])
            )
        else:
            return "Recent conversation history:\n" + "\n".join(
                [self._format_event(event) for event in self.events]
            )


class WorkerStateTracker(StateTracker):
    def __init__(self, context_store: ContextStore, agent_name: Optional[str] = None):
        super().__init__(context_store, "memory-" + agent_name if agent_name else None)

    def _to_openai_format(self, event: Event):
        match event.__class__.__name__:
            case "AssistantMessage":
                msg = {"role": "assistant", "content": event.content}
                if event.tool_calls:
                    msg["tool_calls"] = [
                        self._to_openai_format(tc) for tc in event.tool_calls
                    ]
                return msg
            case "UserMessage":
                return {"role": "user", "content": event.content}
            case "ToolCall":
                return {
                    "id": event.id,
                    "type": "function",
                    "function": {"name": event.name, "arguments": event.arguments},
                }
            case "ToolCallResult":
                return {
                    "role": "tool",
                    "tool_call_id": event.id,
                    "content": event.result,
                }
            case _:
                raise ValueError(f"Unknown event type: {event.__class__.__name__}")

    @property
    def messages(self):
        return [self._to_openai_format(event) for event in self.events]
