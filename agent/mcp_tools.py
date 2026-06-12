"""
MCP Tool Definitions for the DevOps Agent.

Each tool has:
  - name:        what the agent calls it
  - description: what the model reads to decide WHEN to use this tool
  - input_schema: what parameters the tool accepts

The model reads the description and decides autonomously which tools
to call and in what order based on the situation it's investigating.
"""

import subprocess
import json
import requests
import os
from datetime import datetime, timezone


# ── Tool definitions (passed to Claude API) ───────────────────────────────────
# This list tells the model what tools are available.
# The model reads description fields to decide when to call each tool.

TOOL_DEFINITIONS = [
    {
        "name": "list_pods",
        "description": (
            "List all pods in a Kubernetes namespace with their current status, "
            "restart count and age. Use this first to get an overview of what is "
            "running and identify which pods are unhealthy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace to list pods from (e.g. game-dev, game-prod)"
                }
            },
            "required": ["namespace"]
        }
    },
    {
        "name": "get_pod_logs",
        "description": (
            "Fetch the most recent log lines from a specific pod. "
            "Use this after identifying a problematic pod to understand "
            "what error it is producing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace the pod is in"
                },
                "pod_name": {
                    "type": "string",
                    "description": "Full name of the pod"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of recent log lines to fetch (default 50)",
                    "default": 50
                }
            },
            "required": ["namespace", "pod_name"]
        }
    },
    {
        "name": "get_pod_status",
        "description": (
            "Get detailed status of a specific pod including its phase, "
            "container states, restart count and Kubernetes events. "
            "Use this to understand why a pod is not starting or is crashing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace the pod is in"
                },
                "pod_name": {
                    "type": "string",
                    "description": "Full name of the pod"
                }
            },
            "required": ["namespace", "pod_name"]
        }
    },
    {
        "name": "get_argocd_app_status",
        "description": (
            "Get the sync status, health status and last sync time "
            "for an ArgoCD application. Use this to check if a deployment "
            "is OutOfSync, Degraded or if there was a sync error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "ArgoCD application name (e.g. game-2048-dev, game-2048-prod)"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "get_recent_commits",
        "description": (
            "Get the most recent commits on a branch from GitHub. "
            "Use this to understand what code changes were made recently "
            "that might have caused a deployment issue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch name to get commits from (e.g. dev, main)"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of recent commits to fetch (default 5)",
                    "default": 5
                }
            },
            "required": ["branch"]
        }
    },
    {
        "name": "get_pipeline_status",
        "description": (
            "Get the status of the most recent GitHub Actions pipeline run. "
            "Use this to check if the CI or CD pipeline failed and at which step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch to check pipeline status for"
                }
            },
            "required": ["branch"]
        }
    },
    {
        "name": "sync_argocd_app",
        "description": (
            "Trigger a manual sync on an ArgoCD application. "
            "Use this ONLY when the root cause is confirmed to be an "
            "OutOfSync state and the fix is to re-apply the Git state. "
            "Always explain why you are syncing before calling this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "ArgoCD application name to sync"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "send_slack_alert",
        "description": (
            "Send a structured diagnosis report to the Slack #devops-alerts channel. "
            "Always call this as the FINAL step after completing your investigation. "
            "Include root cause, evidence, action taken and recommendation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["CRITICAL", "WARNING", "INFO"],
                    "description": "Severity level of the issue"
                },
                "summary": {
                    "type": "string",
                    "description": "One sentence summary of the issue"
                },
                "root_cause": {
                    "type": "string",
                    "description": "Detailed explanation of what caused the issue"
                },
                "evidence": {
                    "type": "string",
                    "description": "Key log lines or status outputs that support the diagnosis"
                },
                "action_taken": {
                    "type": "string",
                    "description": "What the agent did to resolve the issue, or none if escalating"
                },
                "recommendation": {
                    "type": "string",
                    "description": "What the human operator should do next"
                }
            },
            "required": ["severity", "summary", "root_cause", "evidence", "action_taken", "recommendation"]
        }
    }
]


# ── Tool implementations (the actual functions that run) ──────────────────────

def list_pods(namespace: str) -> dict:
    """List pods in a namespace using kubectl."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace,
             "-o", "json", "--request-timeout=10s"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        data = json.loads(result.stdout)
        pods = []
        for pod in data.get("items", []):
            name = pod["metadata"]["name"]
            phase = pod["status"].get("phase", "Unknown")
            restart_count = sum(
                cs.get("restartCount", 0)
                for cs in pod["status"].get("containerStatuses", [])
            )
            age_seconds = 0
            creation = pod["metadata"].get("creationTimestamp")
            if creation:
                created = datetime.fromisoformat(creation.replace("Z", "+00:00"))
                age_seconds = int((datetime.now(timezone.utc) - created).total_seconds())

            pods.append({
                "name": name,
                "phase": phase,
                "restarts": restart_count,
                "age_minutes": age_seconds // 60
            })
        return {"namespace": namespace, "pods": pods, "count": len(pods)}
    except Exception as e:
        return {"error": str(e)}


def get_pod_logs(namespace: str, pod_name: str, lines: int = 50) -> dict:
    """Fetch pod logs using kubectl."""
    try:
        result = subprocess.run(
            ["kubectl", "logs", pod_name, "-n", namespace,
             f"--tail={lines}", "--request-timeout=10s"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            # Try previous container if current isn't running
            result = subprocess.run(
                ["kubectl", "logs", pod_name, "-n", namespace,
                 f"--tail={lines}", "--previous", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
        return {
            "pod": pod_name,
            "namespace": namespace,
            "logs": result.stdout or result.stderr or "No logs available"
        }
    except Exception as e:
        return {"error": str(e)}


def get_pod_status(namespace: str, pod_name: str) -> dict:
    """Get detailed pod status and events."""
    try:
        # Get pod JSON
        result = subprocess.run(
            ["kubectl", "get", "pod", pod_name, "-n", namespace,
             "-o", "json", "--request-timeout=10s"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        pod = json.loads(result.stdout)
        status = pod.get("status", {})

        # Get events for this pod
        events_result = subprocess.run(
            ["kubectl", "get", "events", "-n", namespace,
             "--field-selector", f"involvedObject.name={pod_name}",
             "--sort-by=.lastTimestamp", "-o", "json"],
            capture_output=True, text=True, timeout=15
        )
        events = []
        if events_result.returncode == 0:
            events_data = json.loads(events_result.stdout)
            for e in events_data.get("items", [])[-5:]:
                events.append({
                    "reason": e.get("reason"),
                    "message": e.get("message"),
                    "type": e.get("type")
                })

        container_states = []
        for cs in status.get("containerStatuses", []):
            state = cs.get("state", {})
            waiting = state.get("waiting", {})
            container_states.append({
                "name": cs.get("name"),
                "ready": cs.get("ready"),
                "restarts": cs.get("restartCount"),
                "state": list(state.keys())[0] if state else "unknown",
                "reason": waiting.get("reason", ""),
                "message": waiting.get("message", "")
            })

        return {
            "pod": pod_name,
            "phase": status.get("phase"),
            "container_states": container_states,
            "events": events
        }
    except Exception as e:
        return {"error": str(e)}


def get_argocd_app_status(app_name: str) -> dict:
    """Get ArgoCD application status using kubectl."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "application", app_name,
             "-n", "argocd", "-o", "json", "--request-timeout=10s"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        app = json.loads(result.stdout)
        status = app.get("status", {})

        return {
            "app": app_name,
            "sync_status": status.get("sync", {}).get("status"),
            "health_status": status.get("health", {}).get("status"),
            "last_sync": status.get("operationState", {}).get("finishedAt"),
            "message": status.get("conditions", [{}])[0].get("message", "") if status.get("conditions") else ""
        }
    except Exception as e:
        return {"error": str(e)}


def get_recent_commits(branch: str, count: int = 5) -> dict:
    """Fetch recent commits from GitHub API."""
    try:
        repo = os.environ.get("GITHUB_REPO", "ashokgitproj/devops-ai-demo")
        token = os.environ.get("GITHUB_TOKEN", "")
        headers = {"Authorization": f"token {token}"} if token else {}

        url = f"https://api.github.com/repos/{repo}/commits"
        params = {"sha": branch, "per_page": count}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()

        commits = []
        for c in resp.json():
            commits.append({
                "sha": c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"]
            })
        return {"branch": branch, "commits": commits}
    except Exception as e:
        return {"error": str(e)}


def get_pipeline_status(branch: str) -> dict:
    """Get latest GitHub Actions run status."""
    try:
        repo = os.environ.get("GITHUB_REPO", "ashokgitproj/devops-ai-demo")
        token = os.environ.get("GITHUB_TOKEN", "")
        headers = {"Authorization": f"token {token}"} if token else {}

        url = f"https://api.github.com/repos/{repo}/actions/runs"
        params = {"branch": branch, "per_page": 3}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()

        runs = []
        for r in resp.json().get("workflow_runs", []):
            runs.append({
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "conclusion": r["conclusion"],
                "branch": r["head_branch"],
                "commit": r["head_sha"][:7],
                "created_at": r["created_at"]
            })
        return {"branch": branch, "recent_runs": runs}
    except Exception as e:
        return {"error": str(e)}


def sync_argocd_app(app_name: str) -> dict:
    """Trigger ArgoCD application sync."""
    try:
        result = subprocess.run(
            ["kubectl", "patch", "application", app_name,
             "-n", "argocd", "--type", "merge",
             "-p", '{"operation":{"initiatedBy":{"username":"devops-agent"},"sync":{"syncStrategy":{"hook":{}}}}}'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {"error": result.stderr}
        return {
            "app": app_name,
            "action": "sync_triggered",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


def send_slack_alert(severity: str, summary: str, root_cause: str,
                     evidence: str, action_taken: str, recommendation: str) -> dict:
    """Send structured alert to Slack."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return {"error": "SLACK_WEBHOOK_URL not set"}

    emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(severity, "⚪")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text",
                         "text": f"{emoji} {severity} — {summary}"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Root Cause*\n{root_cause}"},
                    {"type": "mrkdwn", "text": f"*Action Taken*\n{action_taken}"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Evidence*\n```{evidence[:500]}```"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": f"*Recommendation*\n{recommendation}"}
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn",
                               "text": f"DevOps Agent · {timestamp}"}]
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=message, timeout=10)
        return {"status": "sent", "http_code": resp.status_code}
    except Exception as e:
        return {"error": str(e)}


# ── Tool dispatcher — routes tool name to function ────────────────────────────
def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool by name and return result as JSON string."""
    tools = {
        "list_pods": list_pods,
        "get_pod_logs": get_pod_logs,
        "get_pod_status": get_pod_status,
        "get_argocd_app_status": get_argocd_app_status,
        "get_recent_commits": get_recent_commits,
        "get_pipeline_status": get_pipeline_status,
        "sync_argocd_app": sync_argocd_app,
        "send_slack_alert": send_slack_alert,
    }
    func = tools.get(tool_name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    result = func(**tool_input)
    return json.dumps(result, indent=2)