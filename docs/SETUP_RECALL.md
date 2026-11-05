# Recall.ai — cadastro, chave, região, webhooks e validação

Fonte: documentação oficial consultada em 05/11/2026 (https://docs.recall.ai). Links citados ao final.

## 1. Cadastro (pay-as-you-go)

O cadastro self-service existe em três regiões. Escolha **uma** (a conta, a chave e todos os recursos ficam
presos à região; não há migração entre regiões):

| Região | Cadastro | Base da API |
|---|---|---|
| US West (recomendada para o Brasil) | https://us-west-2.recall.ai/auth/signup | `https://us-west-2.recall.ai` |
| EU (Frankfurt) | https://eu-central-1.recall.ai/auth/signup | `https://eu-central-1.recall.ai` |
| APAC (Tóquio) | https://ap-northeast-1.recall.ai/auth/signup | `https://ap-northeast-1.recall.ai` |

`us-east-1.recall.ai` (= `api.recall.ai`) existe, mas não oferece cadastro self-service.
As primeiras 5 horas de gravação são gratuitas. Depois: bot `web_4_core` US$ 0,60/h, transcrição da própria
Recall US$ 0,15/h de gravação. Cobrança proporcional ao segundo, do `joining_call` até `done`. Bots que terminam
em `fatal` não são cobrados.

Defina no `.env`: `RECALL_REGION=us-west-2` (ou a região escolhida).

## 2. Chave de API

Dashboard → **Developers → API Keys & Secrets** (`https://<região>.recall.ai/dashboard/developers/api-keys`) →
criar chave. Ela não expira (desative para rotacionar). Guarde em `RECALL_API_KEY`. A chave nunca sai do backend:
o navegador/página da assistente só fala com o nosso servidor.

Header usado pelo backend: `Authorization: Token <chave>` (o prefixo `Token` é opcional).

## 3. Workspace Secret (assinatura dos webhooks)

Na mesma tela, **Create Workspace Secret**. O valor começa com `whsec_` e vai em `RECALL_WEBHOOK_SECRET`.
Com ele a Recall assina **os webhooks do dashboard e os endpoints em tempo real** com os cabeçalhos
`webhook-id`, `webhook-timestamp`, `webhook-signature` (esquema Svix: HMAC-SHA256 de `id.timestamp.corpo`).
Contas criadas antes de 15/12/2025 recebem `svix-*` assinados com o segredo do endpoint; o backend aceita os dois.

Sem o segredo configurado o backend aceita qualquer POST (modo dev). Para os endpoints em tempo real há ainda
um segundo fator: `RECALL_REALTIME_SECRET`, embutido na URL (`?secret=...`).

## 4. Webhooks de status (dashboard)

Dashboard → **Webhooks** (`https://<região>.recall.ai/dashboard/webhooks/`) → **Add Endpoint**:

- URL: `https://<BASE_URL>/api/webhooks/recall`
- Assine explicitamente os eventos (o que não for assinado não é enviado):
  `bot.joining_call`, `bot.in_waiting_room`, `bot.in_call_not_recording`, `bot.in_call_recording`,
  `bot.call_ended`, `bot.done`, `bot.fatal`, `transcript.done`, `recording.done`.

Payload recebido:

```json
{"event": "bot.in_call_recording",
 "data": {"data": {"code": "in_call_recording", "sub_code": null, "updated_at": "2026-11-05T15:00:00Z"},
          "bot": {"id": "...", "metadata": {"meeting_id": "...", "app": "navi"}}}}
```

O backend aplica o status à reunião (`metadata.meeting_id` / `bot.id`), gera a ata automaticamente em
`bot.call_ended`/`bot.done` e, em `transcript.done`, baixa a transcrição final e regera a ata se ela tiver sido
feita só com a transcrição da OpenAI. Timeout da Recall: 15 s por entrega; retentativas por 24 h.

**Fallback:** o backend também consulta `GET /api/v1/bot/{id}/` a cada `RECALL_POLL_SECONDS` (10 s) para as
reuniões ativas. Assim o painel funciona mesmo sem webhook cadastrado (útil quando a URL do túnel muda).

## 5. Endpoints em tempo real (transcrição)

Não precisam de cadastro no dashboard: são declarados a cada criação de bot em
`recording_config.realtime_endpoints` (veja `build_bot_payload` em `app/services/meeting_service.py`):

```json
{"type": "webhook", "url": "https://<BASE_URL>/api/webhooks/recall/realtime/?secret=<RECALL_REALTIME_SECRET>", "events": ["transcript.data"]}
```

Regras da Recall: barra final antes da query string (senão HTTP 400); responder 2xx rápido (entrega em série);
60 retentativas de 1 s; só emite enquanto o bot está em `in_call_recording`.
Payload: `data.data.words[]` (com `start_timestamp.relative`), `data.data.participant.{id,name,is_host}`,
`data.bot.id`. O backend grava cada utterance em `transcript_segments` (fonte `recall`).

### Provedor de transcrição e português

| `RECALL_TRANSCRIPT_PROVIDER` | Português | Latência | Requisito |
|---|---|---|---|
| `recallai_streaming` (padrão) | `language_code: pt`, modo `prioritize_accuracy` | **3 a 10 min de atraso** (o modo de baixa latência é só inglês) | nenhum |
| `deepgram_streaming` | `nova-3`, `pt-BR` | 1 a 3 s | chave Deepgram em Dashboard → Transcription → Deepgram |
| `assembly_ai_v3_streaming` | `universal-streaming-multilingual` | 1 a 3 s | chave AssemblyAI no dashboard |
| `speechmatics_streaming`, `elevenlabs_streaming`, `soniox_streaming` | `pt` | 1 a 3 s | chave do provedor no dashboard |
| `none` | — | — | usa só a transcrição da OpenAI (sem nome dos falantes) |

Com o padrão, o painel mostra em tempo real a transcrição feita pela OpenAI (sem falantes) e a transcrição da
Recall (com falantes) chega alguns minutos depois; a ata é regerada automaticamente quando ela chega.
Para transcrição ao vivo com nomes dos falantes na demo, cadastre uma chave Deepgram (há crédito gratuito) e
use `RECALL_TRANSCRIPT_PROVIDER=deepgram_streaming` e `RECALL_TRANSCRIPT_LANGUAGE=pt-BR`.

## 6. Criação do bot (o que o backend envia)

`POST /api/v1/bot/` com `meeting_url`, `bot_name` ("Navi | Assistente IA"), `variant.microsoft_teams=web_4_core`
(recomendado para Output Media), `output_media.camera = {kind: webpage, config: {url: <página da assistente>}}`,
`recording_config` (transcrição + endpoints em tempo real; `include_bot_in_recording.audio=false` para a Navi não
ser gravada nem transcrita), `automatic_leave` (lobby 20 min, ninguém entrou 20 min, todos saíram 60 s) e
`metadata.meeting_id`. Retorno 201 com `id` e `status_changes`. Erros tratados: 507 (sem bots ad-hoc no pool:
retentativa automática), 429, 400 `teams_blacklisted_tenant`.

Limites: 120 criações/min, 30 bots ad-hoc simultâneos (bots agendados com `join_at` > 10 min não têm limite).

## 7. Validação (checklist)

1. `GET https://<região>.recall.ai/api/v1/bot/` com a chave → 200 (lista vazia) confirma chave + região.
2. Crie uma reunião no painel com um link do Teams de teste; em **Bot Explorer** do dashboard
   (`/dashboard/explorer/bot/<bot_id>`) acompanhe `joining_call → in_waiting_room → in_call_recording`.
3. Admita a Navi no lobby do Teams; a tela da câmera dela deve mostrar "Ouvindo a reunião".
   Em **Debug Data → Open Remote Devtools** você vê o console da página da assistente.
4. Fale "Navi, lembre-se de validar o contrato" → nota aparece no painel e a Navi confirma por voz.
5. Webhooks: em **Webhooks → endpoint → Messages** verifique entregas com 200; o botão **Svix Play** permite
   inspecionar payloads; **Recover failed messages** reenvia falhas.
6. Encerre pelo painel ("Encerrar e gerar ata") → ata gerada; `transcript.done` chega depois e regera a ata
   com os nomes dos falantes.

## Links

- Regiões: https://docs.recall.ai/docs/regions · Autenticação: https://docs.recall.ai/reference/authentication
- Criar bot: https://docs.recall.ai/reference/bot_create · Output Media: https://docs.recall.ai/docs/stream-media
- Transcrição em tempo real: https://docs.recall.ai/docs/bot-real-time-transcription
- Payloads em tempo real: https://docs.recall.ai/docs/real-time-event-payloads
- Webhooks de status: https://docs.recall.ai/docs/status-change-webhooks-setup-verification
- Verificação de assinatura: https://docs.recall.ai/docs/authenticating-requests-from-recallai
- Teams: https://docs.recall.ai/docs/microsoft-teams · Lobby: https://docs.recall.ai/docs/teams-bots-bypass-the-lobby
- Sub-códigos de status: https://docs.recall.ai/docs/sub-codes · Preços: https://www.recall.ai/pricing
