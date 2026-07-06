# Deploying Community Health Navigator to Google Cloud — Step by Step

Everything below is copy-paste-able. Commands assume **bash** (Cloud Shell works
perfectly and has every tool pre-installed). Estimated time: ~45 minutes, most of
it waiting for the Vertex AI Search index.

---

## 0. Prerequisites

- A Google Cloud project with **billing enabled**.
- `gcloud` CLI ≥ 470 (`gcloud version`), `bq`, and `curl` — all present in Cloud Shell.
- Python 3.12+ locally (only for generating seed data).
- Your account needs `roles/owner` (or Editor + Security Admin) on the project.

```bash
gcloud auth login
export PROJECT_ID=<your-project-id>
export REGION=us-central1
gcloud config set project $PROJECT_ID
```

Get the code onto the machine you deploy from (Cloud Shell: `git clone` or drag-drop
upload), then:

```bash
cd community-health-navigator
```

---

## 1. Provision base infrastructure (one time)

```bash
chmod +x infra/setup.sh
PROJECT_ID=$PROJECT_ID REGION=$REGION ./infra/setup.sh
```

This enables all APIs and creates: Artifact Registry repo `chn`, Firestore (native),
3 buckets (`*-health-data`, `*-health-docs`, `*-health-uploads` with 1-day
auto-delete), BigQuery dataset `community_health`, Pub/Sub topics
(`action-intents`, `alert-events`, `chn-dead-letter`), 5 service accounts with
least-privilege roles, and the Vertex AI Search datastore `health-knowledge`.

> If the datastore step prints an error other than ALREADY_EXISTS, create it in the
> console instead: **AI Applications → Data Stores → Create** → Cloud Storage →
> unstructured documents → name `health-knowledge`, location `global`.

---

## 2. Seed data: generate, upload, load

```bash
# 2.1 Generate synthetic JSONL (deterministic; ~45k rows)
python data/seed/generate_seed.py

# 2.2 Upload seeds + knowledge docs
gcloud storage cp data/seed/out/*.jsonl gs://$PROJECT_ID-health-data/seed/
gcloud storage cp data/docs/*.md        gs://$PROJECT_ID-health-docs/docs/
```

---

## 3. Deploy the Cloud Functions

```bash
FN_SA=chn-functions@$PROJECT_ID.iam.gserviceaccount.com

gcloud functions deploy ingest-datasets --gen2 --region=$REGION --runtime=python312 \
  --source=functions/ingest_datasets --entry-point=ingest --trigger-http \
  --no-allow-unauthenticated --service-account=$FN_SA --timeout=300s \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID,DATA_BUCKET=$PROJECT_ID-health-data

gcloud functions deploy refresh-models --gen2 --region=$REGION --runtime=python312 \
  --source=functions/refresh_models --entry-point=refresh --trigger-http \
  --no-allow-unauthenticated --service-account=$FN_SA --timeout=540s \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID

gcloud functions deploy anomaly-scan --gen2 --region=$REGION --runtime=python312 \
  --source=functions/anomaly_scan --entry-point=scan --trigger-http \
  --no-allow-unauthenticated --service-account=$FN_SA --timeout=300s \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID,ALERT_TOPIC=alert-events

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$FN_SA" \
    --role="roles/eventarc.eventReceiver"
	
gcloud projects add-iam-policy-binding $PROJECT_ID  \
    --member="serviceAccount:$FN_SA" \
    --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$FN_SA" \
    --role="roles/eventarc.serviceAgent"

# GCS-triggered reindex (fires whenever a doc is added/updated under docs/)
gcloud functions deploy reindex-docs --gen2 --region=$REGION --runtime=python312 \
  --source=functions/reindex_docs --entry-point=reindex \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=$PROJECT_ID-health-docs" \
  --service-account=$FN_SA \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID,DATASTORE_ID=health-knowledge
```

---

## 4. Load BigQuery + train the forecast model

```bash
# 4.1 Load the 4 tables (takes ~1 min)
curl -sS -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $(gcloud functions describe ingest-datasets --gen2 --region=$REGION --format='value(url)')

# 4.2 Train the ARIMA_PLUS demand model (takes 2–5 min)
curl -sS -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $(gcloud functions describe refresh-models --gen2 --region=$REGION --format='value(url)')

# 4.3 Verify
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) rows FROM community_health.utilization_daily'
bq query --use_legacy_sql=false \
  'SELECT * FROM ML.FORECAST(MODEL community_health.demand_forecast, STRUCT(3 AS horizon)) LIMIT 5'
```

---

## 5. Index the knowledge corpus into Vertex AI Search

The upload in step 2.2 already fired `reindex-docs`. To trigger/verify manually:

```bash
# Manual import (idempotent)
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: $PROJECT_ID" \
  "https://discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/global/collections/default_collection/dataStores/health-knowledge/branches/default_branch/documents:import" \
  -d "{\"gcsSource\":{\"inputUris\":[\"gs://$PROJECT_ID-health-docs/docs/*\"],\"dataSchema\":\"content\"}}"

# List indexed documents (indexing takes 5–15 min after import)
curl -sS -H "Authorization: Bearer $TOKEN" -H "X-Goog-User-Project: $PROJECT_ID" \
  "https://discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/global/collections/default_collection/dataStores/health-knowledge/branches/default_branch/documents"
```

Console check: **AI Applications → Data Stores → health-knowledge → Documents**.

---

## 6. Build & deploy the three Cloud Run services

One command builds all images and deploys agent → worker → API (the API step reads
the agent's URL automatically):

```bash
gcloud builds submit --config infra/cloudbuild.yaml .
```

> **Note:** the MVP deploys `chn-api` with `AUTH_MODE=demo` (identity from the
> `X-Demo-User` header) and `chn-agent` publicly reachable. Hardening for real
> users is in step 10.

Record the URLs:

```bash
export API_URL=$(gcloud run services describe chn-api --region $REGION --format='value(status.url)')
export WORKER_URL=$(gcloud run services describe chn-worker --region $REGION --format='value(status.url)')
echo "API: $API_URL"
```

---

## 7. Wire Pub/Sub push subscriptions to the worker

```bash
PUSH_SA=chn-pubsub-push@$PROJECT_ID.iam.gserviceaccount.com

# Pub/Sub needs permission to mint OIDC tokens as the push SA,
# and the push SA needs permission to invoke the worker.
gcloud run services add-iam-policy-binding chn-worker --region=$REGION \
  --member="serviceAccount:$PUSH_SA" --role=roles/run.invoker

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding $PUSH_SA \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator

# Intents (referrals, subscriptions) — 5 attempts then dead-letter (architecture §11)
gcloud pubsub subscriptions create action-intents-push --topic=action-intents \
  --push-endpoint="$WORKER_URL/push" \
  --push-auth-service-account=$PUSH_SA \
  --dead-letter-topic=chn-dead-letter --max-delivery-attempts=5 \
  --ack-deadline=60

# Alert events (anomaly scan fan-out)
gcloud pubsub subscriptions create alert-events-push --topic=alert-events \
  --push-endpoint="$WORKER_URL/push" \
  --push-auth-service-account=$PUSH_SA \
  --dead-letter-topic=chn-dead-letter --max-delivery-attempts=5 \
  --ack-deadline=60

# Let Pub/Sub write to the dead-letter topic
gcloud pubsub topics add-iam-policy-binding chn-dead-letter \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/pubsub.publisher
gcloud pubsub subscriptions create chn-dead-letter-pull --topic=chn-dead-letter
for s in action-intents-push alert-events-push; do
  gcloud pubsub subscriptions add-iam-policy-binding $s \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role=roles/pubsub.subscriber
done
```

---

## 8. Schedules + Firestore indexes

```bash
SCHED_SA=chn-functions@$PROJECT_ID.iam.gserviceaccount.com
fn_url() { gcloud functions describe $1 --gen2 --region=$REGION --format='value(url)'; }
for fn in ingest-datasets refresh-models anomaly-scan; do
  gcloud functions add-invoker-policy-binding $fn --gen2 --region=$REGION \
    --member="serviceAccount:$SCHED_SA"
done

gcloud scheduler jobs create http nightly-ingest --location=$REGION \
  --schedule="0 2 * * *" --uri="$(fn_url ingest-datasets)" --http-method=POST \
  --oidc-service-account-email=$SCHED_SA
gcloud scheduler jobs create http weekly-model-refresh --location=$REGION \
  --schedule="0 3 * * 1" --uri="$(fn_url refresh-models)" --http-method=POST \
  --oidc-service-account-email=$SCHED_SA
gcloud scheduler jobs create http daily-anomaly-scan --location=$REGION \
  --schedule="0 7 * * *" --uri="$(fn_url anomaly-scan)" --http-method=POST \
  --oidc-service-account-email=$SCHED_SA

# Composite indexes used by /me/items and the worker's subscription matching
gcloud firestore indexes composite create --collection-group=referrals \
  --field-config=field-path=user_id,order=ascending \
  --field-config=field-path=ts,order=descending
gcloud firestore indexes composite create --collection-group=subscriptions \
  --field-config=field-path=user_id,order=ascending \
  --field-config=field-path=ts,order=descending
gcloud firestore indexes composite create --collection-group=subscriptions \
  --field-config=field-path=active,order=ascending \
  --field-config=field-path=signal,order=ascending
```

---

## 9. Smoke test (before touching the frontend)

```bash
# 9.1 Health
curl -s $API_URL/healthz          # {"status":"ok","deps":{"firestore":true,"agent":true}}

# 9.2 RAG flow (Flow A) — grounded answer with citations
curl -sN -X POST $API_URL/api/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Demo-User: smoke-1' \
  -d '{"message":"Do I qualify for the county wellness program if I am on Medicaid?","persona":"citizen"}'

# 9.3 Analytics flow (Flow B) — NL->SQL, expect chart_spec event
curl -sN -X POST $API_URL/api/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Demo-User: smoke-1' -H 'X-Persona: analyst' \
  -d '{"message":"Compare er vs urgent visits by district over the last 6 months","persona":"analyst"}'

# 9.4 Forecast flow (Flow C)
curl -sN -X POST $API_URL/api/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Demo-User: smoke-1' -H 'X-Persona: analyst' \
  -d '{"message":"Projected clinic demand for the next 4 weeks by district","persona":"analyst"}'

# 9.5 Action flow (Flow D) — two turns; reuse the session_id from the first response
curl -sN -X POST $API_URL/api/v1/chat -H 'Content-Type: application/json' \
  -H 'X-Demo-User: smoke-1' \
  -d '{"message":"Alert me by email when AQI goes above 150","persona":"citizen"}'
# copy "session_id" from the stream's first event, then:
curl -sN -X POST $API_URL/api/v1/chat -H 'Content-Type: application/json' \
  -H 'X-Demo-User: smoke-1' \
  -d '{"session_id":"<SESSION_ID>","message":"yes","persona":"citizen"}'

# 9.6 Verify the worker executed it
curl -s $API_URL/api/v1/me/items -H 'X-Demo-User: smoke-1'
```

Every stream should end with a `done` event. If 9.2 errors, check
`gcloud logging read 'resource.labels.service_name="chn-agent"' --limit 20`.

---

## 10. Frontend

**Option A — local (fastest for a demo):**
```bash
cd web && npm install
echo "VITE_API_URL=$API_URL" > .env.local
npm run dev            # http://localhost:5173
```

**Option B — Firebase Hosting:**
```bash
npm install -g firebase-tools
firebase login
cp .firebaserc.example .firebaserc     # put your project id inside
cd web && npm install
echo "VITE_API_URL=$API_URL" > .env.production
npm run build
firebase deploy --only hosting
```

**Real auth (recommended before sharing the URL):**
1. Firebase console → Authentication → enable **Anonymous** (citizens) and
   **Email/Password** (analysts).
2. Put the web-app config JSON into `VITE_FIREBASE_CONFIG` and rebuild.
3. Redeploy the API in firebase mode:
   `gcloud run services update chn-api --region $REGION --update-env-vars AUTH_MODE=firebase`
4. Give an analyst the persona claim (one-time, e.g. via `firebase-admin` script):
   `auth.set_custom_user_claims(uid, {"persona": "analyst"})`

---

## 11. Production hardening (post-hackathon, architecture §14)

- **Agent service:** redeploy with `--no-allow-unauthenticated`, grant
  `chn-api` SA `roles/run.invoker` on it, and add an ID-token header
  (`google.auth` `fetch_id_token(audience=AGENT_URL)`) to the API's httpx calls.
- API behind **API Gateway + Cloud Armor**; per-user rate limits.
- **VPC-SC** perimeter around BigQuery/Firestore/Storage; CMEK if PHI ever enters.
- Move the ADK app to **Vertex AI Agent Engine**; pin model versions per release.
- CI: run `pytest services/agent/tests` and the eval golden sets in Cloud Build
  before the deploy steps.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `chat` returns error event `upstream` | AGENT_URL wrong or agent crashed — `gcloud run services logs read chn-agent --region $REGION` |
| RAG answers "don't have that in my sources" for everything | Vertex AI Search still indexing (wait 15 min) or import failed — check step 5 document list |
| Analytics flow always apologizes | BQ tables empty (rerun step 4.1) or agent SA missing `bigquery.jobUser` |
| Forecast errors | Model not trained yet (step 4.2) or <2 months of history |
| Confirmed action never appears in `/me/items` | Push subscription missing/misconfigured (step 7); check `chn-worker` logs and the dead-letter pull sub |
| Signed upload URL 403 on PUT | `chn-api` SA lacks `storage.objectAdmin` on the uploads bucket or `iam.serviceAccountTokenCreator` on itself |
| Firestore `FAILED_PRECONDITION: requires an index` | Indexes from step 8 still building — check console → Firestore → Indexes |

## 13. Teardown

```bash
gcloud run services delete chn-api chn-agent chn-worker --region $REGION -q
for fn in ingest-datasets refresh-models anomaly-scan reindex-docs; do
  gcloud functions delete $fn --gen2 --region=$REGION -q; done
gcloud scheduler jobs delete nightly-ingest weekly-model-refresh daily-anomaly-scan --location=$REGION -q
gcloud pubsub subscriptions delete action-intents-push alert-events-push chn-dead-letter-pull -q
gcloud pubsub topics delete action-intents alert-events chn-dead-letter -q
bq rm -r -f -d $PROJECT_ID:community_health
gcloud storage rm -r gs://$PROJECT_ID-health-data gs://$PROJECT_ID-health-docs gs://$PROJECT_ID-health-uploads
# Firestore + the Vertex AI Search datastore are deleted from the console.
```
