# Application Autohealer

This repository contains an automated Kubernetes self-healing demo.

## Overview

- `agent/` contains the auto-healer agents.
  - `agent_isolator.py`: detects unhealthy pods, restarts them, and marks the deployment for repair.
  - `agent_repairer.py`: watches for deployments marked for repair and attempts remediation.
- `backend/` and `frontend/` contain the application workloads.
- `k8s/` contains Kubernetes manifests for the namespace, app workloads, agents, and failure simulators.

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

### 2) Probe-based failures (escalation path)

The simulator workloads exercise configuration issues such as broken readiness or liveness probes:

```bash
kubectl get pods -n autohealer
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100
```

Expected behavior:
- The repairer should escalate for probe-related failures because restarting the pod will not fix a broken probe spec.

### 3) Crash loop or OOM scenarios

These workloads are useful for checking how the agents classify transient runtime failures:

```bash
kubectl get pods -n autohealer
kubectl logs -n autohealer deployment/autopilot-repairer --tail=100
```

Expected behavior:
- The repairer may decide to escalate or take no action depending on whether the failure appears transient or configuration-driven.

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
