# Community Health Navigator

AI-powered Decision Intelligence Platform for healthcare access and community wellness, built on Google Cloud (ADK + Gemini).

- **Architecture:** see [`architecture.md`](architecture.md)
- **Deployment:** see [`DEPLOYMENT.md`](DEPLOYMENT.md)

## Layout

```
services/api      FastAPI public API (auth, sessions, SSE bridge, signed uploads)
services/agent    ADK multi-agent app (Navigator + Knowledge/Analytics/Forecast/Action)
services/worker   Pub/Sub consumer (referrals, subscriptions, alerts, notifications)
functions/        Cloud Functions gen2 (ingest, model refresh, anomaly scan, reindex)
web/              React (Vite) chat UI + analyst dashboard
data/             BigQuery DDL, BQML model SQL, synthetic seed generator, sample docs
infra/            setup.sh (GCP provisioning) + cloudbuild.yaml
shared/           Pydantic schemas — single source of truth for cross-service payloads
```

## Local development

```bash
pip install -r services/agent/requirements.txt -r services/api/requirements.txt
export GOOGLE_CLOUD_PROJECT=<project> CONFIG_PATH=$PWD/config.yaml PYTHONPATH=$PWD

# terminal 1 — agent service
uvicorn main:app --app-dir services/agent --port 8081
# terminal 2 — API (points at agent)
AGENT_URL=http://localhost:8081 AUTH_MODE=demo uvicorn main:app --app-dir services/api --port 8080
# terminal 3 — web
cd web && npm install && npm run dev
```

`AUTH_MODE=demo` bypasses Firebase auth and derives the user from the `X-Demo-User` header — local dev only.
