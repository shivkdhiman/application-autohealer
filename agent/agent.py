import os
import time
import json
import logging
import anthropic
from rag_memory import RepairRAGStore
from tools import (
    get_unhealthy_pods,
    get_pod_logs,
    describe_pod,
    get_events,
    restart_pod,
    rollout_undo,
    rollout_status,
    deployment_exists,
    get_deployment_from_pod,
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
RAG_STORAGE_DIR = os.getenv("RAG_STORAGE_DIR", "/tmp/repair-rag")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
rag_store = RepairRAGStore(storage_dir=RAG_STORAGE_DIR)


def ask_claude(pod_info: dict, logs: str, describe: str, events: str) -> dict:
    similar_cases = rag_store.search(
        f"{pod_info.get('reason', '')} {logs[:1000]} {describe[:1000]}",
        limit=3,
    )
    user_msg = build_diagnosis_prompt(pod_info, logs, describe, events, similar_cases)
    response = client.messages.create(
        model="claude-haiku-4-5",
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


def execute_action(plan: dict, pod_info: dict | None = None) -> str:
    action = plan.get("action")
    target = str(plan.get("target", "")).strip()

    if action == "restart_pod":
        result = restart_pod(target, NAMESPACE)
        log.info("Restarted pod %s: %s", target, result)
        return result

    elif action == "rollback_deployment":
        deployment = target
        if deployment.startswith("deployment/"):
            deployment = deployment.split("/", 1)[1]

        if deployment and not deployment_exists(deployment, NAMESPACE) and pod_info:
            fallback = get_deployment_from_pod(pod_info["pod"], NAMESPACE)
            if fallback:
                log.warning(
                    "Rollback target %s not found; using deployment %s derived from pod %s",
                    deployment,
                    fallback,
                    pod_info["pod"],
                )
                deployment = fallback

        if not deployment and pod_info:
            deployment = get_deployment_from_pod(pod_info["pod"], NAMESPACE)

        if not deployment:
            msg = f"Rollback failed: no valid deployment target for {target}"
            log.error(msg)
            return msg

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
        result = execute_action(plan, pod_info)
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
