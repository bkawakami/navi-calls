# Implantação no Google Cloud Run

O serviço é um único contêiner (FastAPI + polling de status em background), sem estado local: tudo fica no MongoDB.
Para o Cloud Run use um **MongoDB Atlas** (M0 gratuito serve para a PoC) ou outro MongoDB acessível pela internet.

## 1. Pré-requisitos

- `gcloud` autenticado e projeto selecionado (`gcloud config set project <PROJECT_ID>`).
- MongoDB Atlas: crie o cluster, um usuário e libere o acesso de rede (`0.0.0.0/0` para a PoC). Copie a URI
  `mongodb+srv://...`.
- Chaves: Recall.ai, Workspace Secret da Recall, OpenAI, senha do painel, `SECRET_KEY`.

## 2. Segredos no Secret Manager

```bash
PROJECT_ID=$(gcloud config get-value project)
for name in navi-secret-key navi-mongodb-url navi-recall-api-key navi-recall-webhook-secret navi-recall-realtime-secret navi-openai-api-key navi-dashboard-password; do
  gcloud secrets describe $name --project $PROJECT_ID >/dev/null 2>&1 || gcloud secrets create $name --replication-policy=automatic --project $PROJECT_ID
done
printf '%s' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" | gcloud secrets versions add navi-secret-key --data-file=-
printf '%s' 'mongodb+srv://usuario:senha@cluster.mongodb.net/navi?retryWrites=true&w=majority' | gcloud secrets versions add navi-mongodb-url --data-file=-
printf '%s' 'SUA_CHAVE_RECALL' | gcloud secrets versions add navi-recall-api-key --data-file=-
printf '%s' 'whsec_...' | gcloud secrets versions add navi-recall-webhook-secret --data-file=-
printf '%s' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" | gcloud secrets versions add navi-recall-realtime-secret --data-file=-
printf '%s' 'sk-...' | gcloud secrets versions add navi-openai-api-key --data-file=-
printf '%s' 'senha-do-painel' | gcloud secrets versions add navi-dashboard-password --data-file=-
# A conta de serviço do Cloud Run precisa de roles/secretmanager.secretAccessor nesses segredos.
```

## 3. Build e deploy

```bash
PROJECT_ID=<PROJECT_ID> REGION=southamerica-east1 RECALL_REGION=us-west-2 ./scripts/deploy_cloud_run.sh
```

O script habilita as APIs, cria o repositório no Artifact Registry, faz o build com Cloud Build, publica o serviço
com `--min-instances 1 --max-instances 1` (o polling de status e os webhooks em tempo real não precisam de
escala horizontal na PoC) e imprime a URL. Em seguida:

```bash
gcloud run services update navi --region southamerica-east1 --update-env-vars BASE_URL=https://navi-xxxx.a.run.app
```

`BASE_URL` é o que a Recall usa para carregar a página da assistente e entregar a transcrição em tempo real.

## 4. Webhooks

No dashboard da Recall (Webhooks → Add Endpoint): `https://navi-xxxx.a.run.app/api/webhooks/recall`, assinando
`bot.*`, `transcript.done` e `recording.done`. Mesmo sem o webhook o painel funciona por polling.

## 5. Observações

- O contêiner expõe `PORT` (8080), roda como usuário não-root e tem `HEALTHCHECK` em `/healthz`.
- `DASHBOARD_PASSWORD` protege o painel e as APIs do painel com HTTP Basic; a página da assistente e os webhooks
  usam seus próprios segredos e continuam acessíveis à Recall.
- Logs: `gcloud run services logs read navi --region southamerica-east1 --limit 200`.
- Para atualizar: rode o script de deploy de novo (nova tag de imagem).
- Alternativa sem Cloud Run para a demo: rodar local com `./scripts/tunnel.sh` (cloudflared) como `BASE_URL`.
