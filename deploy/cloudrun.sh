#!/usr/bin/env bash
# One-time bring-up on GCP. Idempotent-ish: rerunning a step that exists is safe.
#
# The flags on the deploy step are load-bearing, not tuning:
#   --no-cpu-throttling  main.py backgrounds work with asyncio.to_thread after the
#                        response is sent; throttled CPU stalls those threads.
#   --max-instances=1    worker.active lives in process memory; a second instance
#                        sees the first one's running cases as stranded and
#                        restarts them.
#   --min-instances=1    the cross-week timeline is the exhibit; an instance that
#                        scales to zero still keeps its history (Cloud SQL), but
#                        the hourly heartbeat should not depend on a cold start.
#   --memory=4Gi         the precedent index holds 218,606 rulings. At 1Gi the
#                        container was killed mid-batch (1030 MiB used) and every
#                        case the agent had open came back stranded.
set -euo pipefail

PROJECT=${PROJECT:-tariff-fleet-2026}
REGION=${REGION:-us-central1}
SQL_INSTANCE=fleet-pg
DB=fleet
DB_USER=fleet

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com

# Smallest shared-core Postgres; the store is a demo-scale audit trail.
gcloud sql instances create "$SQL_INSTANCE" \
  --database-version=POSTGRES_17 --tier=db-f1-micro --region="$REGION" \
  --storage-size=10 --storage-type=HDD || true
gcloud sql databases create "$DB" --instance="$SQL_INSTANCE" || true
DB_PASS=$(openssl rand -hex 16)
gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS" \
  || gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS"

CONN=$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(connectionName)')

# The default compute service account is what the container runs as; without
# aiplatform.user every model call comes back 403 and the demo has no agent.
PROJECT_NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$PROJECT_NUM-compute@developer.gserviceaccount.com" \
  --role=roles/aiplatform.user --condition=None >/dev/null

gcloud run deploy fleet --source . --region="$REGION" --allow-unauthenticated \
  --min-instances=1 --max-instances=1 --no-cpu-throttling \
  --memory=4Gi --cpu=2 \
  --add-cloudsql-instances="$CONN" \
  --set-env-vars="FLEET_PG_DSN=postgresql://$DB_USER:$DB_PASS@/$DB?host=/cloudsql/$CONN,FLEET_VERTEX_PROJECT=$PROJECT,FLEET_ALLOW_API=1"

gcloud run services describe fleet --region="$REGION" --format='value(status.url)'
