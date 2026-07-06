#!/usr/bin/env bash
# One-time GCP provisioning for Community Health Navigator.
# Prereqs: gcloud CLI authenticated (gcloud auth login), billing-enabled project.
# Usage:   PROJECT_ID=my-project ./infra/setup.sh
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
DATASET="${DATASET:-community_health}"
DATASTORE_ID="${DATASTORE_ID:-health-knowledge}"
REPO="${REPO:-chn}"

DATA_BUCKET="${PROJECT_ID}-health-data"
DOCS_BUCKET="${PROJECT_ID}-health-docs"
UPLOAD_BUCKET="${PROJECT_ID}-health-uploads"

gcloud config set project "$PROJECT_ID"

echo "==> 1/8 Enabling APIs"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com discoveryengine.googleapis.com \
  bigquery.googleapis.com firestore.googleapis.com pubsub.googleapis.com \
  cloudfunctions.googleapis.com eventarc.googleapis.com cloudscheduler.googleapis.com \
  storage.googleapis.com iamcredentials.googleapis.com

echo "==> 2/8 Artifact Registry"
gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" 2>/dev/null || echo "    repo exists"

echo "==> 3/8 Firestore (native mode)"
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "    db exists"

echo "==> 4/8 Buckets"
for b in "$DATA_BUCKET" "$DOCS_BUCKET" "$UPLOAD_BUCKET"; do
  gcloud storage buckets create "gs://$b" --location="$REGION" 2>/dev/null || echo "    $b exists"
done
# Uploaded citizen images auto-delete after 1 day (privacy, architecture §6.5)
cat > /tmp/lifecycle.json <<'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]}
EOF
gcloud storage buckets update "gs://$UPLOAD_BUCKET" --lifecycle-file=/tmp/lifecycle.json

echo "==> 5/8 BigQuery dataset"
bq --location="$REGION" mk --dataset "$PROJECT_ID:$DATASET" 2>/dev/null || echo "    dataset exists"

echo "==> 6/8 Pub/Sub topics (+ dead letter)"
for t in action-intents alert-events chn-dead-letter; do
  gcloud pubsub topics create "$t" 2>/dev/null || echo "    $t exists"
done

echo "==> 7/8 Service accounts + IAM"
for sa in chn-api chn-agent chn-worker chn-functions chn-pubsub-push; do
  gcloud iam service-accounts create "$sa" --display-name="$sa" 2>/dev/null || echo "    $sa exists"
done
SA="serviceAccount"
P="$PROJECT_ID"
grant() { gcloud projects add-iam-policy-binding "$P" --member="$SA:$1@$P.iam.gserviceaccount.com" --role="$2" --condition=None -q >/dev/null; }

# API: Firestore, signed URLs (uploads bucket), token creator for signBlob
grant chn-api roles/datastore.user
grant chn-api roles/iam.serviceAccountTokenCreator
gcloud storage buckets add-iam-policy-binding "gs://$UPLOAD_BUCKET" \
  --member="$SA:chn-api@$P.iam.gserviceaccount.com" --role=roles/storage.objectAdmin -q >/dev/null
# Agent: Gemini, BigQuery read+jobs, Vertex AI Search, Firestore, publish intents
grant chn-agent roles/aiplatform.user
grant chn-agent roles/bigquery.dataViewer
grant chn-agent roles/bigquery.jobUser
grant chn-agent roles/discoveryengine.viewer
grant chn-agent roles/datastore.user
grant chn-agent roles/pubsub.publisher
grant chn-agent roles/storage.objectViewer      # read uploaded images
# Worker: Firestore writes
grant chn-worker roles/datastore.user
# Functions: BigQuery load/query, publish alerts, GCS read, datastore import
grant chn-functions roles/bigquery.admin
grant chn-functions roles/pubsub.publisher
grant chn-functions roles/storage.objectViewer
grant chn-functions roles/discoveryengine.editor

echo "==> 8/8 Vertex AI Search datastore"
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: $PROJECT_ID" \
  "https://discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/global/collections/default_collection/dataStores?dataStoreId=$DATASTORE_ID" \
  -d '{"displayName":"health-knowledge","industryVertical":"GENERIC","solutionTypes":["SOLUTION_TYPE_SEARCH"],"contentConfig":"CONTENT_REQUIRED"}' \
  | grep -q '"name"\|ALREADY_EXISTS' && echo "    datastore ready (or creating)"

echo ""
echo "Setup complete. Next: DEPLOYMENT.md step 3 (seed data) onward."
