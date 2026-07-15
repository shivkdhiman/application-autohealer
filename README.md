# Application Autohealer Shiv Copy

Self-healing Kubernetes demo on GKE. Two agents watch the cluster and use Claude to diagnose and fix failures.

- `autopilot-isolator` — finds unhealthy pods, isolates them, flags the deployment.
- `autopilot-repairer` — diagnoses the flagged deployment with Claude, then `restart_pod`, `rollback_deployment`, or `escalate`.

## Run the demo

1. Watch the cluster: `k9s -n autohealer` (`l` for logs on a selected pod, `Esc` to go back).
2. Pick an error injection below and run it against `backend`.
3. Watch it recover (or escalate) in k9s / repairer logs.
4. Revert: `kubectl rollout undo deployment/backend -n autohealer`


## Error injection commands (`backend`)

| Failure | Command | Expected |
|---|---|---|
| Bad image tag | `kubectl set image deployment/backend backend=gcr.io/auto-app-healer/autopilot-backend:invalidtag -n autohealer` | Rolled back automatically |
| Crash on startup | `kubectl patch deployment backend -n autohealer --patch-file k8s/demo-patches/crash-command.json` | Rolled back or escalated |
| Broken liveness probe | `kubectl patch deployment backend -n autohealer --patch-file k8s/demo-patches/broken-liveness.json` | Rolled back or escalated |
| OOM (memory squeeze) | `kubectl patch deployment backend -n autohealer --patch-file k8s/demo-patches/oom-memory.json` | Rolled back or escalated |

Run one at a time, revert before trying the next. (There's no "bad env var" row — `backend/server.js` doesn't read any config env var, so setting one is a no-op on the real app; that logic only existed in the removed `bad-config-simulator`.)

## Useful commands

```bash
kubectl get pods -n autohealer
kubectl get deployments -n autohealer
kubectl describe pod <pod> -n autohealer
kubectl logs -n autohealer -l app=autopilot-isolator --tail=50
kubectl logs -n autohealer -l app=autopilot-repairer --tail=50
```

## Notes Shiv

- Deployment-managed pods get recreated automatically when deleted or crashed — expected, not a bug.
- Images are pushed to `gcr.io/auto-app-healer/...`.
- App details (React admin UI, RAG Memory tab): see `backend/README.md`.
