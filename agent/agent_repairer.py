import os
import time
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
    get_rollout_revision_count,
)
from prompts import SYSTEM_PROMPT, build_diagnosis_prompt

MARKER_LABEL = "autohealer/repair-needed"
RAG_STORAGE_DIR = os.getenv("RAG_STORAGE_DIR", "/tmp/repair-rag")
RAG_HTTP_PORT = int(os.getenv("RAG_HTTP_PORT", "8001"))
rag_store = RepairRAGStore(storage_dir=RAG_STORAGE_DIR)


class RagRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/rag"):
            try:
                data = rag_store.list_recent(limit=100)
                body = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                log.error("RAG HTTP endpoint error: %s", e)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        elif self.path.startswith("/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_rag_http_server():
    server = HTTPServer(("0.0.0.0", RAG_HTTP_PORT), RagRequestHandler)
    log.info("RAG HTTP server listening on port %d", RAG_HTTP_PORT)
    server.serve_forever()


def ask_claude(pod_info: dict, logs: str, describe: str, events: str, revision_count: int = 0) -> dict:
    similar_cases = rag_store.search(
        f"{pod_info.get('reason', '')} {logs[:1000]} {describe[:1000]}",
        limit=3,
    )
    user_msg = build_diagnosis_prompt(pod_info, logs, describe, events, similar_cases, revision_count)
    response = client.messages.create(
        model="claude-haiku-4-5",
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


def repair_deployment(deployment: str, pods: list[dict]) -> str:
    pod = _choose_repair_pod(pods)
    pod_name = pod["metadata"]["name"]
    pod_info = {
        "pod": pod_name,
        "reason": _pod_status_reason(pod),
        "restarts": pod.get("status", {}).get("containerStatuses", [{}])[0].get("restartCount", 0),
        "container": pod.get("spec", {}).get("containers", [{}])[0].get("name", ""),
    }
    logs = get_pod_logs(pod_name, NAMESPACE)
    describe = describe_pod(pod_name, NAMESPACE)
    events = get_events(NAMESPACE)
    revision_count = get_rollout_revision_count(deployment, NAMESPACE)

    try:
        plan = ask_claude(pod_info, logs, describe, events, revision_count)
    except Exception as e:
        log.error("Claude API error for deployment %s: %s", deployment, e)
        return str(e)

    log.info("Repair decision: %s", json.dumps(plan, indent=2))
    action = plan.get("action")
    target = str(plan.get("target", "")).strip()

    if action == "rollback_deployment" and revision_count <= 1:
        log.warning(
            "Repairer chose rollback_deployment for %s but no prior revision exists (revision_count=%d); "
            "downgrading to escalate instead of attempting a rollback that cannot succeed.",
            deployment, revision_count,
        )
        action = "escalate"
        plan["reason"] = f"{plan.get('reason', '')} (downgraded from rollback_deployment: no prior revision available)"

    succeeded = False
    if action == "restart_pod":
        result = restart_pod(pod_name, NAMESPACE)
        log.info("Restarted pod %s: %s", pod_name, result)
        succeeded = not result.startswith("Failed to delete pod")
    elif action == "rollback_deployment":
        deployment_name = target or deployment
        if deployment_name.startswith("deployment/"):
            deployment_name = deployment_name.split("/", 1)[1]
        if not deployment_exists(deployment_name, NAMESPACE):
            deployment_name = deployment
        result = rollout_undo(deployment_name, NAMESPACE)
        log.info("Rolled back deployment %s: %s", deployment_name, result)
        succeeded = not result.startswith("Rollback failed")
        if succeeded:
            time.sleep(5)
            status = rollout_status(deployment_name, NAMESPACE)
            result = f"{result}\n{status}"
    elif action == "escalate":
        result = f"ESCALATION REQUIRED for {deployment}: {plan.get('reason')}"
        log.warning(result)
    else:
        result = "no_action"
        log.info("No action taken for deployment %s.", deployment)

    if action == "no_action" or (action in ("restart_pod", "rollback_deployment") and succeeded):
        remove_deployment_labels(deployment, [MARKER_LABEL, "autohealer/failure-reason"], NAMESPACE)
        log.info("Cleared repair labels for deployment %s", deployment)
    elif action in ("restart_pod", "rollback_deployment") and not succeeded:
        log.warning("Repair action %s failed for %s, leaving repair-needed label in place: %s", action, deployment, result)

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

        log.info("Repairing deployment %s", deployment)
        result = repair_deployment(deployment, pods)
        log.info("Repair result for %s: %s", deployment, result)


if __name__ == "__main__":
    log.info("Autopilot repairer started. Poll interval: %ds", POLL_INTERVAL)
    threading.Thread(target=start_rag_http_server, daemon=True).start()
    while True:
        try:
            run_once()
        except Exception as e:
            log.error("Unexpected error in repairer loop: %s", e)
        time.sleep(POLL_INTERVAL)
