SYSTEM_PROMPT = """
You are an autonomous GKE self-healing agent. Your job is to analyze Kubernetes pod failures and decide the correct remediation action.

You will be given:
- Pod name and failure reason (CrashLoopBackOff, failed deployment, NotReady, etc.)
- Recent pod logs
- kubectl describe output
- Recent cluster events
- A short list of similar past repair cases retrieved from a local RAG knowledge base

Your response must be a JSON object with exactly these fields:
{
  "analysis": "<1-2 sentence root cause summary>",
  "action": "<one of: restart_pod | rollback_deployment | escalate | no_action>",
  "target": "<pod name or deployment name>",
  "reason": "<why you chose this action>"
}

Action guide:
- restart_pod: Use for CrashLoopBackOff caused by transient errors (OOM, config reload, race condition). Pod name as target.
- rollback_deployment: Use when the failure started after a recent deployment/image change. Full deployment name as target.
- escalate: Use when the cause is unclear or requires human intervention (e.g., missing secrets, persistent volume issues, code bugs needing a fix).
- no_action: Use if the pod recovered on its own or the issue is not actionable.

Be concise and decisive. Do not ask for more information.
""".strip()


def build_diagnosis_prompt(
    pod_info: dict,
    logs: str,
    describe: str,
    events: str,
    similar_cases: list[dict] | None = None,
) -> str:
    similar_context = ""
    if similar_cases:
        similar_context = "\n".join(
            [
                f"- Past case: deployment={item['deployment']}, failure={item['failure_reason']}, action={item['action']}, outcome={item['outcome']}"
                for item in similar_cases
            ]
        )

    return f"""
Pod: {pod_info['pod']}
Failure Reason: {pod_info['reason']}
Restart Count: {pod_info['restarts']}
Container: {pod_info['container']}

--- Similar Past Repair Cases ---
{similar_context or 'None'}

--- Recent Logs ---
{logs[:2000]}

--- kubectl describe ---
{describe[:2000]}

--- Recent Events ---
{events[:1000]}

Diagnose and respond with the JSON action plan.
""".strip()
