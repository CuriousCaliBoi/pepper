import time
from typing import Any, List, Optional

import pydantic
from pydantic import Field


class Event(pydantic.BaseModel):
    id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class ToolCall(Event):
    id: str
    name: str
    arguments: str


class ToolCallResult(Event):
    id: str
    name: Optional[str] = None
    result: str | dict | list[dict]


class UserMessage(Event):
    content: str


class SendToUser(Event):
    content: str


class AssistantMessage(Event):
    content: str | None = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None

class Wait(Event):
    content: str


class GenericEvent(Event):
    type: Optional[str] = None
    content: Any

class AgentState(Event):
    events: List[
        ToolCall
        | ToolCallResult
        | UserMessage
        | AssistantMessage
        | GenericEvent
        | SendToUser
        | Wait
    ]
    summary: Optional[str] = None
