# Application Autohealer

This repository contains an automated Kubernetes self-healing demo.

## Overview

- `agent/` contains the auto-healer agents.
  - `agent_isolator.py`: detects unhealthy pods, restarts them, and marks the deployment for repair.
  - `agent_repairer.py`: watches for deployments marked for repair and attempts remediation.
- `backend/` and `frontend/` contain the application workloads.
- `k8s/` contains Kubernetes manifests for the namespace, app workloads, agents, and failure simulators.

| Simulator                 | Current Status                           | Interpretation                                                           |
| ------------------------- | ---------------------------------------- | ------------------------------------------------------------------------ |
| `bad-deploy-simulator`    | `ImagePullBackOff`                       | ❌ Still broken. The image name is invalid or the image cannot be pulled. |
| `bad-config-simulator`    | `CrashLoopBackOff` / `Error`             | ⚠️ Pod keeps crashing because of a bad configuration.                    |
| `crash-simulator`         | `CrashLoopBackOff`                       | ⚠️ Container starts and then crashes repeatedly.                         |
| `liveness-fail-simulator` | New pod created after old one terminated | ✅ Kubernetes/AutoHealer restarted it due to liveness probe failures.     |
| `oom-simulator`           | `OOMKilled`                              | ⚠️ Container exceeded its memory limit and was killed.                   |


## Auto-healing flow

When a recoverable app failure happens, the agents should do the following:

1. `autopilot-isolator` detects the unhealthy pod.
2. It isolates the unhealthy pod by deleting it; if the pod is managed by a Deployment, Kubernetes may recreate it automatically.
3. It labels the deployment with `autohealer/repair-needed=true` and `autohealer/failure-reason=...`.
4. `autopilot-repairer` sees the label and diagnoses the deployment.
5. If it decides the failure is due to a bad image or deployment regression, it runs `kubectl rollout undo`.
6. If repair succeeds, it clears the repair labels.

## How to validate the agents

Application endpoint: http://35.188.223.248:8000/health

### 1) Recoverable deployment regression (rollback path)

Use the backend deployment for a rollback-style test:

```bash
kubectl set image deployment/backend backend=gcr.io/auto-app-healer/autopilot-backend:invalidtag -n autohealer
```

Then watch the agents and workload:

```bash
kubectl get pods -n autohealer -l app=backend -w
kubectl logs -n autohealer deployment/autopilot-isolator --tail=100
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100
```

Expected behavior:
- The backend pod enters an error state such as `ImagePullBackOff`.
- The isolator detects the unhealthy pod and marks the deployment for repair.
- The repairer attempts a rollback to the previous working revision.

The other simulators below (`k8s/simulate-crash.yaml`, `k8s/more-simulators.yaml`) are deployed and cycling continuously in the `autohealer` namespace, so no injection is needed — just observe.

Quick overview:

```bash
kubectl get pods -n autohealer
```

### 2) Crash loop (`crash-simulator`)

Container exits immediately. Expect the isolator to detect `CrashLoopBackOff` and restart it, and the repairer to diagnose it (likely **escalate**, since restarting a pod that always exits won't help).

```bash
kubectl describe pod -n autohealer -l app=crash-simulator | tail -30
kubectl get deployment crash-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-isolator --tail=100 | grep -i crash
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i crash-simulator
```

### 3) Bad image / deployment regression (`bad-deploy-simulator`)

Non-existent image tag. Expect the isolator to mark it for repair and the repairer to attempt `rollout undo` (there's no prior good revision here, so watch what it actually decides).

```bash
kubectl describe pod -n autohealer -l app=bad-deploy-simulator | Select-Object -Last 30
kubectl get deployment bad-deploy-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i bad-deploy-simulator
```

### 4) OOM kill (`oom-simulator`)

Steadily allocates memory until OOMKilled. Expect `CrashLoopBackOff`/OOMKilled reason, with the repairer likely **escalating** (transient/runtime, not a rollback candidate).

```bash
kubectl describe pod -n autohealer -l app=oom-simulator | grep -A5 "Last State"
kubectl get deployment oom-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i oom-simulator
```

### 5) Broken readiness probe (`readiness-fail-simulator`)

Pod runs fine but the readiness probe always fails. Expect **escalate**, since restarting won't fix a bad probe spec.

```bash
kubectl describe pod -n autohealer -l app=readiness-fail-simulator | grep -A5 Readiness
kubectl get deployment readiness-fail-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i readiness-fail
```

### 6) Broken liveness probe (`liveness-fail-simulator`)

Liveness probe always fails, so kubelet kills/restarts the container in a loop. Expect **escalate**, for the same reason as above.

```bash
kubectl describe pod -n autohealer -l app=liveness-fail-simulator | grep -A5 Liveness
kubectl get deployment liveness-fail-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i liveness-fail
```

### 7) Bad config (`bad-config-simulator`)

Container exits due to a bad env var. Expect `CrashLoopBackOff`/`Error`, with the repairer likely **escalating** (a config fix isn't something rollback/restart solves).

```bash
kubectl logs -n autohealer -l app=bad-config-simulator --tail=10
kubectl get deployment bad-config-simulator -n autohealer -o jsonpath='{.metadata.labels}{"\n"}'
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100 | grep -A5 -i bad-config
```

### Full agent trace

Useful for a live demo — run these two in split panes. You'll see the isolator flag pods every `POLL_INTERVAL` seconds and the repairer print its `Repair decision` JSON (Claude's diagnosis: `action`, `target`, `reason`) for each one live.

```bash
kubectl logs -n autohealer deployment/autopilot-isolator -f --tail=20
```

```bash
kubectl logs -n autohealer deployment/autopilot-repairer -f --tail=20
```

## Important note about pod recreation

If a pod is managed by a Deployment, Kubernetes will normally recreate it when it is deleted or when it crashes. That means you should not expect a Deployment-managed pod to remain permanently failed without a replacement. The current agent implementation isolates the unhealthy pod by deleting it, so replacement by the ReplicaSet controller is expected. If you want to validate a workload that stays in a failed state without replacement, use a non-Deployment workload or a standalone pod.

## Notes

- The simulator deployments are intentionally failing workloads for testing the agent’s diagnosis and escalation logic.
- Use the backend or frontend app deployments for rollback-style validation.

## Useful commands

```bash
kubectl get pods -n autohealer
kubectl get deployments -n autohealer
kubectl describe pod <pod> -n autohealer
kubectl logs -n autohealer -l app=autopilot-isolator --tail=50
kubectl logs -n autohealer -l app=autopilot-repairer --tail=50
```

## Image registry

The manifests use `gcr.io/auto-app-healer/...` for image names. Ensure that the built images are pushed to this registry and accessible by your cluster.
