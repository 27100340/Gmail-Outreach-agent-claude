<div align="center">

# Gmail Outreach Agent

**Autonomous cold outreach inbox monitor powered by Claude**

Built for [Ticketly](https://ticketly.pk) — tracks watched contacts, flags priority replies, and delivers daily inbox summaries straight to Slack.

---

**Agent By: Baqir Hassan - LUMS - 27100340 for: Ticketly**

---

</div>

## What It Does

This agent connects to your Gmail, scans your inbox every morning, and produces a structured daily report:

- **P1 / Urgent** — replies needing immediate action (call requests, blockers, deadlines)
- **P2 / Important** — questions, operational alerts, calendar invites
- **P3 / Low Priority** — newsletters, promos, digests
- **Watched Contacts Tracking** — who replied, who hasn't, stale threads, missing outreach
- **Draft Creation** — the agent can draft follow-up emails (saved to Drafts, never sends)

Reports are saved locally as `.md` files AND posted to a Slack channel automatically.

### How It Works

```
GitHub Actions (daily cron) or local run
        |
        v
run_agent.py
        |
        v
agent.py  -->  Creates a Claude Managed Agent session (Anthropic cloud)
        |           |
        |           +--> Agent calls gmail_search, gmail_get_thread, gmail_create_draft
        |           |
        |           +--> Local script executes those against Gmail API
        |           |
        |           +--> Agent writes the structured report
        |
        v
Report saved to reports/ + posted to Slack
```

The agent runs on Anthropic's Managed Agents platform. Gmail tool calls are intercepted locally and executed against the Gmail API. The agent never has direct access to your Gmail credentials.

---

## Sample Report

```
# Daily Inbox Summary – April 13, 2026

## P1 – Urgent (2)

Sara Abdo (NymCard) – Re: BIN Allocation Request – She's asking you to send
the correct card design (missing attachment). – Draft created — attach the
design PDF before sending.

Jira Admin – Your space(s) will be permanently deleted – "Marketing" space
deletes in 7 days. – No reply needed; action in Jira.

## P2 – Important (4)

Google Calendar – Sprint Planning Session today 11:30am. – No reply needed.
Firebase Crashlytics – Trending stability issues for CardPay Android. –
No reply needed; review in Firebase console.
...

## P3 – Low Priority (10)
Medium Daily Digest x5, Replit webinar, Dribbble newsletter, Gamma promo...

## Watched Contacts – No Reply
27100340@lums.edu.pk – Partnership Proposal – Sent Apr 10 – 3 days waiting

---
Drafts created: 1 — review and send from Gmail
```

---

## Project Structure

```
Outreach Agent/
├── run_agent.py                 # Entry point
├── agent.py                     # Session logic, streaming, Slack posting
├── gmail_tools.py               # Gmail API handlers (search, thread, draft)
├── .env                         # API keys (gitignored)
├── .gitignore
│
├── config/                      # OAuth credentials + agent config (gitignored)
│   ├── credentials.json
│   ├── token.json
│   └── agent_config.json
│
├── prompts/                     # Prompt templates — edit without touching code
│   ���── monitor.md
│
├── setup/                       # One-time setup scripts
│   ├── auth_gmail.py            # Gmail OAuth flow
│   ├── setup_agent.py           # Create Managed Agent on Anthropic
│   └── setup_environment.py     # Create cloud environment on Anthropic
│
├── reports/                     # Generated daily reports (gitignored)
│
├── docs/                        # Documentation
│   └── gmail_agent.md
│
└── .github/workflows/
    └── daily-report.yml         # GitHub Actions daily cron
```

---

## Setup Guide

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/) with Managed Agents access
- A [Google Cloud project](https://console.cloud.google.com/) with Gmail API enabled
- A Slack workspace (for automated report delivery)

### 1. Clone the repo

```bash
git clone https://github.com/27100340/Gmail-Outreach-agent-claude.git
cd Gmail-Outreach-agent-claude
```

### 2. Install dependencies

```bash
pip install anthropic google-api-python-client google-auth-httplib2 \
            google-auth-oauthlib python-dotenv rich
```

### 3. Set up Google Cloud OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API** (APIs & Services > Library > search "Gmail API" > Enable)
4. Configure **OAuth consent screen**:
   - User type: External
   - App name: anything (e.g., "Outreach Agent")
   - Add scope: `https://www.googleapis.com/auth/gmail.modify`
   - Add your Gmail address as a test user
5. Create **OAuth credentials**:
   - APIs & Services > Credentials > Create Credentials > OAuth client ID
   - Application type: **Desktop app**
   - Download the JSON file
6. Save it as `config/credentials.json`:

```bash
mkdir config
mv ~/Downloads/client_secret_*.json config/credentials.json
```

### 4. Authenticate with Gmail

```bash
python setup/auth_gmail.py
```

This opens a browser window for Google OAuth. Sign in and grant access. A `config/token.json` file is created automatically. This only needs to be done once — the token auto-refreshes.

### 5. Set up your `.env`

```bash
# Create .env in the project root
ANTHROPIC_API_KEY=sk-ant-...your-key...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

Leave `SLACK_WEBHOOK_URL` blank if you don't want Slack integration yet.

### 6. Create the Managed Agent

```bash
python setup/setup_agent.py
```

This creates a persistent agent on Anthropic's platform with the Gmail tools defined. The agent ID is saved to `config/agent_config.json`.

### 7. Create the cloud environment

```bash
python setup/setup_environment.py
```

This creates the cloud container environment the agent runs in. The environment ID is added to `config/agent_config.json`.

### 8. Edit your watchlist

Open `agent.py` and edit the `WATCHLIST` array with the email addresses you want to track:

```python
WATCHLIST = [
    "client1@example.com",
    "client2@company.com",
    "lead@prospect.org",
]
```

### 9. Run it

```bash
python run_agent.py
```

You'll see a live progress display in the terminal, then the report saves to `reports/` and posts to Slack (if configured).

---

## Slack Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) > **Create New App** > **From scratch**
2. Name: `Outreach Agent` — pick your workspace
3. Go to **Incoming Webhooks** > toggle ON
4. Click **Add New Webhook to Workspace** > select your channel (e.g., `#outreach-reports`)
5. Copy the webhook URL and paste it in your `.env`:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```

---

## Automate with GitHub Actions

The included workflow runs the agent every morning at **9:00 AM PKT** and posts the report to Slack.

### Add GitHub Secrets

Go to your repo > **Settings** > **Secrets and variables** > **Actions** > add these:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_CREDENTIALS` | Full contents of `config/credentials.json` |
| `GOOGLE_TOKEN` | Full contents of `config/token.json` |
| `AGENT_CONFIG` | Full contents of `config/agent_config.json` |
| `SLACK_WEBHOOK_URL` | Your Slack webhook URL |

### Change the schedule

Edit `.github/workflows/daily-report.yml` — the cron expression is in UTC:

```yaml
schedule:
  - cron: "0 4 * * *"   # 4:00 AM UTC = 9:00 AM PKT
```

Common times (PKT = UTC+5):

| PKT | UTC | Cron |
|---|---|---|
| 8:00 AM | 3:00 AM | `0 3 * * *` |
| 9:00 AM | 4:00 AM | `0 4 * * *` |
| 10:00 AM | 5:00 AM | `0 5 * * *` |

### Manual trigger

Go to **Actions** tab > **Daily Outreach Report** > **Run workflow** to trigger it manually any time.

---

## Customizing the Prompt

The agent prompt lives in `prompts/monitor.md` — edit it to change the report format, priority rules, or add new sections. No Python changes needed.

Available placeholders (filled automatically):

| Placeholder | Value |
|---|---|
| `{today}` | `2026-04-13` |
| `{today_long}` | `April 13, 2026` |
| `{watchlist}` | Formatted list of watched emails |
| `{watchlist_exclusions}` | Gmail exclusion query for non-watched emails |

---

## Cost

| Component | Cost |
|---|---|
| Claude Sonnet tokens | ~$0.01–0.05 per run |
| Managed Agents runtime | ~$0.01 per 10-min session |
| Gmail API | Free |
| Slack webhooks | Free |
| GitHub Actions | Free (2,000 mins/month on free tier) |
| **Monthly estimate** | **~$1–3** |

---

## Tech Stack

- **Claude Managed Agents** (Anthropic) — AI agent platform
- **Gmail API** (Google) — email search, thread reading, draft creation
- **Rich** (Python) — terminal progress display
- **Slack Incoming Webhooks** — report delivery
- **GitHub Actions** — daily scheduling

---

<div align="center">

**Agent By: Baqir Hassan - LUMS - 27100340 for: Ticketly**

Built with Claude Managed Agents

</div>
