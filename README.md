# Navi — assistente de IA para reuniões do Microsoft Teams (PoC)

A Navi entra em uma reunião do Teams como a participante **"Navi | Assistente IA"**, acompanha toda a conversa em
silêncio, responde em português quando chamada pelo nome ("Navi, o que você acha dessa proposta?"), guarda
lembretes ("Navi, lembre-se de validar o contrato") e, ao final, gera **ata e backlog** (resumo, decisões,
pendências e tarefas com responsável, prazo e trecho de origem), disponíveis no painel e para download
(Markdown, Word e JSON).

## Como funciona

```
Painel (FastAPI + Jinja/Alpine) ──POST /api/v1/bot──▶ Recall.ai ──▶ entra no Teams como "Navi | Assistente IA"
        ▲                                                │
        │ webhooks (status, transcrição em tempo real)    │ Output Media: o bot renderiza a página da assistente
        │                                                ▼
   MongoDB ◀── backend ◀──(token efêmero, decisões, notas)── página da assistente (app/static/js/assistant.js)
                                                         │  áudio da reunião (getUserMedia) ⇄ OpenAI Realtime (WebRTC;
                                                         │  fallback WebSocket), create_response=false
                                                         ▼
                                            voz da Navi tocada na página → enviada à reunião
```

1. O usuário cola o link do Teams e clica em **Adicionar Navi**. O backend cria o bot na Recall.ai com
   `output_media.camera = {kind: webpage, url: <página da assistente>}` e transcrição em tempo real por webhook.
2. Se a reunião tiver lobby, o painel avisa para admitir a Navi.
3. A página da assistente (rodando dentro do bot) pede ao backend um **client secret efêmero** da OpenAI
   (a chave real nunca sai do servidor), conecta por WebRTC e envia o áudio da reunião. A resposta automática
   fica **desabilitada** (`turn_detection.create_response=false`); cada fala é transcrita e enviada ao backend,
   que decide se foi um chamado à Navi (nome no início/fim da frase; menções em terceira pessoa são ignoradas).
4. Em um chamado, a página pede uma resposta (`response.create`) com instruções específicas: lembretes são
   persistidos como notas antes mesmo da confirmação por voz; perguntas são respondidas em 1 a 3 frases.
   Enquanto fala, o microfone é silenciado (ela não ouve a própria voz) e a resposta é cortada se passar de 25 s.
5. Transcrição (Recall com nome do falante + OpenAI), notas, respostas e eventos são gravados continuamente no
   MongoDB. Em reconexões (queda ou limite de 60 min da sessão Realtime), o backend reinjeta o contexto.
6. Ao encerrar (botão **Encerrar e gerar ata** ou fim da reunião), a transcrição consolidada vai para um modelo
   de texto com saída estruturada; a ata aparece no painel e pode ser baixada. Informações ausentes ficam como
   **"a definir"**.

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI (async) + Pydantic v2 |
| Banco | MongoDB (Motor) |
| Painel | Jinja2 + TailwindCSS (CDN) + AlpineJS |
| Página da assistente | HTML/JS puro (WebRTC / WebSocket + AudioWorklet) |
| Integrações | Recall.ai (bots, Output Media, transcrição, webhooks) · OpenAI (Realtime, Responses) |
| Deploy | Docker → Google Cloud Run |

## Pré-requisitos

- Python 3.12+, Docker (MongoDB local), `cloudflared` (túnel público em dev: `brew install cloudflared`)
- Conta Recall.ai (ver `docs/SETUP_RECALL.md`) e chave OpenAI (ver `docs/SETUP_OPENAI.md`)
- Reunião do Teams que permita participantes anônimos (ver `docs/TEAMS.md`)

## Setup local

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # preencher RECALL_API_KEY, OPENAI_API_KEY, SECRET_KEY, RECALL_REALTIME_SECRET
./scripts/dev_mongo.sh          # MongoDB em Docker (porta 27027)
python run.py                   # http://localhost:8000
```

Para a Recall alcançar a página da assistente e os webhooks, o backend precisa de URL pública:

```bash
./scripts/tunnel.sh             # imprime https://xxxx.trycloudflare.com
# coloque essa URL em BASE_URL no .env, reinicie `python run.py`
# e cadastre https://xxxx.trycloudflare.com/api/webhooks/recall no dashboard da Recall (opcional: há polling de status)
```

Roteiro completo da demonstração: `docs/RUNBOOK_DEMO.md`.

## Testes

```bash
pytest -q                                   # unitários + integração (usa o MongoDB local, banco navi_test)
ruff check app/ tests/
python scripts/dev_fake_meeting.py          # reunião simulada: testa a página da assistente sem a Recall
node scripts/e2e_assistant.mjs <url> <wav> 70   # Chrome headless com "microfone" alimentado por um WAV (Playwright)
```

O teste ponta a ponta com áudio sintético validou: conexão WebRTC e WebSocket, transcrição em português,
detecção do chamado, nota salva e confirmada por voz, pergunta respondida com contexto da reunião, ata gerada
com tarefas/pendências e exportações `.md/.docx/.json`.

## Estrutura

```
app/
├── main.py                # lifespan (MongoDB, índices, polling de status), routers
├── config.py              # Pydantic Settings (.env)
├── routes/
│   ├── views/             # painel (/, /meetings/{id}) e página da assistente (/assistant/{id})
│   └── api/               # /api/meetings, /api/assistant, /api/webhooks
├── services/              # meeting, assistant, transcript, minutes, webhook + core/{recall_client, openai_client}
├── models/                # meetings, transcript_segments, notes, events, minutes
├── templates/             # Jinja2 (dashboard/, assistant/, components/)
└── static/js/             # assistant.js (página no bot), meeting.js (painel)
docs/                      # SETUP_RECALL, SETUP_OPENAI, TEAMS, DEPLOY_CLOUD_RUN, RUNBOOK_DEMO
scripts/                   # dev_mongo.sh, tunnel.sh, deploy_cloud_run.sh, dev_fake_meeting.py, e2e_assistant.mjs
```

## Endpoints principais

| Método/URL | Uso |
|---|---|
| `POST /api/meetings` `{meeting_url, title}` | cria a reunião e o bot na Recall |
| `GET /api/meetings/{id}/live?after_seq=` | feed ao vivo (transcrição, notas, eventos, status) |
| `POST /api/meetings/{id}/leave` | retira a Navi e gera a ata |
| `POST /api/meetings/{id}/minutes?force=1` · `GET .../minutes` | gera / lê a ata |
| `GET /api/meetings/{id}/export/{minutes.md|minutes.docx|minutes.json|transcript.txt|transcript.json}` | downloads |
| `POST /api/assistant/{id}/session` (token da página) | client secret efêmero + configuração da sessão |
| `POST /api/assistant/{id}/transcript` · `/notes` · `/response` · `/events` | usados pela página da assistente |
| `POST /api/webhooks/recall` · `POST /api/webhooks/recall/realtime/` | webhooks da Recall |

## Segurança

- Chaves da Recall e da OpenAI só no backend (`.env` / Secret Manager). A página recebe apenas tokens efêmeros.
- Página da assistente protegida por token HMAC por reunião (`SECRET_KEY`); webhooks verificados por assinatura
  (`RECALL_WEBHOOK_SECRET`) e segredo na URL (`RECALL_REALTIME_SECRET`).
- Painel opcionalmente protegido por HTTP Basic (`DASHBOARD_USER` / `DASHBOARD_PASSWORD`) — recomendado no Cloud Run.

## Deploy

`docs/DEPLOY_CLOUD_RUN.md` e `scripts/deploy_cloud_run.sh` (Dockerfile pronto; MongoDB Atlas como banco).

## Limitações conhecidas da PoC

- Convites por e-mail/calendário ficaram fora (apenas link colado no painel).
- Transcrição com nome dos falantes depende do provedor na Recall: a transcrição da própria Recall em português
  chega com 3 a 10 min de atraso (a ata é regerada automaticamente quando ela chega); para tempo real use
  Deepgram com chave própria (`RECALL_TRANSCRIPT_PROVIDER=deepgram_streaming`).
- A detecção do nome depende do ASR; "Navi" no meio da frase é ignorado de propósito.
- WebRTC a partir do navegador do bot não é documentado pela Recall; por isso há fallback automático para WebSocket
  e a opção `NAVI_TRANSPORT=websocket`.
