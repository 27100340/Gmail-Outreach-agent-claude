# CLAUDE.md — Gmail Outreach Monitor Agent

## Project Overview

Building an autonomous Gmail outreach monitoring agent using Claude Managed Agents API. The agent runs daily in Anthropic's cloud, checks Gmail for replies from a tracked list of email addresses, produces a report (who replied, who didn't), and on command drafts contextual follow-up emails for non-responders.

**Platform:** Windows 10 (Build 26200.8039)  
**Python:** 3.13.5  
**User:** Baqir (home dir: `C:\Users\Baqir`)

---

## Architecture

```
Windows Task Scheduler (daily trigger)
        │
        ▼
daily_monitor.py (runs on local machine)
        │
        ├── Creates a Managed Agent SESSION via Anthropic API
        │       (agent runs in Anthropic's cloud)
        │
        ├── Sends monitoring prompt with watchlist
        │
        ├── Streams SSE events from the session
        │       │
        │       ├── When agent calls gmail_search, gmail_get_thread, 
        │       │   or gmail_create_draft → local script executes 
        │       │   against Gmail API and returns results
        │       │
        │       └── When agent emits text → captured for report
        │
        └── Saves report to ~/gmail-agent/reports/
```

The agent (model + system prompt + tool definitions) and environment (cloud container config) are persistent resources created once via API. Sessions are ephemeral — one per daily run.

Custom tools (gmail_search, gmail_get_thread, gmail_create_draft) are defined on the agent but executed locally by the Python script. The script intercepts tool_use events, runs the Gmail API call, and posts tool_result events back to the session.

---

## What Has Been Completed

### 1. Anthropic Platform
- [x] Signed into platform.claude.com
- [x] API key obtained and set as environment variable `ANTHROPIC_API_KEY`

### 2. Python Environment
- [x] Python 3.13.5 installed, on PATH
- [x] Libraries installed: `anthropic`, `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`

### 3. Google Cloud Project
- [x] Project created in Google Cloud Console
- [x] Gmail API enabled
- [x] OAuth consent screen configured (External, Testing status)
- [x] Test user added (Baqir's Gmail address)
- [x] `gmail.modify` scope added
- [x] OAuth Desktop App credentials created
- [x] `credentials.json` downloaded and saved to `C:\Users\Baqir\.gmail-agent\credentials.json`

### 4. Gmail OAuth Authentication
- [x] `auth_gmail.py` created and run
- [x] Browser OAuth flow completed
- [x] `token.json` saved to `C:\Users\Baqir\.gmail-agent\token.json`

### 5. Agent & Environment Setup
- [x] `setup_agent.py` created and run — Agent ID saved
- [x] `setup_environment.py` created and run — Environment ID saved
- [x] Both IDs stored in `C:\Users\Baqir\.gmail-agent\agent_config.json`

### 6. Daily Monitor Script
- [x] `daily_monitor.py` created at `C:\Users\Baqir\gmail-agent\daily_monitor.py`

---

## What Still Needs To Be Done

### 7. Testing
- [ ] Run `daily_monitor.py` manually and verify it works end-to-end
- [ ] Debug any SDK method name mismatches (see SDK Note below)
- [ ] Verify Gmail tool calls execute correctly
- [ ] Verify report saves to `~/gmail-agent/reports/`

### 8. Watchlist Configuration
- [ ] Edit `WATCHLIST` in `daily_monitor.py` with actual email addresses to track

### 9. Windows Task Scheduler
- [ ] Create scheduled task to run `daily_monitor.py` daily
- [ ] Program: path to `python.exe` (run `where python` to find it)
- [ ] Arguments: `C:\Users\Baqir\gmail-agent\daily_monitor.py`
- [ ] Start in: `C:\Users\Baqir\gmail-agent`
- [ ] Uncheck "Start only if on AC power"
- [ ] Check "Run task as soon as possible after a missed start"

### 10. Follow-Up Script
- [ ] Create `send_followups.py` — interactive script that:
  - Asks user for non-responder email addresses
  - Creates a session, sends follow-up drafting prompt
  - Agent reads original threads via gmail_get_thread
  - Agent creates drafts via gmail_create_draft
  - Drafts appear in Gmail Drafts folder for manual review/send

### 11. Error Handling & Logging (optional improvements)
- [ ] Add logging to file for scheduled runs
- [ ] Add retry logic for API failures
- [ ] Add token refresh error handling
- [ ] Add notification on failure (email or desktop toast)

---

## File Structure

```
C:\Users\Baqir\
├── .gmail-agent\                          # Config & credentials (sensitive)
│   ├── credentials.json                   # Google OAuth client credentials
│   ├── token.json                         # Google access/refresh tokens (auto-refreshes)
│   └── agent_config.json                  # Agent ID + Environment ID
│
└── gmail-agent\                           # Project directory
    ├── auth_gmail.py                      # One-time: Gmail OAuth flow
    ├── setup_agent.py                     # One-time: create Managed Agent
    ├── setup_environment.py               # One-time: create Environment
    ├── daily_monitor.py                   # Scheduled daily: check for replies
    ├── send_followups.py                  # Manual: draft follow-up emails (TO BE CREATED)
    └── reports\                           # Daily reports saved here
        └── outreach-report-YYYY-MM-DD.md
```

---

## Key IDs and Config

All stored in `C:\Users\Baqir\.gmail-agent\agent_config.json`:

```json
{
  "agent_id": "<AGENT_ID>",
  "agent_version": <VERSION>,
  "environment_id": "<ENVIRONMENT_ID>"
}
```

These are persistent. Never recreate them unless you want to change the agent's system prompt or tools.

---

## Agent Definition

**Model:** claude-sonnet-4-6  
**Beta header:** managed-agents-2026-04-01

### System Prompt (summarized)

The agent monitors a watchlist of email addresses. For daily checks, it searches for outbound emails (to:address is:sent) and inbound replies (from:address), cross-references by threadId, and produces a report with REPLIED / NO REPLY / NO OUTBOUND FOUND sections. For follow-ups, it reads original threads and creates drafts — never sends directly.

### Custom Tools Defined on the Agent

| Tool | Purpose | Executed by |
|------|---------|-------------|
| `gmail_search` | Search Gmail with query syntax (from:, to:, is:sent, newer_than:, etc). Returns message metadata. | Local script via Google API |
| `gmail_get_thread` | Retrieve full email thread by thread ID. Returns all messages with headers and body. | Local script via Google API |
| `gmail_create_draft` | Create a draft email (NOT send). Supports threading via in_reply_to header. | Local script via Google API |

### Built-in Tools (from agent_toolset_20260401)

bash, read, write, edit, glob, grep, web_fetch, web_search — all execute in Anthropic's cloud container.

---

## SDK Note — IMPORTANT

Claude Managed Agents launched April 8, 2026. The Python SDK method names used in the scripts are based on the REST API structure from the official docs:

- `POST /v1/agents` → create agent
- `POST /v1/environments` → create environment  
- `POST /v1/sessions` → create session
- `POST /v1/sessions/{id}/events` → send events
- `GET /v1/sessions/{id}/stream` → SSE stream

The exact Python SDK namespace may not match what was written in the scripts. The scripts use patterns like:

```python
client.beta.agents.create(...)
client.beta.agents.sessions.create(...)
client.beta.agents.sessions.events.create(...)
client.beta.agents.sessions.stream(...)
```

**If these methods don't exist in the installed SDK version:**

1. Run `pip install --upgrade anthropic` first
2. Check what's available: `print(dir(client.beta))`
3. The namespace might be `client.beta.managed_agents.*` instead of `client.beta.agents.*`
4. Worst case, fall back to raw HTTP requests using the `requests` library with the REST endpoints above

All API calls require the beta header: `anthropic-beta: managed-agents-2026-04-01`  
In the SDK, pass `betas=["managed-agents-2026-04-01"]` to each call.

---

## API Costs

| Component | Cost |
|-----------|------|
| Sonnet 4.6 tokens | ~$0.01-0.05 per daily session |
| Managed Agents runtime | $0.08/hour (~$0.01 per 10-min session) |
| Gmail API | Free |
| Google Cloud Project | Free |
| **Monthly estimate** | **~$1-3** |

---

## daily_monitor.py — Full Source

```python
"""
Gmail Outreach Monitor — Daily Check
Runs via Windows Task Scheduler. Creates a Managed Agent session,
sends the monitoring prompt, handles Gmail tool calls locally,
and saves the report.
"""

import anthropic
import json
import os
import sys
import base64
import traceback
from datetime import datetime
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ─── Configuration ───────────────────────────────────────────

CREDS_DIR = os.path.expanduser("~/.gmail-agent")
TOKEN_FILE = os.path.join(CREDS_DIR, "token.json")
CONFIG_FILE = os.path.join(CREDS_DIR, "agent_config.json")
REPORT_DIR = os.path.expanduser("~/gmail-agent/reports")

# Your watchlist — edit this list
WATCHLIST = [
    "person1@example.com",
    "person2@example.com",
    "person3@company.com",
]

# ─── Setup ───────────────────────────────────────────────────

os.makedirs(REPORT_DIR, exist_ok=True)

# Load agent config
with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

AGENT_ID = config["agent_id"]
ENVIRONMENT_ID = config["environment_id"]

# Initialize Gmail
creds = Credentials.from_authorized_user_file(
    TOKEN_FILE, 
    scopes=["https://www.googleapis.com/auth/gmail.modify"]
)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

gmail = build("gmail", "v1", credentials=creds)

# Initialize Anthropic
anthropic_client = anthropic.Anthropic()

# ─── Gmail Tool Handlers ────────────────────────────────────

def handle_gmail_search(params):
    """Execute a Gmail search and return results."""
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


def handle_gmail_get_thread(params):
    """Retrieve a full email thread."""
    thread_id = params["thread_id"]

    thread = gmail.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()

    msgs = []
    for msg in thread["messages"]:
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

        # Extract body text
        body = ""
        payload = msg["payload"]
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    break
        elif "body" in payload and "data" in payload["body"]:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        if not body:
            body = msg.get("snippet", "")

        msgs.append({
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "message_id": headers.get("Message-ID", ""),
            "body": body[:2000]  # Truncate very long emails
        })

    return json.dumps(msgs, indent=2)


def handle_gmail_create_draft(params):
    """Create an email draft."""
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


TOOL_HANDLERS = {
    "gmail_search": handle_gmail_search,
    "gmail_get_thread": handle_gmail_get_thread,
    "gmail_create_draft": handle_gmail_create_draft,
}

# ─── Main Session Logic ─────────────────────────────────────

def run_daily_check():
    today = datetime.now().strftime("%Y-%m-%d")
    report_lines = []

    print(f"[{today}] Starting daily outreach check...")

    # Create a new session
    session = anthropic_client.beta.agents.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        title=f"Daily outreach check {today}",
        betas=["managed-agents-2026-04-01"]
    )
    session_id = session.id
    print(f"Session created: {session_id}")

    # Build the prompt
    watchlist_formatted = "\n".join(f"- {email}" for email in WATCHLIST)
    prompt = f"""Today is {today}. 

Check my Gmail for the status of outreach to the following email addresses.

WATCHLIST:
{watchlist_formatted}

For EACH address above:
1. Search for emails I SENT TO them in the last 7 days: 
   use gmail_search with query "to:<address> is:sent newer_than:7d"
2. Search for emails I RECEIVED FROM them in the last 7 days: 
   use gmail_search with query "from:<address> newer_than:7d"
3. Determine if they replied to any of my outbound emails 
   (matching threadId indicates a reply in the same conversation)

Then produce a final report with these exact sections:

## REPLIED
For each address that replied, list:
- Email address
- Original subject line
- Date of their reply
- Brief snippet of their reply

## NO REPLY  
For each address that has NOT replied, list:
- Email address
- Original subject line (if outbound email exists)
- Date the outbound email was sent
- Number of days since sent

## NO OUTBOUND FOUND
For each address where you found no outbound email from me in the last 7 days, list:
- Email address
- Note: "No outbound email found in last 7 days"

Check every single address. Do not skip any."""

    # Send the prompt
    anthropic_client.beta.agents.sessions.events.create(
        session_id=session_id,
        events=[{
            "type": "user.message",
            "content": [{"type": "text", "text": prompt}]
        }],
        betas=["managed-agents-2026-04-01"]
    )
    print("Prompt sent. Streaming agent response...")

    # Stream and handle events
    with anthropic_client.beta.agents.sessions.stream(
        session_id=session_id,
        betas=["managed-agents-2026-04-01"]
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "agent.tool_use":
                tool_name = event.name
                tool_input = event.input
                tool_use_id = event.id

                if tool_name in TOOL_HANDLERS:
                    print(f"  [Tool call: {tool_name}]")
                    try:
                        result = TOOL_HANDLERS[tool_name](tool_input)
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                        print(f"  [Tool error: {e}]")

                    # Send result back to the agent
                    anthropic_client.beta.agents.sessions.events.create(
                        session_id=session_id,
                        events=[{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": [{"type": "text", "text": result}]
                        }],
                        betas=["managed-agents-2026-04-01"]
                    )
                else:
                    # Built-in tool — agent handles it in the cloud
                    print(f"  [Built-in tool: {tool_name}]")

            elif event_type == "agent.message":
                for block in event.content:
                    if hasattr(block, "text"):
                        print(block.text, end="")
                        report_lines.append(block.text)

            elif event_type == "session.status_idle":
                print("\n\n--- Agent finished ---")
                break

    # Save the report
    report_path = os.path.join(REPORT_DIR, f"outreach-report-{today}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(report_lines))

    print(f"Report saved to: {report_path}")
    return report_path


if __name__ == "__main__":
    try:
        run_daily_check()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
```

---

## setup_agent.py — Full Source

```python
import anthropic
import json
import os

client = anthropic.Anthropic()

agent = client.beta.agents.create(
    name="Gmail Outreach Monitor",
    model="claude-sonnet-4-6",
    system="""You are an outreach monitoring agent. Your job is to track a list of 
email addresses and determine which ones have replied to outbound emails.

WORKFLOW FOR DAILY CHECK:
1. For each email address in the watchlist, search for emails SENT TO them 
   using gmail_search with query: to:<address> is:sent newer_than:7d
2. For each email address, search for emails RECEIVED FROM them 
   using gmail_search with query: from:<address> newer_than:7d  
3. Cross-reference: if you find an outbound email to someone AND a reply 
   from them with a matching thread, they replied.
4. Produce a structured report with two sections:
   REPLIED - address, original subject, reply date, snippet of reply
   NO REPLY - address, original subject, days since sent

WORKFLOW FOR FOLLOW-UP DRAFTING:
1. Use gmail_get_thread to read the full original email thread
2. Write a follow-up that references the original email content naturally
3. Keep follow-ups brief, professional, and non-pushy
4. Use gmail_create_draft to save the draft — NEVER send directly

RULES:
- Never send emails. Only create drafts.
- Always include all watchlist addresses in the report, even if no outbound 
  email was found (mark as "No outbound email found").
- Use plain text for email drafts, not HTML.""",
    tools=[
        {"type": "agent_toolset_20260401"},
        {
            "type": "custom",
            "name": "gmail_search",
            "description": "Search Gmail using Gmail query syntax (from:, to:, subject:, is:sent, newer_than:, older_than:, etc). Returns a JSON array of message objects with id, threadId, subject, from, to, date, and snippet fields. Use this to find outbound emails sent to watchlist addresses and to find replies from those addresses.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "Gmail search query. Examples: 'to:john@example.com is:sent newer_than:7d' or 'from:john@example.com newer_than:7d'"
                    },
                    "max_results": {
                        "type": "integer", 
                        "description": "Maximum number of messages to return. Default 20.",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        },
        {
            "type": "custom",
            "name": "gmail_get_thread",
            "description": "Retrieve a full email thread by its thread ID. Returns all messages in the conversation with sender, recipient, subject, date, and body text. Use this to read the original outbound email before drafting a follow-up.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "thread_id": {
                        "type": "string", 
                        "description": "The Gmail thread ID (obtained from gmail_search results)"
                    }
                },
                "required": ["thread_id"]
            }
        },
        {
            "type": "custom",
            "name": "gmail_create_draft",
            "description": "Create an email draft in Gmail. The draft is NOT sent — it appears in the user's Drafts folder for review. Use this to compose follow-up emails for non-responding contacts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line. For follow-ups, use 'Re: <original subject>'"},
                    "body": {"type": "string", "description": "Plain text email body"},
                    "in_reply_to": {
                        "type": "string", 
                        "description": "Optional. The Message-ID header from the original email, for proper threading"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }
    ],
    betas=["managed-agents-2026-04-01"]
)

config = {"agent_id": agent.id, "agent_version": agent.version}
config_path = os.path.expanduser("~/.gmail-agent/agent_config.json")
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Agent created successfully!")
print(f"Agent ID: {agent.id}")
print(f"Version: {agent.version}")
print(f"Config saved to: {config_path}")
```

---

## setup_environment.py — Full Source

```python
import anthropic
import json
import os

client = anthropic.Anthropic()

environment = client.beta.agents.environments.create(
    name="gmail-monitor-env",
    config={
        "type": "cloud",
        "networking": {"type": "unrestricted"}
    },
    betas=["managed-agents-2026-04-01"]
)

config_path = os.path.expanduser("~/.gmail-agent/agent_config.json")
with open(config_path, "r") as f:
    config = json.load(f)

config["environment_id"] = environment.id

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Environment created successfully!")
print(f"Environment ID: {environment.id}")
print(f"Config saved to: {config_path}")
```

---

## auth_gmail.py — Full Source

```python
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CREDS_DIR = os.path.expanduser("~/.gmail-agent")
CREDS_FILE = os.path.join(CREDS_DIR, "credentials.json")
TOKEN_FILE = os.path.join(CREDS_DIR, "token.json")

def main():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    print("Authentication successful!")
    print(f"Token saved to: {TOKEN_FILE}")

if __name__ == "__main__":
    main()
```

---

## Immediate Next Steps for Claude Code

1. **Verify SDK namespace:** Run `python -c "import anthropic; c = anthropic.Anthropic(); print(dir(c.beta))"` to see what's available. Fix method names in all scripts if they don't match.

2. **Test daily_monitor.py:** Run it manually. Expect possible errors around SDK method names — fix them based on what `dir()` reveals.

3. **Create send_followups.py:** Interactive script that asks for non-responder addresses, creates a session, drafts follow-up emails based on original threads, saves them as Gmail drafts.

4. **Set up Windows Task Scheduler:** Automate daily_monitor.py to run at a chosen time.

5. **Add logging:** Write logs to `~/gmail-agent/logs/` so scheduled runs can be debugged after the fact.
