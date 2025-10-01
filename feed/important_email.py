import asyncio
import os
from datetime import datetime
from typing import Any, Dict, Tuple

from episodic import ContextStore, ContextSubscriber, ContextUpdate
from pepper.tool.utils.email_utils import normalize_gmail_message


class ImportantEmailFeed:
    def __init__(self, context_store: ContextStore):
        self.cs = context_store
        self.subscriber = ContextSubscriber(self.cs)

    async def start(self):
        await self.cs.health_check()
        self.subscriber.on_context_update(namespaces=["composio"])(
            self.handle_composio_update
        )
        await self.subscriber.start()

    async def handle_composio_update(self, update: ContextUpdate):
        email_data = update.context.data

        print("[IMPORTANT EMAIL FEED] Received A New Email")

        # Handle composio webhook format (payload already contains the Gmail message)
        if isinstance(email_data, dict) and "payload" in email_data:
            actual_email_data = email_data.get("payload") or {}
            email_content = normalize_gmail_message(
                actual_email_data, preview_chars=500, include_body=True
            )
        elif isinstance(email_data, dict) and "data" in email_data:
            # Handle wrapped response format from composio
            messages = email_data.get("data", {}).get("messages", [])
            if messages and len(messages) > 0:
                email_content = normalize_gmail_message(
                    messages[0], preview_chars=500, include_body=True
                )
            else:
                return  # No messages to process
        else:
            # Direct message format
            email_content = normalize_gmail_message(
                email_data, preview_chars=500, include_body=True
            )

        print(
            "[IMPORTANT EMAIL FEED] Successfully normalized email content: ",
            email_content,
        )

        is_urgent, is_important = is_urgent_or_important(email_content)

        if is_urgent or is_important:
            email_reminder = create_email_reminder(
                email_content, is_urgent, is_important
            )

            # Add urgency tags for easier filtering
            tags = ["important_email"]
            if is_urgent:
                tags.append("urgent")
            if is_important:
                tags.append("important")

            print("[IMPORTANT EMAIL FEED] Sending Email Reminder: ", email_reminder)
            await self.cs.store(
                context_id=f"important_email_{update.context.id}",
                data={"content": email_reminder},
                tags=tags,
                namespace="important_email",
            )


def is_urgent_or_important(email_content: Dict[str, Any]) -> Tuple[bool, bool]:
    """Check if email is urgent or important based on content and metadata."""
    is_urgent = False
    is_important = False

    # Check subject line for urgency/importance indicators
    subject = email_content.get("subject", "").lower()
    body = email_content.get("body", email_content.get("preview", "")).lower()

    # Urgent indicators
    urgent_keywords = [
        "urgent",
        "asap",
        "immediately",
        "critical",
        "emergency",
        "time sensitive",
        "deadline today",
        "expires today",
        "action required",
    ]
    for keyword in urgent_keywords:
        if keyword in subject or keyword in body:
            is_urgent = True
            break

    # Important indicators
    important_keywords = [
        "important",
        "priority",
        "attention needed",
        "please review",
        "confidential",
        "meeting",
        "invoice",
        "payment",
        "contract",
        "deadline",
        "reminder",
        "follow up",
        "action item",
    ]
    for keyword in important_keywords:
        if keyword in subject or keyword in body:
            is_important = True
            break

    # Check labels for importance
    labels = email_content.get("labels", [])
    if "IMPORTANT" in labels or "STARRED" in labels:
        is_important = True

    return is_urgent, is_important


def create_email_reminder(
    email_content: Dict[str, Any], is_urgent: bool, is_important: bool
) -> str:
    """Create a text reminder from email content."""
    sender = email_content.get("from", "Unknown sender")
    subject = email_content.get("subject", "No subject")
    preview = email_content.get("preview", "")
    body = email_content.get("body", preview)
    timestamp = email_content.get("timestamp", "")

    # Convert timestamp if it's in milliseconds
    if isinstance(timestamp, (int, str)) and timestamp:
        try:
            ts = int(timestamp) / 1000 if len(str(timestamp)) > 10 else int(timestamp)
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except:
            date_str = str(timestamp)
    else:
        date_str = "Unknown time"

    # Create urgency prefix
    urgency_prefix = ""
    if is_urgent and is_important:
        urgency_prefix = "🚨 URGENT & IMPORTANT: "
    elif is_urgent:
        urgency_prefix = "⚡ URGENT: "
    elif is_important:
        urgency_prefix = "⭐ IMPORTANT: "

    # Truncate body for summary
    summary = body[:300] + "..." if len(body) > 300 else body

    # Build reminder text
    reminder_parts = [
        f"{urgency_prefix}Email from {sender}",
        f"Subject: {subject}",
        f"Received: {date_str}",
        f"Preview: {summary}",
    ]

    if email_content.get("hasAttachments"):
        reminder_parts.append("📎 Has attachments")

    return "\n".join(reminder_parts)


if __name__ == "__main__":
    endpoint = os.environ.get("CONTEXT_STORE_ENDPOINT", "http://localhost:8000")
    api_key = os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here")

    async def main():
        context_store = ContextStore(endpoint=endpoint, api_key=api_key)
        important_email_feed = ImportantEmailFeed(context_store)
        await important_email_feed.start()

        while True:
            await asyncio.sleep(10)

    asyncio.run(main())
