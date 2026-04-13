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

# ─── Load .env ──────────────────────────────────────────────

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ─── Paths ──────────────────────────────────────────────────

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
PROMPT_DIR = os.path.join(ROOT_DIR, "prompts")
REPORT_DIR = os.path.join(ROOT_DIR, "reports")

TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "agent_config.json")

# ─── Watchlist ──────────────────────────────────────────────

WATCHLIST = [
    "27100340@lums.edu.pk",
]

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


def _post_to_slack(report_text, console):
    """Post the report to Slack if SLACK_WEBHOOK_URL is configured."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        console.log("[dim]Slack webhook not configured, skipping[/dim]")
        return False

    # Slack has a ~40k char limit; truncate if needed
    if len(report_text) > 39000:
        report_text = report_text[:39000] + "\n\n... (truncated)"

    payload = json.dumps({"text": report_text}).encode("utf-8")
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


def _load_prompt(now, watchlist, watchlist_exclusions):
    """Load the prompt template from prompts/monitor.md and fill placeholders."""
    prompt_path = os.path.join(PROMPT_DIR, "monitor.md")
    watchlist_formatted = "\n".join(f"- {email}" for email in watchlist)
    today = now.strftime("%Y-%m-%d")
    today_long = now.strftime("%B %d, %Y")

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Use safe substitution — {p1_count}, {p2_count}, {p3_count}, {draft_count}
    # are meant for the agent to fill in, not Python. Escape them first.
    safe_template = template.replace("{p1_count}", "{{p1_count}}")
    safe_template = safe_template.replace("{p2_count}", "{{p2_count}}")
    safe_template = safe_template.replace("{p3_count}", "{{p3_count}}")
    safe_template = safe_template.replace("{draft_count}", "{{draft_count}}")

    return safe_template.format(
        today=today,
        today_long=today_long,
        watchlist=watchlist_formatted,
        watchlist_exclusions=watchlist_exclusions,
    )

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

        # ── Create session ──
        status.update("[yellow]Creating agent session...[/yellow]")
        session = anthropic_client.beta.sessions.create(
            agent=AGENT_ID,
            environment_id=ENVIRONMENT_ID,
            title=f"Daily outreach check {today}",
            betas=["managed-agents-2026-04-01"],
        )
        session_id = session.id
        console.log("[green]\u2713[/green] Session created")

        # ── Build and send prompt ──
        status.update("[yellow]Sending monitoring prompt...[/yellow]")
        watchlist_exclusions = " ".join(f"-from:{email}" for email in WATCHLIST)
        prompt = _load_prompt(now, WATCHLIST, watchlist_exclusions)

        anthropic_client.beta.sessions.events.send(
            session_id=session_id,
            events=[{
                "type": "user.message",
                "content": [{"type": "text", "text": prompt}],
            }],
        )
        console.log("[green]\u2713[/green] Prompt sent to agent")

        # ── Stream and handle events ──
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

    # ── Save report ──
    report_text = "".join(report_lines) + f"\n\n---\n*{CREDIT}*\n"
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
