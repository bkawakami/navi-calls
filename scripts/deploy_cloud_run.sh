#!/usr/bin/env bash
# Deploy simples no Cloud Run. Pré-requisitos: gcloud autenticado, projeto selecionado,
# segredos criados no Secret Manager (ver docs/DEPLOY_CLOUD_RUN.md).
#
# Uso: PROJECT_ID=meu-projeto REGION=southamerica-east1 ./scripts/deploy_cloud_run.sh
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-southamerica-east1}"
SERVICE="${SERVICE:-navi}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/navi/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

echo "Projeto: ${PROJECT_ID} | Região: ${REGION} | Serviço: ${SERVICE}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project "${PROJECT_ID}" >/dev/null
gcloud artifacts repositories describe navi --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create navi --repository-format=docker --location "${REGION}" --project "${PROJECT_ID}"

gcloud builds submit --tag "${IMAGE}" --project "${PROJECT_ID}"

gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --cpu 1 --memory 512Mi \
  --timeout 300 \
  --set-env-vars "APP_ENV=production,DEBUG=false,RECALL_REGION=${RECALL_REGION:-us-east-1},RECALL_BOT_NAME=Navi | Assistente IA" \
  --set-secrets "SECRET_KEY=navi-secret-key:latest,MONGODB_URL=navi-mongodb-url:latest,RECALL_API_KEY=navi-recall-api-key:latest,RECALL_WEBHOOK_SECRET=navi-recall-webhook-secret:latest,RECALL_REALTIME_SECRET=navi-recall-realtime-secret:latest,OPENAI_API_KEY=navi-openai-api-key:latest,DASHBOARD_PASSWORD=navi-dashboard-password:latest"

URL=$(gcloud run services describe "${SERVICE}" --region "${REGION}" --project "${PROJECT_ID}" --format 'value(status.url)')
echo "Serviço publicado em: ${URL}"
echo "Agora defina BASE_URL=${URL} no serviço:"
echo "  gcloud run services update ${SERVICE} --region ${REGION} --project ${PROJECT_ID} --update-env-vars BASE_URL=${URL}"
echo "E cadastre o webhook ${URL}/api/webhooks/recall no dashboard da Recall."
