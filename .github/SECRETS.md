# Required GitHub Secrets

Set these in: GitHub repo → Settings → Secrets and variables → Actions

| Secret | Description |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID, e.g. `my-project-123` |
| `GCP_SA_KEY` | JSON key of a GCP service account with roles: `roles/storage.admin` (for GCR), `roles/container.developer` (for GKE) |
| `GKE_CLUSTER` | GKE cluster name, e.g. `autopilot-cluster` |
| `GKE_ZONE` | GKE cluster zone or region, e.g. `us-central1-a` |
| `ANTHROPIC_API_KEY` | Anthropic API key for the self-healing agent |

## Creating the GCP Service Account

```bash
PROJECT=your-project-id

gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:github-actions@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:github-actions@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/container.developer"

# Download key and paste into GCP_SA_KEY secret
gcloud iam service-accounts keys create key.json \
  --iam-account="github-actions@$PROJECT.iam.gserviceaccount.com"
cat key.json
```
