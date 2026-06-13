"""
DevOps AI Agent — main entry point.

Environment variables required:
  ANTHROPIC_API_KEY   — Claude API key (from Azure Key Vault)
  SLACK_WEBHOOK_URL   — Slack incoming webhook URL (from Azure Key Vault)
  GITHUB_TOKEN        — GitHub personal access token (for API calls)
  GITHUB_REPO         — GitHub repo in format owner/repo

Usage:
  python main.py                          # run sample investigation
  python main.py healthcheck              # run proactive health check
  python main.py <namespace> "<issue>"   # investigate specific issue
"""

import os
import sys
from dotenv import load_dotenv
from agent_runner import run_agent, run_health_check
from slack_reporter import send_agent_started, send_agent_error

# Load .env file if running locally (not in production)
load_dotenv()


def validate_environment():
    """Check all required environment variables are present."""
    required = ["ANTHROPIC_API_KEY", "SLACK_WEBHOOK_URL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variables: {missing}")
        print("Set them in .env file for local testing or as K8s secrets for cluster deployment.")
        sys.exit(1)
    print("✅ Environment validated")


def main():
    validate_environment()

    # Parse command line arguments
    if len(sys.argv) == 2 and sys.argv[1] == "healthcheck":
        print("Running scheduled health check...")
        run_health_check()

    elif len(sys.argv) == 3:
        # Custom trigger: python main.py <namespace> "<issue description>"
        namespace = sys.argv[1]
        issue = sys.argv[2]
        trigger = {
            "namespace": namespace,
            "issue": issue,
            "severity": "WARNING"
        }
        send_agent_started(trigger)
        try:
            run_agent(trigger)
        except Exception as e:
            send_agent_error(str(e))
            raise

    else:
        # Default demo scenario
        print("Running demo investigation scenario...")
        trigger = {
            "namespace": "game-dev",
            "issue": "Deployment health check — verify cluster state",
            "severity": "INFO"
        }
        send_agent_started(trigger)
        try:
            run_agent(trigger)
        except Exception as e:
            send_agent_error(str(e))
            raise


if __name__ == "__main__":
    main()