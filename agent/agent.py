import os
import time
import json
import logging
import anthropic
from tools import (
    get_unhealthy_pods,
    get_pod_logs,
    describe_pod,
    get_events,
    restart_pod,
    rollout_undo,
    rollout_status,
)
from prompts import SYSTEM_PROMPT, build_diagnosis_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("autopilot-agent")

NAMESPACE = os.getenv("NAMESPACE", "default")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ask_claude(pod_info: dict, logs: str, describe: str, events: str) -> dict:
    user_msg = build_diagnosis_prompt(pod_info, logs, describe, events)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    # extract JSON even if wrapped in markdown code block
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def derive_deployment_name(pod_name: str) -> str:
    # strip last two hash segments: <deploy>-<rs-hash>-<pod-hash>
    parts = pod_name.rsplit("-", 2)
    return parts[0] if len(parts) == 3 else pod_name


def execute_action(plan: dict) -> str:
    action = plan.get("action")
    target = plan.get("target", "")

    if action == "restart_pod":
        result = restart_pod(target, NAMESPACE)
        log.info("Restarted pod %s: %s", target, result)
        return result

    elif action == "rollback_deployment":
        deployment = derive_deployment_name(target)
        result = rollout_undo(deployment, NAMESPACE)
        log.info("Rolled back deployment %s: %s", deployment, result)
        time.sleep(5)
        status = rollout_status(deployment, NAMESPACE)
        log.info("Post-rollback status: %s", status)
        return f"{result}\n{status}"

    elif action == "escalate":
        msg = f"ESCALATION REQUIRED for {target}: {plan.get('reason')}"
        log.warning(msg)
        return msg

    else:
        log.info("No action taken for %s.", target)
        return "no_action"


def run_once():
    log.info("Scanning namespace '%s' for unhealthy pods...", NAMESPACE)
    unhealthy = get_unhealthy_pods(NAMESPACE)

    if not unhealthy:
        log.info("All pods healthy.")
        return

    log.warning("Found %d unhealthy pod(s): %s", len(unhealthy), unhealthy)

    for pod_info in unhealthy:
        pod = pod_info["pod"]
        log.info("Diagnosing pod: %s (reason: %s)", pod, pod_info["reason"])

        logs = get_pod_logs(pod, NAMESPACE)
        describe = describe_pod(pod, NAMESPACE)
        events = get_events(NAMESPACE)

        try:
            plan = ask_claude(pod_info, logs, describe, events)
        except Exception as e:
            log.error("Claude API error for pod %s: %s", pod, e)
            continue

        log.info("Claude decision: %s", json.dumps(plan, indent=2))
        result = execute_action(plan)
        log.info("Action result: %s", result)


def main():
    log.info("Autopilot agent started. Poll interval: %ds", POLL_INTERVAL)
    while True:
        try:
            run_once()
        except Exception as e:
            log.error("Unexpected error in agent loop: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
