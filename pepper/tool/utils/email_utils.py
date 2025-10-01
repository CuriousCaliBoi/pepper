import json
import re
from base64 import urlsafe_b64decode
from typing import Any, Dict, List, Optional


def _b64url_decode_to_bytes(data: str) -> bytes:
    if not isinstance(data, str):
        return b""
    # Add padding if missing
    padding = "=" * (-len(data) % 4)
    try:
        return urlsafe_b64decode(data + padding)
    except Exception:
        return b""


def _qp_decode(data: bytes) -> bytes:
    try:
        import quopri

        return quopri.decodestring(data)
    except Exception:
        return data


def _decode_text_bytes(data: bytes) -> str:
    for enc in ("utf-8", "latin-1", "utf-16"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    # naive tag strip to avoid heavy deps
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    try:
        import html as htmllib

        text = htmllib.unescape(text)
    except Exception:
        pass
    return text


def _decode_gmail_part(part: Dict[str, Any]) -> str:
    body = (part or {}).get("body", {})
    data_str = body.get("data")
    if not data_str:
        return ""
    raw_bytes = _b64url_decode_to_bytes(data_str)
    # Many providers send quoted-printable inside the decoded bytes
    raw_bytes = _qp_decode(raw_bytes)
    return _decode_text_bytes(raw_bytes)


def _gather_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not payload:
        return []
    parts = payload.get("parts") or []
    gathered: List[Dict[str, Any]] = []
    for p in parts:
        mime = (p or {}).get("mimeType", "")
        if mime.startswith("multipart/"):
            gathered.extend(_gather_parts(p))
        else:
            gathered.append(p)
    return gathered


def extract_plain_text_from_payload(payload: Dict[str, Any]) -> str:
    parts = _gather_parts(payload)
    # Prefer text/plain, else text/html
    plain = next((p for p in parts if (p or {}).get("mimeType") == "text/plain"), None)
    if plain:
        return _decode_gmail_part(plain)
    html = next((p for p in parts if (p or {}).get("mimeType") == "text/html"), None)
    if html:
        return _strip_html(_decode_gmail_part(html))
    # Fallback: decode top-level body if present
    if payload.get("body", {}).get("data"):
        return _decode_gmail_part(payload)
    return ""


def truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def normalize_gmail_message(
    message: Dict[str, Any], preview_chars: int = 160, include_body: bool = False
) -> Dict[str, Any]:
    message_id = (
        message.get("messageId") or message.get("message_id") or message.get("id")
    )
    thread_id = message.get("threadId") or message.get("thread_id")
    subject = (
        message.get("subject")
        or (message.get("preview", {}) or {}).get("subject")
        or ""
    )
    sender = message.get("sender") or message.get("from") or ""
    to = message.get("to") or ""
    timestamp = (
        message.get("messageTimestamp")
        or message.get("message_timestamp")
        or message.get("internalDate")
        or ""
    )
    labels = message.get("labelIds") or message.get("label_ids") or []

    # Prefer preview.body if present; else messageText/message_text; else decode payload
    preview_body = (
        (message.get("preview", {}) or {}).get("body")
        or message.get("messageText")
        or message.get("message_text")
        or ""
    )
    if not preview_body and message.get("payload"):
        preview_body = extract_plain_text_from_payload(message.get("payload") or {})

    compact: Dict[str, Any] = {
        "id": message_id or "",
        "threadId": thread_id or "",
        "timestamp": timestamp,
        "from": sender,
        "to": to,
        "subject": subject,
        "labels": labels,
        "preview": truncate(preview_body, preview_chars),
        "hasAttachments": bool(
            message.get("attachmentList") or message.get("attachment_list")
        ),
    }

    if include_body and message.get("payload"):
        body_text = extract_plain_text_from_payload(message.get("payload") or {})
        compact["body"] = truncate(
            body_text, max(0, preview_chars * 4)
        )  # longer cap if requested

    return compact


def compact_fetch_emails_response(
    raw_json_str: str, preview_chars: int = 160, include_body: bool = False
) -> str:
    try:
        data: Dict[str, Any] = json.loads(raw_json_str)
    except Exception:
        # Already a string error from executor
        return raw_json_str

    # Preserve wrapper shape where possible
    successful = bool(data.get("successful", True))
    error = data.get("error")
    next_page = (data.get("data") or {}).get("nextPageToken")
    size_est = (data.get("data") or {}).get("resultSizeEstimate")
    messages = ((data.get("data") or {}).get("messages")) or []

    compact_messages = [
        normalize_gmail_message(m, preview_chars, include_body) for m in messages
    ]

    compact_wrapper = {
        "successful": successful,
        "error": error,
        "data": {
            "messages": compact_messages,
            "nextPageToken": next_page,
            "resultSizeEstimate": size_est,
        },
    }
    return json.dumps(compact_wrapper, ensure_ascii=False)
