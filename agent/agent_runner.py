"""
Agent Runner — the core reasoning loop.

This is where Claude (the LLM) receives a situation, decides which
MCP tools to call, interprets the results, and builds a diagnosis.

The loop continues until Claude stops requesting tools and produces
its final response — which triggers a Slack report.
"""

import anthropic
import json
import os
from datetime import datetime, timezone
from mcp_tools import TOOL_DEFINITIONS, execute_tool


# ── System prompt — defines the agent's role and behaviour ───────────────────
# This is what shapes how Claude reasons. It's not just a description —
# it's the operating mandate the model follows throughout the entire loop.

SYSTEM_PROMPT = """You are an expert DevOps AI agent responsible for monitoring 
and diagnosing issues in a Kubernetes-based deployment platform.

Your environment:
- AKS cluster running game-2048 application
- Two namespaces: game-dev (1 replica) and game-prod (2 replicas)
- ArgoCD manages deployments via GitOps (watches GitHub repo)
- CI pipeline: ci.yaml builds and pushes images on dev branch push
- CD pipeline: cd-prod.yaml promotes tested images to prod

Your responsibilities:
1. Investigate deployment issues thoroughly using available tools
2. Always gather evidence before forming a conclusion
3. Check multiple sources: pod status, logs, ArgoCD status, recent commits
4. Identify the ROOT CAUSE — not just the symptom
5. Take action only when you are confident it is safe and correct
6. Always send a Slack alert as your final step with full diagnosis

Your reasoning style:
- Think step by step — explain what you are checking and why
- Be specific — reference exact pod names, error messages, commit SHAs
- Be honest about uncertainty — say if you need more information
- Prioritise prod issues over dev issues
- Never trigger sync_argocd_app without first confirming it is safe to do so

Tool usage rules:
- Start with list_pods to get an overview
- Use get_pod_status before get_pod_logs for efficiency
- Cross-reference pod issues with recent commits using get_recent_commits
- Always end with send_slack_alert regardless of outcome"""


def run_agent(trigger_context: dict) -> str:
    """
    Run the agent reasoning loop for a given trigger context.

    trigger_context contains:
      - namespace:  which namespace triggered the investigation
      - issue:      plain English description of what was detected
      - severity:   initial severity estimate (CRITICAL/WARNING/INFO)

    Returns the agent's final diagnosis as a string.
    """

    # Initialise the Anthropic client
    # API key is read from ANTHROPIC_API_KEY environment variable
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    print(f"\n{'='*60}")
    print(f"AGENT TRIGGERED: {datetime.now(timezone.utc).isoformat()}")
    print(f"Context: {json.dumps(trigger_context, indent=2)}")
    print(f"{'='*60}\n")

    # Build the initial user message
    # This is the situation description the agent starts from
    initial_message = f"""
DevOps issue detected. Please investigate and diagnose.

Trigger context:
- Namespace: {trigger_context.get('namespace', 'unknown')}
- Issue detected: {trigger_context.get('issue', 'Unknown issue')}
- Initial severity: {trigger_context.get('severity', 'WARNING')}
- Detected at: {datetime.now(timezone.utc).isoformat()}

Please investigate this issue thoroughly using your available tools.
Start by listing pods in the affected namespace, then dig deeper based
on what you find. Check ArgoCD status and recent commits as well.
End your investigation by sending a Slack alert with your full diagnosis.
"""

    # ── Agentic loop ──────────────────────────────────────────────────────────
    # messages holds the full conversation history between us and Claude.
    # Each tool call and result is appended here so Claude has full context.

    messages = [{"role": "user", "content": initial_message}]
    max_iterations = 10   # safety limit — prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Agent iteration {iteration} ---")

        # Send current conversation to Claude
        # tools= tells Claude what tools are available
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages
        )

        print(f"Stop reason: {response.stop_reason}")

        # ── Check why Claude stopped ──────────────────────────────────────────
        # stop_reason == "tool_use"   → Claude wants to call a tool
        # stop_reason == "end_turn"   → Claude is done reasoning

        if response.stop_reason == "end_turn":
            # Claude has finished its investigation
            # Extract the final text response
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            print(f"\n{'='*60}")
            print("AGENT COMPLETED INVESTIGATION")
            print(f"{'='*60}")
            print(final_text)
            return final_text

        elif response.stop_reason == "tool_use":
            # Claude wants to call one or more tools
            # Add Claude's response to message history
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Process each tool call in this response
            # Claude can request multiple tools in one response
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    print(f"\n→ Tool call: {tool_name}")
                    print(f"  Input: {json.dumps(tool_input, indent=2)}")

                    # Execute the tool
                    result = execute_tool(tool_name, tool_input)

                    print(f"  Result preview: {result[:200]}...")

                    # Collect result to send back to Claude
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            # Send all tool results back to Claude
            # Claude will use these to continue its reasoning
            messages.append({
                "role": "user",
                "content": tool_results
            })

        else:
            # Unexpected stop reason — break safely
            print(f"Unexpected stop reason: {response.stop_reason}")
            break

    return "Agent reached maximum iterations without completing investigation."


def run_health_check():
    """
    Run a proactive health check across both environments.
    Called on a schedule to detect issues before they escalate.
    """
    print("\nRunning proactive health check...")

    trigger = {
        "namespace": "game-dev",
        "issue": "Scheduled health check — verify all deployments are healthy",
        "severity": "INFO"
    }
    return run_agent(trigger)


if __name__ == "__main__":
    # Quick test — run a health check against the live cluster
    # Usage: python agent_runner.py
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        run_health_check()
    else:
        # Default: investigate a sample issue
        test_trigger = {
            "namespace": "game-dev",
            "issue": "Pod restart count elevated — possible crash loop",
            "severity": "WARNING"
        }
        run_agent(test_trigger)