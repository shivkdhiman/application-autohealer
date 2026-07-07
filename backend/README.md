# Records Admin App

A simple Node.js + React data entry admin app. No build step: the server is
plain Node (`http`, `fs`, no dependencies), and the frontend loads React 18 +
Babel standalone directly via `<script>` tags from `public/`.

## Run locally

```bash
node server.js
```

Then open http://localhost:8000 in a browser. Set `PORT` to use a different port:

```bash
PORT=3000 node server.js
```

## Run with Docker

```bash
docker build -t records-admin .
docker run -p 8000:8000 records-admin
```

## Structure

- `server.js` — Node HTTP server: serves `public/` as static files and exposes the API below.
- `public/index.html`, `public/app.jsx`, `public/styles.css` — React UI (JSX transpiled in-browser via Babel standalone, no bundler).
- `data/records.json` — local JSON file storage for records. Created automatically if missing.

## API

- `GET /api/records` — list all records.
- `POST /api/records` — create a record. Body: `{ name, dob, jobTitle, notes }`. `name`, `dob`, and `jobTitle` are required; `notes` is optional and limited to 2000 characters.
- `DELETE /api/records/:id` — delete a record by id.
- `GET /api/rag` — proxies the auto-healer's RAG repair-case memory from the `autopilot-repairer` agent (see below). Returns `502` with an error message if the agent's RAG service isn't reachable.
- `GET /health` — health check (used by the Kubernetes probes in `k8s/backend-deployment.yaml`).

## RAG Memory tab

The "RAG Memory" tab in the UI shows the repair cases the `autopilot-repairer` agent has recorded (deployment, pod, failure reason, action taken, outcome, and full logged context — see `agent/rag_memory.py`).

This works by the agent exposing its own small HTTP server (`GET /rag` on port 8001, added in `agent/agent_repairer.py`), backed by a Kubernetes `ClusterIP` Service named `autopilot-repairer` (see `k8s/agent-deployment.yaml`). This backend proxies to it via `GET /api/rag`.

- In-cluster, this resolves automatically via `http://autopilot-repairer.autohealer.svc.cluster.local:8001/rag`.
- Outside the cluster (e.g. running `node server.js` locally), set `RAG_SERVICE_URL` to point at wherever that endpoint is reachable, or the tab will just show a "service unreachable" message.

## Notes

- Data is stored on the container's local filesystem (`data/records.json`), so it does not persist across pod restarts unless a volume is mounted. The same applies to the agent's RAG store (`RAG_STORAGE_DIR`, default `/tmp/repair-rag`).
- Search and refresh in the Admin Dashboard tab operate on the current record list fetched from `GET /api/records`.
