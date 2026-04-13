"""Entry point for the Ticketly outreach monitoring agent."""

import os
import sys
import traceback

from agent import run_daily_check

if __name__ == "__main__":
    # Use AGENT_USERNAME env var (for CI/scheduled runs), otherwise prompt
    username = os.environ.get("AGENT_USERNAME", "").strip()
    if not username:
        try:
            username = input("Enter your name: ").strip()
        except EOFError:
            username = ""
    if not username:
        print("Username is required. Set AGENT_USERNAME env var or enter interactively.")
        sys.exit(1)
    try:
        run_daily_check(username)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
