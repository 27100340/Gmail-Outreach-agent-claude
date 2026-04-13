"""
Outreach monitoring agent — session management, streaming, and reporting.

Creates a Managed Agent session on Anthropic's platform, sends the monitoring
prompt, handles Gmail tool calls locally via the streaming loop, and saves
the resulting report to disk.
"""

import anthropic
import json
import os
import re
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from rich.console import Console
from rich.panel import Panel

from gmail_tools import build_tool_handlers
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
CONFIG_FILE = os.path.join(CONFIG_DIR, "agent_config.json")

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

with open(CONFIG_FILE, "r") as f:
    _config = json.load(f)

AGENT_ID = _config["agent_id"]
ENVIRONMENT_ID = _config["environment_id"]

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
TOOL_HANDLERS = build_tool_handlers(gmail)

# Anthropic
anthropic_client = anthropic.Anthropic()

# ─── Display helpers ────────────────────────────────────────

def _friendly_tool_message(tool_name, tool_input):
    """Convert a tool call into a human-readable status message."""
    if tool_name == "gmail_search":
        query = tool_input.get("query", "")
        match = re.search(r'(?:to:|from:)(\S+)', query)
        addr = match.group(1) if match else None
        if "is:sent" in query and addr:
            return f"Checking sent emails to [cyan]{addr}[/cyan]"
        if "from:" in query and addr:
            return f"Checking replies from [cyan]{addr}[/cyan]"
        if "is:unread" in query:
            return "Scanning other unread emails in inbox"
        return "Searching Gmail"
    if tool_name == "gmail_get_thread":
        return "Reading full email thread"
    if tool_name == "gmail_create_draft":
        return f"Creating draft email to [cyan]{tool_input.get('to', '?')}[/cyan]"
    return f"Running {tool_name}"


def _md_to_slack_mrkdwn(text):
    """Convert markdown report to Slack mrkdwn format."""
    lines = text.split("\n")
    converted = []
    for line in lines:
        # ## Heading → *Heading* (bold)
        if line.startswith("## "):
            converted.append(f"*{line[3:].strip()}*")
        # # Title → *Title* (bold)
        elif line.startswith("# "):
            converted.append(f"*{line[2:].strip()}*")
        # **bold** → *bold*
        else:
            # Replace **text** with *text*
            converted.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", line))
    return "\n".join(converted)


def _build_slack_blocks(report_text):
    """Build Slack Block Kit blocks from the report for rich formatting."""
    slack_text = _md_to_slack_mrkdwn(report_text)

    # Split on section headers (lines that are *bold* and look like headers)
    sections = []
    current_header = None
    current_lines = []

    for line in slack_text.split("\n"):
        stripped = line.strip()
        # Detect section headers: lines that are fully bold like *P1 – Urgent (3)*
        if (
            stripped.startswith("*")
            and stripped.endswith("*")
            and len(stripped) > 2
            and "–" in stripped
            or stripped.startswith("*Daily Inbox Summary")
            or stripped.startswith("*Watched Contacts")
            or stripped.startswith("*Drafts created")
        ):
            # Save previous section
            if current_header or current_lines:
                sections.append((current_header, "\n".join(current_lines).strip()))
            current_header = stripped
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_header or current_lines:
        sections.append((current_header, "\n".join(current_lines).strip()))

    # Build Block Kit blocks
    blocks = []

    # Title header
    title = sections[0][0] if sections and sections[0][0] else "*Daily Inbox Summary*"
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": title.strip("*"), "emoji": True}
    })
    blocks.append({"type": "divider"})

    for header, body in sections[1:]:
        if not header and not body:
            continue

        # Section header
        if header:
            # Pick emoji based on content
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

            header_text = f"{emoji}{header}"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": header_text}
            })

        # Section body — Slack limits each text block to 3000 chars
        if body:
            # Split into chunks if needed
            while body:
                chunk = body[:3000]
                # Don't cut in the middle of a line
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

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "_Agent By: Baqir Hassan - LUMS - 27100340 for: Ticketly_"}
        ]
    })

    # Slack limits to 50 blocks
    return blocks[:50]


def _post_to_slack(report_text, console):
    """Post the report to Slack if SLACK_WEBHOOK_URL is configured."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        console.log("[dim]Slack webhook not configured, skipping[/dim]")
        return False

    blocks = _build_slack_blocks(report_text)
    fallback = report_text[:3000] + "..." if len(report_text) > 3000 else report_text

    payload = json.dumps({
        "text": fallback,
        "blocks": blocks,
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
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


def _load_prompt(now, watchlist_exclusions, active_contacts_section, scan_data):
    """Load the prompt template from prompts/monitor.md and fill placeholders."""
    prompt_path = os.path.join(PROMPT_DIR, "monitor.md")
    today = now.strftime("%Y-%m-%d")
    today_long = now.strftime("%B %d, %Y")

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Escape agent-filled placeholders so Python's .format() doesn't touch them.
    # {p1_count}, {p2_count}, {p3_count}, {draft_count} are written by the agent.
    safe_template = template.replace("{p1_count}", "{{p1_count}}")
    safe_template = safe_template.replace("{p2_count}", "{{p2_count}}")
    safe_template = safe_template.replace("{p3_count}", "{{p3_count}}")
    safe_template = safe_template.replace("{draft_count}", "{{draft_count}}")

    return safe_template.format(
        today=today,
        today_long=today_long,
        active_contacts_section=active_contacts_section,
        watchlist_exclusions=watchlist_exclusions,
        total_watched=len(WATCHLIST),
        no_reply_count=len(scan_data["sent_no_reply"]),
        stale_count=len(scan_data["stale_threads"]),
        no_response_count=len(scan_data["no_response"]),
    )

def _build_active_contacts_section(scan_data):
    """Build the active-contacts block that gets injected into the prompt."""
    active = scan_data["active_contacts"]
    thread_ids = scan_data["thread_ids"]

    if not active:
        return (
            "No active contacts found — skip to STEP 3 (unread inbox scan)."
        )

    lines = []
    for email in active:
        tids = thread_ids.get(email, [])
        tid_str = ", ".join(tids) if tids else "(none)"
        lines.append(f"Contact: {email}")
        lines.append(f"  Thread IDs: {tid_str}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _build_local_sections(scan_data):
    """Build the markdown sections that Python appends to the report.

    These cover contacts the agent did NOT process: no-reply, stale, and
    no-response lists produced by the local pre-filter.
    """
    parts = []

    # ── No Reply ──
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

    # ── Stale Threads ──
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

    # ── No Response ──
    parts.append("## Watched Contacts \u2013 No Response")
    if scan_data["no_response"]:
        for email in scan_data["no_response"]:
            parts.append(
                f"**{email}** \u2013 No response received"
            )
    else:
        parts.append("None.")

    return "\n".join(parts)


# ─── Main session logic ────────────────────────────────────

def run_daily_check(username):
    """Run a full outreach monitoring session and save the report."""
    console = Console()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    report_lines = []
    tool_call_count = 0

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

        # ── Pre-filter watchlist contacts ──
        scan_data = scan_watchlist(gmail, WATCHLIST, console, status)
        active_section = _build_active_contacts_section(scan_data)

        # ── Run agent session (only if there's work to do) ──
        has_active = len(scan_data["active_contacts"]) > 0

        if has_active:
            # Create session
            status.update("[yellow]Creating agent session...[/yellow]")
            session = anthropic_client.beta.sessions.create(
                agent=AGENT_ID,
                environment_id=ENVIRONMENT_ID,
                title=f"Daily outreach check {today}",
                betas=["managed-agents-2026-04-01"],
            )
            session_id = session.id
            console.log("[green]\u2713[/green] Session created")

            # Build and send prompt
            status.update("[yellow]Sending monitoring prompt...[/yellow]")
            watchlist_exclusions = " ".join(f"-from:{email}" for email in WATCHLIST)
            prompt = _load_prompt(now, watchlist_exclusions, active_section, scan_data)

            anthropic_client.beta.sessions.events.send(
                session_id=session_id,
                events=[{
                    "type": "user.message",
                    "content": [{"type": "text", "text": prompt}],
                }],
            )
            console.log("[green]\u2713[/green] Prompt sent to agent")

            # Stream and handle events
            sent_tool_ids = set()
            finished = False

            while not finished:
                status.update("[bold cyan]Agent is thinking...[/bold cyan]")

                with anthropic_client.beta.sessions.events.stream(
                    session_id=session_id,
                ) as stream:
                    for event in stream:
                        event_type = getattr(event, "type", None)

                        if event_type == "agent.custom_tool_use":
                            tool_name = event.name
                            tool_input = event.input
                            tool_use_id = event.id

                            friendly = _friendly_tool_message(tool_name, tool_input)
                            status.update(f"[yellow]{friendly}...[/yellow]")

                            if tool_name in TOOL_HANDLERS:
                                try:
                                    result = TOOL_HANDLERS[tool_name](tool_input)
                                    is_error = False
                                except Exception as e:
                                    result = json.dumps({"error": str(e)})
                                    is_error = True
                                    console.log(f"[red]\u2717 Tool error:[/red] {e}")

                                tool_call_count += 1
                                console.log(f"[green]\u2713[/green] {friendly}")

                                anthropic_client.beta.sessions.events.send(
                                    session_id=session_id,
                                    events=[{
                                        "type": "user.custom_tool_result",
                                        "custom_tool_use_id": tool_use_id,
                                        "content": [{"type": "text", "text": result}],
                                        "is_error": is_error,
                                    }],
                                )
                                sent_tool_ids.add(tool_use_id)
                            else:
                                console.log(f"[red]\u2717[/red] Unknown custom tool: {tool_name}")

                        elif event_type == "agent.tool_use":
                            console.log(f"[blue]\u2192[/blue] Built-in tool: {event.name}")

                        elif event_type == "agent.message":
                            status.update("[cyan]Agent is writing report...[/cyan]")
                            for block in event.content:
                                if hasattr(block, "text"):
                                    report_lines.append(block.text)

                        elif event_type == "session.status_idle":
                            stop_reason = getattr(event, "stop_reason", None)
                            reason_type = getattr(stop_reason, "type", None)

                            if reason_type == "requires_action":
                                event_ids = getattr(stop_reason, "event_ids", [])
                                unsent = [eid for eid in event_ids if eid not in sent_tool_ids]

                                if unsent:
                                    console.log(f"[red]\u2717[/red] Missing results for {len(unsent)} tool call(s)")
                                    finished = True
                                else:
                                    console.log(f"[yellow]\u2192[/yellow] Agent processing results...")
                                break
                            else:
                                console.log("[green]\u2713[/green] Agent finished processing")
                                finished = True
                                break

                        elif event_type == "session.status_terminated":
                            console.log("[red]\u2717[/red] Session terminated unexpectedly")
                            finished = True
                            break

                        elif event_type == "session.error":
                            error_msg = getattr(event, "error", "unknown error")
                            console.log(f"[red]\u2717 Error:[/red] {error_msg}")
        else:
            # No active contacts — skip the agent session entirely ($0 cost)
            console.log("[green]\u2713[/green] No active contacts — skipping agent session (no cost)")
            today_long = now.strftime("%B %d, %Y")
            report_lines.append(f"# Daily Inbox Summary \u2013 {today_long}\n\n")
            report_lines.append("## P1 \u2013 Urgent (0)\nNone.\n\n")
            report_lines.append("## P2 \u2013 Important (0)\nNone.\n\n")
            report_lines.append("## P3 \u2013 Low Priority (0)\nNone.\n\n")
            report_lines.append(
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
        "".join(report_lines)
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
        f"[dim]Tool calls made:[/dim]  {tool_call_count}\n"
        f"[dim]Report saved to:[/dim]  [underline]{report_path}[/underline]",
        title="[bold green]Done[/bold green]",
        subtitle=f"[dim]{CREDIT}[/dim]",
        border_style="green",
    ))
    console.print()

    return report_path
