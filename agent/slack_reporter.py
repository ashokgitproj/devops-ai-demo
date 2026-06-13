"""
Slack Reporter — standalone utility for sending formatted messages.

The agent uses the send_slack_alert MCP tool for its diagnosis reports.
This module handles additional notifications like startup, errors, and
health check summaries outside the main agent loop.
"""

import requests
import os
from datetime import datetime, timezone


def send_message(text: str, severity: str = "INFO") -> bool:
    """Send a simple text message to Slack."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL not set — skipping Slack notification")
        return False

    emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(severity, "⚪")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *DevOps Agent* · {timestamp}\n{text}"
                }
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Slack error: {e}")
        return False


def send_agent_started(trigger_context: dict) -> bool:
    """Notify Slack that agent has started an investigation."""
    namespace = trigger_context.get("namespace", "unknown")
    issue = trigger_context.get("issue", "unknown issue")
    return send_message(
        f"🔍 Agent investigation started\n"
        f"*Namespace:* {namespace}\n"
        f"*Trigger:* {issue}",
        severity="INFO"
    )


def send_agent_error(error: str) -> bool:
    """Notify Slack that agent encountered an error."""
    return send_message(
        f"Agent encountered an error and could not complete investigation.\n"
        f"*Error:* `{error}`\n"
        f"Manual investigation required.",
        severity="CRITICAL"
    )