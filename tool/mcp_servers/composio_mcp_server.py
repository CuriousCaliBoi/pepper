import json
import os
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from pepper.constants import COMPOSIO_USER_ID

try:
    from composio import Composio  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    Composio = None  # type: ignore


mcp = FastMCP("composio-mcp-server")


COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY")

def _ensure_client() -> Composio:
    if Composio is None:
        raise RuntimeError(
            "Composio SDK is not installed. Please add 'composio' to requirements and install dependencies."
        )
    if not COMPOSIO_API_KEY:
        raise RuntimeError("COMPOSIO_API_KEY is not set in the environment.")
    return Composio(api_key=COMPOSIO_API_KEY)


def _json_default(o: Any):
    try:
        if hasattr(o, "model_dump"):
            return o.model_dump()
        if hasattr(o, "dict"):
            return o.dict()
        if hasattr(o, "to_dict"):
            return o.to_dict()
        return getattr(o, "__dict__", str(o))
    except Exception:
        return str(o)


def _stringify(result: Any) -> str:
    try:
        # Common JSON-serializable types
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, default=_json_default)

        # Pydantic v2 / v1 or custom SDK models
        for attr in ("model_dump", "dict", "to_dict"):
            if hasattr(result, attr):
                try:
                    obj = getattr(result, attr)()
                    return json.dumps(obj, ensure_ascii=False, default=_json_default)
                except Exception:
                    pass

        # Known Composio ToolExecuteResponse-like objects
        if hasattr(result, "data") and hasattr(result, "successful"):
            obj = {
                "data": getattr(result, "data"),
                "successful": bool(getattr(result, "successful")),
                "error": getattr(result, "error", None),
            }
            # Preserve optional ids if present
            for k in ("log_id", "session_info"):
                if hasattr(result, k):
                    obj[k] = getattr(result, k)
            return json.dumps(obj, ensure_ascii=False, default=_json_default)

        # Fallback to string
        return str(result)
    except Exception:
        return str(result)


def _execute(
    action: str, arguments: Dict[str, Any], composio_user_id: Optional[str] = None
) -> str:
    try:
        client = _ensure_client()
        effective_user = COMPOSIO_USER_ID
        res = client.client.tools.execute(
            action, user_id=effective_user, arguments=arguments or {}
        )
        return _stringify(res)
    except Exception as e:
        return f"[ERROR]: Failed to execute {action}: {e}"


async def gmail_fetch_emails(
    ids_only: bool = False,
    include_payload: bool = True,
    include_spam_trash: bool = False,
    label_ids: List[str] | None = None,
    max_results: int = 1,
    page_token: str | None = None,
    query: str | None = None,
    verbose: bool = True,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Fetch Gmail messages with optional filters (FetchEmailsRequest).

    Args:
        ids_only (default False): If true, return only message IDs and thread IDs (fastest).
        include_payload (default True): If true, include full payload (headers, body, attachments); false for metadata only.
        include_spam_trash (default False): If true, include messages from SPAM and TRASH.
        label_ids (default None): Filter by label IDs. Common: INBOX, SPAM, TRASH, UNREAD, STARRED, IMPORTANT,
                   CATEGORY_PRIMARY (alias CATEGORY_PERSONAL), CATEGORY_SOCIAL, CATEGORY_PROMOTIONS,
                   CATEGORY_UPDATES, CATEGORY_FORUMS.
        max_results (default 1): Max messages per page (1–500).
        page_token (default None): Token for pagination from previous response's nextPageToken.
        query (default None): Gmail advanced search query (e.g., "from:user subject:meeting", supports from:, to:, subject:,
               label:, has:attachment, is:unread, after:YYYY/MM/DD, before:YYYY/MM/DD, AND/OR/NOT, quoted phrases).
        verbose (default True): If false, optimized concurrent metadata fetching for faster performance; if true, detailed fetching.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string containing fetched messages or metadata depending on flags, or an
             error string prefixed with "[ERROR]:" if the call fails.

    """
    # Clamp per schema: max_results in [1, 500]
    max_results = max(1, min(max_results, 500))

    args: Dict[str, Any] = {
        "ids_only": ids_only,
        "include_payload": include_payload,
        "include_spam_trash": include_spam_trash,
        "max_results": max_results,
        "verbose": verbose,
        "user_id": gmail_user_id,
    }
    if label_ids:
        args["label_ids"] = label_ids
    if page_token:
        args["page_token"] = page_token
    if query:
        args["query"] = query
    return _execute("GMAIL_FETCH_EMAILS", args, composio_user_id)


@mcp.tool()
async def gmail_fetch_emails_compact(
    ids_only: bool = False,
    include_payload: bool = True,
    include_spam_trash: bool = False,
    label_ids: List[str] | None = None,
    max_results: int = 1,
    page_token: str | None = None,
    query: str | None = None,
    verbose: bool = True,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
    preview_chars: int = 160,
    include_body: bool = False,
) -> str:
    """Fetch Gmail messages and return compact, human‑friendly objects.

    Returns a JSON string with shape:
      {
        "successful": bool,
        "error": str | null,
        "data": {
          "messages": [
            {
              "id": str,
              "threadId": str,
              "timestamp": str,
              "from": str,
              "to": str,
              "subject": str,
              "labels": list[str],
              "hasAttachments": bool,
              "preview": str,
              "body"?: str
            }
          ],
          "nextPageToken": str | null,
          "resultSizeEstimate": int | null
        }
      }

    Args:
        ids_only (default False): If true, only message IDs and thread IDs are fetched (fastest).
        include_payload (default True): Include Gmail payload so the body can be decoded; set False for metadata-only.
        include_spam_trash (default False): If true, include messages from SPAM and TRASH.
        label_ids (default None): Filter by label IDs (e.g., INBOX, UNREAD, IMPORTANT, CATEGORY_PRIMARY, etc.).
        max_results (default 1): Maximum messages to retrieve (1–500).
        page_token (default None): Token for paginated retrieval from a previous response's nextPageToken.
        query (default None): Gmail advanced search query (e.g., "from:user subject:meeting"). Supports operators like
            from:, to:, subject:, label:, has:attachment, is:unread, after:YYYY/MM/DD, before:YYYY/MM/DD, AND/OR/NOT.
        verbose (default True): If false, uses optimized metadata fetching; if true, uses detailed fetching.
        gmail_user_id (default "me"): Gmail API user context ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).
        preview_chars (default 160): Maximum characters for the preview text included in each message.
        include_body (default False): If true, include a truncated plain‑text body (up to ~4× preview length).

    Notes:
        - If include_payload is False, body extraction is skipped and preview may fall back to provider previews.
        - HTML bodies are decoded and stripped to plain text; tracking markup is removed and whitespace collapsed.
    """
    # Clamp per schema: max_results in [1, 500]
    max_results = max(1, min(max_results, 500))

    args: Dict[str, Any] = {
        "ids_only": ids_only,
        "include_payload": include_payload,
        "include_spam_trash": include_spam_trash,
        "max_results": max_results,
        "verbose": verbose,
        "user_id": gmail_user_id,
    }
    if label_ids:
        args["label_ids"] = label_ids
    if page_token:
        args["page_token"] = page_token
    if query:
        args["query"] = query

    raw = _execute("GMAIL_FETCH_EMAILS", args, composio_user_id)
    try:
        from pepper.tool.utils.email_utils import (
            compact_fetch_emails_response,
        )  # type: ignore

        return compact_fetch_emails_response(
            raw, preview_chars=preview_chars, include_body=include_body
        )
    except Exception:
        # Fallback: return raw on any failure to compact
        return raw


@mcp.tool()
async def gmail_create_draft(
    recipient_email: str,
    subject: str,
    body: str,
    cc: List[str] | None = None,
    bcc: List[str] | None = None,
    extra_recipients: List[str] | None = None,
    is_html: bool = False,
    thread_id: str | None = None,
    attachment: Dict[str, Any] | None = None,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Create a Gmail draft (CreateEmailDraftRequest).

    Args:
        recipient_email (required): Primary recipient email address.
        subject (required): Email subject line.
        body (required): Email body content (plain text or HTML if is_html=True).
        cc (default None): Carbon copy recipients.
        bcc (default None): Blind carbon copy recipients.
        extra_recipients (default None): Additional "To" recipients (not CC/BCC).
        is_html (default False): Set true if body contains HTML.
        thread_id (default None): Existing Gmail thread ID to reply to; omit for new thread.
        attachment (default None): File attachment object with required fields {name, mimetype, s3key}.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string describing the created draft (e.g., draft id, message id) or an
             error string prefixed with "[ERROR]:" if the call fails.

    """
    args: Dict[str, Any] = {
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "is_html": is_html,
        "user_id": gmail_user_id,
    }
    if cc:
        args["cc"] = cc
    if bcc:
        args["bcc"] = bcc
    if extra_recipients:
        args["extra_recipients"] = extra_recipients
    if thread_id:
        args["thread_id"] = thread_id
    if attachment is not None:
        # Basic validation per schema: name, mimetype, s3key
        required_keys = {"name", "mimetype", "s3key"}
        if not isinstance(attachment, dict) or not required_keys.issubset(
            attachment.keys()
        ):
            return "[ERROR]: Invalid attachment. Expected keys: name, mimetype, s3key"
        args["attachment"] = attachment
    # Action name guess based on schema and conventions
    return _execute("GMAIL_CREATE_EMAIL_DRAFT", args, composio_user_id)


@mcp.tool()
async def gmail_delete_draft(
    draft_id: str,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Delete a Gmail draft by ID (DeleteDraftRequest).

    Args:
        draft_id (required): Immutable draft ID to delete.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string indicating deletion result/status, or an error string prefixed
             with "[ERROR]:" if the call fails.

    """
    args = {"draft_id": draft_id, "user_id": gmail_user_id}
    return _execute("GMAIL_DELETE_DRAFT", args, composio_user_id)


@mcp.tool()
async def gmail_forward_message(
    message_id: str,
    recipient_email: str,
    additional_text: str | None = None,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Forward an existing Gmail message (ForwardMessageRequest).

    Args:
        message_id (required): ID of the message to forward.
        recipient_email (required): Email address to forward to.
        additional_text (default None): Optional extra text included before forwarded content.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string describing the forward/send operation result, or an error string
             prefixed with "[ERROR]:" if the call fails.

    """
    args: Dict[str, Any] = {
        "message_id": message_id,
        "recipient_email": recipient_email,
        "user_id": gmail_user_id,
    }
    if additional_text:
        args["additional_text"] = additional_text
    return _execute("GMAIL_FORWARD_MESSAGE", args, composio_user_id)


@mcp.tool()
async def gmail_send_email(
    recipient_email: str,
    body: str,
    subject: str | None = None,
    cc: List[str] | None = None,
    bcc: List[str] | None = None,
    extra_recipients: List[str] | None = None,
    is_html: bool = False,
    attachment: Dict[str, Any] | None = None,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Send an email via Gmail (SendEmailRequest).

    Args:
        recipient_email (required): Primary recipient email address.
        body (required): Email content (plain text or HTML if is_html=True).
        subject (default None): Optional subject line (nullable).
        cc (default None): Carbon copy recipients.
        bcc (default None): Blind carbon copy recipients.
        extra_recipients (default None): Additional "To" recipients (not CC/BCC).
        is_html (default False): Set true if body contains HTML.
        attachment (default None): File attachment object with required fields {name, mimetype, s3key}.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string describing the sent message (e.g., id, threadId), or an error string
             prefixed with "[ERROR]:" if the call fails.

    """
    args: Dict[str, Any] = {
        "recipient_email": recipient_email,
        "body": body,
        "is_html": is_html,
        "user_id": gmail_user_id,
    }
    if subject is not None:
        args["subject"] = subject
    if cc:
        args["cc"] = cc
    if bcc:
        args["bcc"] = bcc
    if extra_recipients:
        args["extra_recipients"] = extra_recipients
    if attachment is not None:
        required_keys = {"name", "mimetype", "s3key"}
        if not isinstance(attachment, dict) or not required_keys.issubset(
            attachment.keys()
        ):
            return "[ERROR]: Invalid attachment. Expected keys: name, mimetype, s3key"
        args["attachment"] = attachment
    return _execute("GMAIL_SEND_EMAIL", args, composio_user_id)


@mcp.tool()
async def gmail_search_people(
    query: str,
    pageSize: int = 10,
    person_fields: str = "emailAddresses,names,phoneNumbers",
    other_contacts: bool = True,
    composio_user_id: str | None = None,
) -> str:
    """Search contacts by query (SearchPeopleRequest).

    Args:
        query (required): Matches names, nicknames, email addresses, phone numbers, organization fields.
        pageSize (default 10): Max results to return (0–30; values >30 capped by the API).
        person_fields (default "emailAddresses,names,phoneNumbers"): Comma-separated fields to return. If
            other_contacts is true, only emailAddresses, names, phoneNumbers are allowed.
        other_contacts (default True): Include "Other Contacts" (interacted but not explicitly saved). If false, only primary contacts.
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string containing people search results, or an error string prefixed with
             "[ERROR]:" if the call fails.

    """
    # Clamp per schema: pageSize in [0, 30]
    pageSize = max(0, min(pageSize, 30))

    args: Dict[str, Any] = {
        "query": query,
        "pageSize": pageSize,
        "person_fields": person_fields,
        "other_contacts": other_contacts,
    }
    return _execute("GMAIL_SEARCH_PEOPLE", args, composio_user_id)


@mcp.tool()
async def gmail_send_draft(
    draft_id: str,
    gmail_user_id: str = "me",
    composio_user_id: str | None = None,
) -> str:
    """Send a Gmail draft by ID (SendDraftRequest).

    Args:
        draft_id (required): The ID of the draft to send.
        gmail_user_id (default "me"): Gmail API user context to execute against ("me" or an email address).
        composio_user_id (default COMPOSIO_USER_ID): Composio user id (execution context for the action).

    Returns:
        str: JSON string describing the sent message (e.g., id, threadId), or an error string
             prefixed with "[ERROR]:" if the call fails.

    """
    args: Dict[str, Any] = {
        "draft_id": draft_id,
        "user_id": gmail_user_id,
    }
    return _execute("GMAIL_SEND_DRAFT", args, composio_user_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
