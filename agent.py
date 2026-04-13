"""
Outreach monitoring agent — pre-filters contacts locally, reads threads
via Gmail API, and sends ONE Claude Messages API call for classification
and report generation. No Managed Agents, no streaming, no tool calls.
"""

import anthropic
import json
import os
import re
import base64
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from rich.console import Console
from rich.panel import Panel

from prefilter import scan_watchlist

# ─── Load .env ──────────────────────────────────────────────

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ─── Paths ──────────────────────────────────────────────────

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
PROMPT_DIR = os.path.join(ROOT_DIR, "prompts")
REPORT_DIR = os.path.join(ROOT_DIR, "reports")
WATCHLIST_FILE = os.path.join(ROOT_DIR, "watchlist", "contacts.txt")

TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")

# ─── Watchlist ──────────────────────────────────────────────

def _load_watchlist():
    """Load email addresses from watchlist/contacts.txt."""
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    emails = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    if not emails:
        raise SystemExit("Watchlist is empty. Add emails to watchlist/contacts.txt")
    return emails

WATCHLIST = _load_watchlist()

# ─── Initialization ─────────────────────────────────────────

os.makedirs(REPORT_DIR, exist_ok=True)

# Gmail
_creds = Credentials.from_authorized_user_file(
    TOKEN_FILE,
    scopes=["https://www.googleapis.com/auth/gmail.modify"],
)
if _creds.expired and _creds.refresh_token:
    _creds.refresh(Request())
    with open(TOKEN_FILE, "w") as f:
        f.write(_creds.to_json())

gmail = build("gmail", "v1", credentials=_creds)

# Anthropic (regular Messages API — no Managed Agents)
anthropic_client = anthropic.Anthropic()

# ─── Local thread reader ───────────────────────────────────

def _read_thread(thread_id):
    """Read a full Gmail thread locally. Returns formatted string."""
    try:
        thread = gmail.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
    except Exception as e:
        return f"[Could not read thread {thread_id}: {e}]"

    msgs = []
    for msg in thread.get("messages", []):
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

        msgs.append(
            f"From: {headers.get('From', '')}\n"
            f"To: {headers.get('To', '')}\n"
            f"Date: {headers.get('Date', '')}\n"
            f"Subject: {headers.get('Subject', '')}\n"
            f"Body: {body[:500]}"
        )

    return "\n---\n".join(msgs)


def _search_unread_inbox(watchlist_exclusions):
    """Search for unread emails not from watched contacts. Returns formatted string."""
    query = f"is:unread {watchlist_exclusions} newer_than:7d"
    try:
        resp = gmail.users().messages().list(
            userId="me", q=query, maxResults=30
        ).execute()
    except Exception:
        return "Could not search unread inbox."

    messages = resp.get("messages", [])
    if not messages:
        return "No other unread emails found."

    entries = []
    for msg in messages:
        detail = gmail.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        entries.append(
            f"From: {headers.get('From', '')}\n"
            f"Subject: {headers.get('Subject', '(no subject)')}\n"
            f"Date: {headers.get('Date', '')}\n"
            f"Snippet: {detail.get('snippet', '')}"
        )

    return "\n---\n".join(entries)

# ─── Slack helpers ──────────────────────────────────────────

def _md_to_slack_mrkdwn(text):
    """Convert markdown report to Slack mrkdwn format."""
    lines = text.split("\n")
    converted = []
    for line in lines:
        if line.startswith("## "):
            converted.append(f"*{line[3:].strip()}*")
        elif line.startswith("# "):
            converted.append(f"*{line[2:].strip()}*")
        else:
            converted.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", line))
    return "\n".join(converted)


def _build_slack_blocks(report_text):
    """Build Slack Block Kit blocks from the report."""
    slack_text = _md_to_slack_mrkdwn(report_text)

    sections = []
    current_header = None
    current_lines = []

    for line in slack_text.split("\n"):
        stripped = line.strip()
        if (
            stripped.startswith("*")
            and stripped.endswith("*")
            and len(stripped) > 2
            and "–" in stripped
            or stripped.startswith("*Daily Inbox Summary")
            or stripped.startswith("*Watched Contacts")
            or stripped.startswith("*Drafts created")
        ):
            if current_header or current_lines:
                sections.append((current_header, "\n".join(current_lines).strip()))
            current_header = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_header or current_lines:
        sections.append((current_header, "\n".join(current_lines).strip()))

    blocks = []

    title = sections[0][0] if sections and sections[0][0] else "*Daily Inbox Summary*"
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": title.strip("*"), "emoji": True}
    })
    blocks.append({"type": "divider"})

    for header, body in sections[1:]:
        if not header and not body:
            continue

        if header:
            emoji = ""
            h = header.lower()
            if "p1" in h or "urgent" in h:
                emoji = ":red_circle: "
            elif "p2" in h or "important" in h:
                emoji = ":large_yellow_circle: "
            elif "p3" in h or "low priority" in h:
                emoji = ":white_circle: "
            elif "no reply" in h:
                emoji = ":hourglass: "
            elif "stale" in h:
                emoji = ":zzz: "
            elif "no response" in h:
                emoji = ":mailbox_with_no_mail: "
            elif "summary" in h:
                emoji = ":bar_chart: "
            elif "drafts" in h:
                emoji = ":pencil2: "

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{emoji}{header}"}
            })

        if body:
            while body:
                chunk = body[:3000]
                if len(body) > 3000:
                    last_newline = chunk.rfind("\n")
                    if last_newline > 0:
                        chunk = body[:last_newline]
                    body = body[len(chunk):]
                else:
                    body = ""
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": chunk.strip()}
                })

        blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "_Agent By: Baqir Hassan - LUMS - 27100340 for: Ticketly_"}
        ]
    })

    return blocks[:50]


def _post_to_slack(report_text, console):
    """Post the report to Slack if SLACK_WEBHOOK_URL is configured."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        console.log("[dim]Slack webhook not configured, skipping[/dim]")
        return False

    blocks = _build_slack_blocks(report_text)
    fallback = report_text[:3000] + "..." if len(report_text) > 3000 else report_text

    payload = json.dumps({"text": fallback, "blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                console.log("[green]\u2713[/green] Report posted to Slack")
                return True
            console.log(f"[red]\u2717[/red] Slack returned status {resp.status}")
            return False
    except Exception as e:
        console.log(f"[red]\u2717 Slack error:[/red] {e}")
        return False

# ─── Prompt + report helpers ───────────────────────────────

def _load_prompt(now, active_threads_content, unread_inbox_content, scan_data):
    """Load the prompt template and fill all placeholders."""
    prompt_path = os.path.join(PROMPT_DIR, "monitor.md")
    today = now.strftime("%Y-%m-%d")
    today_long = now.strftime("%B %d, %Y")

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Escape agent-filled placeholders
    safe_template = template.replace("{p1_count}", "{{p1_count}}")
    safe_template = safe_template.replace("{p2_count}", "{{p2_count}}")
    safe_template = safe_template.replace("{p3_count}", "{{p3_count}}")

    return safe_template.format(
        today=today,
        today_long=today_long,
        active_threads_content=active_threads_content,
        unread_inbox_content=unread_inbox_content,
        total_watched=len(WATCHLIST),
        no_reply_count=len(scan_data["sent_no_reply"]),
        stale_count=len(scan_data["stale_threads"]),
        no_response_count=len(scan_data["no_response"]),
    )


def _build_local_sections(scan_data):
    """Build the markdown sections that Python appends to the report."""
    parts = []

    parts.append("## Watched Contacts \u2013 No Reply")
    if scan_data["sent_no_reply"]:
        for item in scan_data["sent_no_reply"]:
            parts.append(
                f"**{item['email']}** \u2013 {item['subject']} \u2013 "
                f"Sent on {item['date_sent']}"
            )
    else:
        parts.append("None.")

    parts.append("")

    parts.append("## Watched Contacts \u2013 Stale Threads")
    if scan_data["stale_threads"]:
        for item in scan_data["stale_threads"]:
            snippet = item.get("snippet", "")
            context = f" \u2013 {snippet}" if snippet else ""
            parts.append(
                f"**{item['email']}** \u2013 {item['subject']} \u2013 "
                f"Our last message on {item['our_last_date']}{context}"
            )
    else:
        parts.append("None.")

    parts.append("")

    parts.append("## Watched Contacts \u2013 No Response")
    if scan_data["no_response"]:
        for email in scan_data["no_response"]:
            parts.append(f"**{email}** \u2013 No response received")
    else:
        parts.append("None.")

    return "\n".join(parts)

# ─── Main session logic ────────────────────────────────────

def run_daily_check(username):
    """Run a full outreach monitoring check and save the report."""
    console = Console()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # ── Header ──
    CREDIT = "Agent By: Baqir Hassan - LUMS - 27100340 for: Ticketly"
    console.print()
    console.print(Panel(
        f"[bold]Outreach Monitor[/bold]\n"
        f"[dim]{CREDIT}[/dim]\n\n"
        f"[dim]User:[/dim]  {username}\n"
        f"[dim]Date:[/dim]  {now.strftime('%A, %B %d %Y')}\n"
        f"[dim]Time:[/dim]  {now.strftime('%I:%M %p')}\n"
        f"[dim]Watching:[/dim]  {len(WATCHLIST)} address(es)",
        title="[bold cyan]Ticketly Outreach Agent[/bold cyan]",
        subtitle=f"[dim]{CREDIT}[/dim]",
        border_style="cyan",
    ))
    console.print()

    with console.status("[bold]Initializing...[/bold]", spinner="dots") as status:

        # ── Step 1: Pre-filter watchlist ──
        scan_data = scan_watchlist(gmail, WATCHLIST, console, status)
        active_contacts = scan_data["active_contacts"]
        thread_ids = scan_data["thread_ids"]

        # ── Step 2: Read threads locally for active contacts ──
        active_threads_content = ""
        if active_contacts:
            status.update("[yellow]Reading threads for active contacts...[/yellow]")
            thread_parts = []
            for email in active_contacts:
                tids = thread_ids.get(email, [])
                for tid in tids:
                    console.log(f"[green]\u2713[/green] Reading thread for [cyan]{email}[/cyan]")
                    content = _read_thread(tid)
                    thread_parts.append(
                        f"=== Contact: {email} | Thread: {tid} ===\n{content}"
                    )
            active_threads_content = "\n\n".join(thread_parts)
        else:
            active_threads_content = "No active contacts with recent activity."

        # ── Step 3: Read unread inbox (non-watched) ──
        status.update("[yellow]Scanning unread inbox...[/yellow]")
        watchlist_exclusions = " ".join(f"-from:{email}" for email in WATCHLIST)
        unread_inbox_content = _search_unread_inbox(watchlist_exclusions)
        console.log("[green]\u2713[/green] Unread inbox scanned")

        # ── Step 4: Build prompt with all content embedded ──
        status.update("[yellow]Building prompt...[/yellow]")
        prompt = _load_prompt(now, active_threads_content, unread_inbox_content, scan_data)
        console.log(f"[green]\u2713[/green] Prompt built ({len(prompt)} chars)")

        # ── Step 5: Single API call to Claude ──
        has_content = active_contacts or unread_inbox_content != "No other unread emails found."

        if has_content:
            status.update("[bold cyan]Claude is writing the report...[/bold cyan]")
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            report_from_claude = response.content[0].text
            console.log("[green]\u2713[/green] Report generated")
        else:
            console.log("[green]\u2713[/green] No activity — building local report")
            today_long = now.strftime("%B %d, %Y")
            report_from_claude = (
                f"# Daily Inbox Summary \u2013 {today_long}\n\n"
                f"## P1 \u2013 Urgent (0)\nNone.\n\n"
                f"## P2 \u2013 Important (0)\nNone.\n\n"
                f"## P3 \u2013 Low Priority (0)\nNone.\n\n"
                f"## 6. SUMMARY\n"
                f"- {len(WATCHLIST)} contacts watched; no new activity today.\n"
                f"- {len(scan_data['sent_no_reply'])} contacts awaiting first reply.\n"
                f"- {len(scan_data['stale_threads'])} stale threads.\n"
                f"- {len(scan_data['no_response'])} contacts with no response.\n\n"
                f"**Drafts created: 0**\n"
            )

    # ── Save report ──
    local_sections = _build_local_sections(scan_data)
    report_text = (
        report_from_claude
        + "\n\n"
        + local_sections
        + f"\n\n---\n*{CREDIT}*\n"
    )
    report_name = now.strftime("%A,%Y-%m-%d,%I-%M-%p") + f",{username}.md"
    report_path = os.path.join(REPORT_DIR, report_name)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # ── Post to Slack ──
    _post_to_slack(report_text, console)

    # ── Completion summary ──
    console.print()
    console.print(Panel(
        f"[bold green]\u2713 Complete![/bold green]\n\n"
        f"[dim]Report saved to:[/dim]  [underline]{report_path}[/underline]",
        title="[bold green]Done[/bold green]",
        subtitle=f"[dim]{CREDIT}[/dim]",
        border_style="green",
    ))
    console.print()

    return report_path
