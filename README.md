# Application Autohealer

This repository contains an automated Kubernetes self-healing demo running on GKE.

## Overview

- `agent/` contains the auto-healer agents.
  - `agent_isolator.py`: detects unhealthy pods, restarts them, and marks the deployment for repair.
  - `agent_repairer.py`: watches for deployments marked for repair and attempts remediation (Claude decides `restart_pod`, `rollback_deployment`, or `escalate`).
- `backend/` is a Node.js + React data entry admin app (see `backend/README.md`) — also the workload used for the rollback validation scenario below.
- `frontend/` is a static demo page.
- `k8s/` contains Kubernetes manifests for the namespace, app workloads, agents, and failure simulators.

## Auto-healing flow

When a recoverable app failure happens, the agents should do the following:

1. `autopilot-isolator` detects the unhealthy pod.
2. It isolates the unhealthy pod by deleting it; if the pod is managed by a Deployment, Kubernetes may recreate it automatically.
3. It labels the deployment with `autohealer/repair-needed=true` and `autohealer/failure-reason=...`.
4. `autopilot-repairer` sees the label and diagnoses the deployment.
5. If it decides the failure is due to a bad image or deployment regression, it runs `kubectl rollout undo`.
6. If it decides the failure is a transient crash, it restarts the pod.
7. If neither will help (e.g. a broken probe or bad config), it escalates and leaves the repair-needed label in place for a human.
8. If repair succeeds, it clears the repair labels.

## How to validate the agents

Application endpoint: http://35.188.223.248:8000/ (confirm the current IP with `kubectl get svc -n autohealer backend`)

### 1) Backend rollback (`rollback_deployment` path)

Trigger a bad image on the backend deployment:

```bash
kubectl set image deployment/backend backend=gcr.io/auto-app-healer/autopilot-backend:invalidtag -n autohealer
```

Watch the pod cycle through the failure and recovery:

```bash
kubectl get pods -n autohealer -l app=backend -w
```

In another pane, watch the repairer's diagnosis and rollback in real time:

```bash
kubectl logs -n autohealer deployment/autopilot-repairer -f --tail=20 | grep -A3 -i backend
```

**Expected**: pod goes `ImagePullBackOff` → isolator deletes/labels it → repairer decides `rollback_deployment` → `kubectl rollout undo` succeeds → new pod comes up `Running` `1/1` on the prior working image.

### 2) Crash loop (`crash-simulator`, `restart_pod` path)

Already cycling continuously in the `autohealer` namespace — no injection needed, just observe:

```bash
kubectl get pods -n autohealer -l app=crash-simulator -w
```

```bash
kubectl logs -n autohealer deployment/autopilot-repairer -f --tail=20 | grep -A5 -i crash-simulator
```

**Expected**: no `Unexpected error in repairer loop` line in the repairer logs, and either `Restarted pod ... deleted — Kubernetes will restart it` (when Claude picks `restart_pod`) or a clean `ESCALATION REQUIRED` (once restart count climbs) — either way, the loop keeps running afterward instead of dying.

### Full agent trace

Useful for a live demo — run these two in split panes. You'll see the isolator flag pods every `POLL_INTERVAL` seconds and the repairer print its `Repair decision` JSON (Claude's diagnosis: `action`, `target`, `reason`) for each one live.

```bash
kubectl logs -n autohealer deployment/autopilot-isolator -f --tail=20
```

```bash
kubectl logs -n autohealer deployment/autopilot-repairer -f --tail=20
```

## Automated validation

```bash
cd agent
python validate_simulators.py
```

## Important note about pod recreation

If a pod is managed by a Deployment, Kubernetes will normally recreate it when it is deleted or when it crashes. That means you should not expect a Deployment-managed pod to remain permanently failed without a replacement. The current agent implementation isolates the unhealthy pod by deleting it, so replacement by the ReplicaSet controller is expected.

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
