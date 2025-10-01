import asyncio
import json
from typing import Dict, List

from episodic import ContextStore
from pepper.llm_client.model import Event
from pepper.llm_client.openai_client import get_openai_client

summarize_prompt = """
You are a conversation summarizer for the Pepper AI assistant system. You will receive a chronological sequence of messages from conversations between users and Pepper's agents (scheduler and worker agents).

{optional_message_structure}

# Summarization Guidelines

When summarizing conversations:

1. **Focus on User Intent**: Prioritize what the user wanted to accomplish
2. **Track Task Completion**: Note which requests were fulfilled vs pending
3. **Preserve Context**: Maintain important details like names, dates, specific requests
4. **Show Agent Actions**: Summarize what Pepper did (sent emails, checked calendar, etc.)
5. **Include Outcomes**: Note results delivered to the user
6. **Highlight Pending Items**: Call out any unfinished tasks or promises
7. **Build on Past Context**: When a past summary is provided, integrate it with new information rather than duplicating it

# Output Format

Structure your summary as:

**User Requests:**
- [List main things user asked for, including both past and recent requests if relevant]

**Actions Taken:**
- [What Pepper/agents actually did - tool calls, searches, etc.]

**Results Delivered:**
- [Information or confirmations sent to user via send_to_user]

**Status:**
- [Completed/Pending/Waiting for user response]

**Key Context:**
- [Important details to remember for future interactions, building on past context]

# Example Summary

**User Requests:**
- Asked for last 5 emails and next 3 meetings with summary
- Requested to send status email to Alice

**Actions Taken:**  
- Retrieved user profile for context
- Fetched recent emails and calendar events in parallel
- Drafted email with subject "Status update" and body "Shipping on track for Friday"

**Results Delivered:**
- Provided combined summary of emails and meetings
- Showed email draft and got user approval
- Sent approved email to alice@example.com

**Status:**
- All requests completed successfully

**Key Context:**
- User prefers concise summaries
- Has upcoming meeting conflicts to watch
- Active email thread with Alice about shipping timeline

Remember: Focus on actionable information and user-visible outcomes. Internal agent coordination details should be condensed unless they affect the user experience. When building on a past summary, avoid redundancy but ensure continuity of context.
"""

scheduler_message_structure = """
# Message Structure Overview

The conversation contains these message types:

## User Messages
- `<user_message>`: Direct input from the human user - the primary driver of conversations
- These represent actual user requests, questions, or responses

## Agent Communications  
- `<send_to_user>`: Messages that Pepper sent directly to the user (user has seen these)
- `<thinking>`: Internal reasoning/planning by agents (user never sees this)
- `<tool_call>`: Function calls made by agents (invisible to user)
- `<tool_result>`: Results returned from tool executions (invisible to user unless relayed)

## External Events
- `<event>`: External notifications (important emails, calendar alerts, etc.)
- These can trigger agent responses and user notifications

## Agent Roles
- **Scheduler Agent (Pepper)**: The main orchestrator that communicates with users and delegates work
- **Worker Agent**: Execution specialist that performs specific tasks using tools (never talks to users directly)
"""


class Summarizer:
    def __init__(self):
        pass

    async def _summarize(
        self, text: str, message_structure: str = "", past_summary: str = None
    ) -> str:
        openai_client = await get_openai_client()
        system_prompt = summarize_prompt.format(
            optional_message_structure=message_structure
        )
        user_prompt = "Please summarize the conversation:\n\n"
        if past_summary:
            user_prompt += f"The past summary is: {past_summary}\n\n"
        user_prompt += "The following is the new conversation:\n\n" + text
        response = await openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content

    def _format_event(self, event: Event) -> str:
        match event.__class__.__name__:
            case "UserMessage":
                return f"<user_message>{event.content}</user_message>\n"
            case "AssistantMessage":
                return f"<thinking>{event.content}</thinking>\n"
            case "ToolCall":
                return f"<tool_call>id: {event.id} Function: {event.name} Arguments: {event.arguments}</tool_call>\n"
            case "ToolCallResult":
                return f"<tool_result>id: {event.id} Return: {event.result}</tool_result>\n"
            case "GenericEvent":
                return f"<event>type: {event.type} content: {event.content}</event>\n"
            case "SendToUser":
                return f"<send_to_user>{event.content}</send_to_user>\n"
            case _:
                return f"<event>type: {event.__class__.__name__} content: {event.model_dump_json()}</event>\n"

    async def summarize_conversation(
        self,
        events: List[Event],
        past_summary: str = None,
        use_message_structure: bool = False,
    ) -> str:
        message_structure = ""
        if use_message_structure:
            message_structure = scheduler_message_structure

        text = ""
        for event in events:
            text += self._format_event(event)

        return await self._summarize(text, message_structure, past_summary)
