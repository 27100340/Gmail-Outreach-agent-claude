"""
Gmail API tool handlers for the outreach monitoring agent.

Each handler takes a dict of parameters (from the agent's tool call),
executes the corresponding Gmail API operation, and returns a JSON string.
"""

import json
import base64
from email.mime.text import MIMEText


def handle_gmail_search(gmail, params):
    """Search Gmail and return message metadata."""
    query = params["query"]
    max_results = params.get("max_results", 20)

    results = gmail.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    output = []

    for msg in messages:
        detail = gmail.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"]
        ).execute()

        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        output.append({
            "id": msg["id"],
            "threadId": msg["threadId"],
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "message_id": headers.get("Message-ID", ""),
            "snippet": detail.get("snippet", "")
        })

    return json.dumps(output, indent=2)


def handle_gmail_get_thread(gmail, params):
    """Retrieve all messages in an email thread."""
    thread_id = params["thread_id"]

    thread = gmail.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()

    msgs = []
    for msg in thread["messages"]:
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

        body = ""
        payload = msg["payload"]
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                    body = base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="replace")
                    break
        elif "body" in payload and "data" in payload["body"]:
            body = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode("utf-8", errors="replace")

        if not body:
            body = msg.get("snippet", "")

        msgs.append({
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "message_id": headers.get("Message-ID", ""),
            "body": body[:2000]
        })

    return json.dumps(msgs, indent=2)


def handle_gmail_create_draft(gmail, params):
    """Create a draft email (never sends)."""
    message = MIMEText(params["body"])
    message["to"] = params["to"]
    message["subject"] = params["subject"]

    if params.get("in_reply_to"):
        message["In-Reply-To"] = params["in_reply_to"]
        message["References"] = params["in_reply_to"]

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()

    return json.dumps({
        "status": "draft_created",
        "draft_id": draft["id"],
        "to": params["to"],
        "subject": params["subject"]
    })


def build_tool_handlers(gmail):
    """Return a dict mapping tool names to handler callables bound to `gmail`."""
    return {
        "gmail_search": lambda params: handle_gmail_search(gmail, params),
        "gmail_get_thread": lambda params: handle_gmail_get_thread(gmail, params),
        "gmail_create_draft": lambda params: handle_gmail_create_draft(gmail, params),
    }
