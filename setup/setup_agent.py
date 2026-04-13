import anthropic
import json
import os

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

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

# Save the agent ID — preserve existing config (e.g. environment_id)
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "agent_config.json")
config = {}
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        config = json.load(f)
config["agent_id"] = agent.id
config["agent_version"] = agent.version
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Agent created successfully!")
print(f"Agent ID: {agent.id}")
print(f"Version: {agent.version}")
print(f"Config saved to: {config_path}")