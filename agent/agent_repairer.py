import os
import time
import json
import logging
from common import log, NAMESPACE, POLL_INTERVAL, client
from rag_memory import RepairRAGStore
from tools import (
    get_deployments_with_label,
    get_pods_for_deployment,
    get_pod_logs,
    describe_pod,
    get_events,
    restart_pod,
    rollout_undo,
    rollout_status,
    deployment_exists,
    get_deployment_from_pod,
    remove_deployment_labels,
)
from prompts import SYSTEM_PROMPT, build_diagnosis_prompt

MARKER_LABEL = "autohealer/repair-needed"
RAG_STORAGE_DIR = os.getenv("RAG_STORAGE_DIR", "/tmp/repair-rag")
rag_store = RepairRAGStore(storage_dir=RAG_STORAGE_DIR)


def ask_claude(pod_info: dict, logs: str, describe: str, events: str) -> dict:
    similar_cases = rag_store.search(
        f"{pod_info.get('reason', '')} {logs[:1000]} {describe[:1000]}",
        limit=3,
    )
    user_msg = build_diagnosis_prompt(pod_info, logs, describe, events, similar_cases)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _pod_status_reason(pod: dict) -> str:
    container_statuses = pod.get("status", {}).get("containerStatuses", [])
    for cs in container_statuses:
        state = cs.get("state", {})
        waiting = state.get("waiting", {})
        if waiting.get("reason"):
            return waiting["reason"]
        terminated = state.get("terminated", {})
        if terminated.get("reason"):
            return terminated["reason"]
    conditions = pod.get("status", {}).get("conditions", [])
    for cond in conditions:
        if cond.get("type") == "Ready" and cond.get("status") == "False":
            return cond.get("reason", "NotReady")
    return "Running"


def _choose_repair_pod(pods: list[dict]) -> dict:
    unhealthy_pods = []
    for pod in pods:
        reason = _pod_status_reason(pod)
        if reason not in ("Running", "Succeeded", "Completed"):
            unhealthy_pods.append((reason, pod))
    if unhealthy_pods:
        # Prefer a pod with an explicit failure reason
        return sorted(unhealthy_pods, key=lambda item: item[0] == "NotReady")[0][1]
    return pods[0]


def repair_deployment(deployment: str, pod_info: dict) -> str:
    pods = get_pods_for_deployment(deployment, NAMESPACE)
    if not pods:
        msg = f"No pods found for deployment {deployment}."
        log.warning(msg)
        return msg

    pod = _choose_repair_pod(pods)
    pod_name = pod["metadata"]["name"]
    logs = get_pod_logs(pod_name, NAMESPACE)
    describe = describe_pod(pod_name, NAMESPACE)
    events = get_events(NAMESPACE)

    try:
        plan = ask_claude(pod_info, logs, describe, events)
    except Exception as e:
        log.error("Claude API error for deployment %s: %s", deployment, e)
        return str(e)

    log.info("Repair decision: %s", json.dumps(plan, indent=2))
    action = plan.get("action")
    target = str(plan.get("target", "")).strip()

    if action == "restart_pod":
        result = restart_pod(pod, NAMESPACE)
        log.info("Restarted pod %s: %s", pod, result)
    elif action == "rollback_deployment":
        deployment_name = target or deployment
        if deployment_name.startswith("deployment/"):
            deployment_name = deployment_name.split("/", 1)[1]
        if not deployment_exists(deployment_name, NAMESPACE):
            deployment_name = deployment
        result = rollout_undo(deployment_name, NAMESPACE)
        log.info("Rolled back deployment %s: %s", deployment_name, result)
        time.sleep(5)
        status = rollout_status(deployment_name, NAMESPACE)
        result = f"{result}\n{status}"
    elif action == "escalate":
        result = f"ESCALATION REQUIRED for {deployment}: {plan.get('reason')}"
        log.warning(result)
    else:
        result = "no_action"
        log.info("No action taken for deployment %s.", deployment)

    if action in ("restart_pod", "rollback_deployment"):
        remove_deployment_labels(deployment, [MARKER_LABEL, "autohealer/failure-reason"], NAMESPACE)
        log.info("Cleared repair labels for deployment %s", deployment)

    rag_store.add_case(
        deployment=deployment,
        pod_name=pod_name,
        failure_reason=pod_info.get("reason", "unknown"),
        action=action or "no_action",
        outcome=result,
        logs=logs,
    )

    return result


def run_once():
    deployments = get_deployments_with_label(f"{MARKER_LABEL}=true", NAMESPACE)
    if not deployments:
        log.info("Repairer found no deployments needing repair.")
        return

    for deployment in deployments:
        pods = get_pods_for_deployment(deployment, NAMESPACE)
        if not pods:
            log.warning("No pods for deployment %s, skipping repair.", deployment)
            continue

        pod = pods[0]
        pod_info = {
            "pod": pod["metadata"]["name"],
            "reason": pod.get("status", {}).get("phase", "Unknown"),
            "restarts": pod.get("status", {}).get("containerStatuses", [{}])[0].get("restartCount", 0),
            "container": pod.get("spec", {}).get("containers", [{}])[0].get("name", ""),
        }
        log.info("Repairing deployment %s with pod %s", deployment, pod_info["pod"])
        result = repair_deployment(deployment, pod_info)
        log.info("Repair result for %s: %s", deployment, result)


if __name__ == "__main__":
    log.info("Autopilot repairer started. Poll interval: %ds", POLL_INTERVAL)
    while True:
        try:
            run_once()
        except Exception as e:
            log.error("Unexpected error in repairer loop: %s", e)
        time.sleep(POLL_INTERVAL)
