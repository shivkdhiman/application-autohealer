import subprocess
import json


def _run(cmd: list[str]) -> tuple[str, str, int]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def get_pods(namespace: str = "default") -> dict:
    out, err, code = _run([
        "kubectl", "get", "pods", "-n", namespace,
        "-o", "json"
    ])
    if code != 0:
        return {"error": err}
    return json.loads(out)


def get_pod_logs(pod_name: str, namespace: str = "default", tail: int = 50) -> str:
    out, err, code = _run([
        "kubectl", "logs", pod_name, "-n", namespace,
        f"--tail={tail}", "--previous"
    ])
    if code != 0:
        # try without --previous if pod never started
        out, err, code = _run([
            "kubectl", "logs", pod_name, "-n", namespace, f"--tail={tail}"
        ])
    return out or err


def describe_pod(pod_name: str, namespace: str = "default") -> str:
    out, err, _ = _run(["kubectl", "describe", "pod", pod_name, "-n", namespace])
    return out or err


def restart_pod(pod_name: str, namespace: str = "default") -> str:
    _, err, code = _run(["kubectl", "delete", "pod", pod_name, "-n", namespace])
    if code != 0:
        return f"Failed to delete pod: {err}"
    return f"Pod {pod_name} deleted — Kubernetes will restart it."


def rollout_undo(deployment: str, namespace: str = "default") -> str:
    out, err, code = _run([
        "kubectl", "rollout", "undo", f"deployment/{deployment}", "-n", namespace
    ])
    if code != 0:
        return f"Rollback failed: {err}"
    return out


def rollout_status(deployment: str, namespace: str = "default") -> str:
    out, err, _ = _run([
        "kubectl", "rollout", "status", f"deployment/{deployment}",
        "-n", namespace, "--timeout=30s"
    ])
    return out or err


def get_events(namespace: str = "default") -> str:
    out, err, _ = _run([
        "kubectl", "get", "events", "-n", namespace,
        "--sort-by=.lastTimestamp"
    ])
    return out or err


def get_unhealthy_pods(namespace: str = "default") -> list[dict]:
    data = get_pods(namespace)
    if "error" in data:
        return []
    unhealthy = []
    for pod in data.get("items", []):
        name = pod["metadata"]["name"]
        phase = pod["status"].get("phase", "")
        container_statuses = pod["status"].get("containerStatuses", [])
        for cs in container_statuses:
            state = cs.get("state", {})
            waiting = state.get("waiting", {})
            reason = waiting.get("reason", "")
            restart_count = cs.get("restartCount", 0)
            if reason in ("CrashLoopBackOff", "Error", "OOMKilled") or (
                phase == "Pending" and restart_count > 2
            ):
                unhealthy.append({
                    "pod": name,
                    "reason": reason or phase,
                    "restarts": restart_count,
                    "container": cs["name"],
                })
        # check for failed deployments via pod conditions
        conditions = pod["status"].get("conditions", [])
        for cond in conditions:
            if cond.get("type") == "Ready" and cond.get("status") == "False":
                if not any(u["pod"] == name for u in unhealthy):
                    unhealthy.append({
                        "pod": name,
                        "reason": cond.get("reason", "NotReady"),
                        "restarts": 0,
                        "container": "",
                    })
    return unhealthy
