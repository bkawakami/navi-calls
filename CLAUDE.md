# CLAUDE.md

## Objetivo do Projeto

Navi é uma assistente de IA que participa de reuniões do Microsoft Teams. Um bot da Recall.ai entra na
reunião como "Navi | Assistente IA"; a página da assistente (Output Media) recebe o áudio da reunião e
conversa com a OpenAI Realtime API via WebRTC (fallback WebSocket). A Navi ouve em silêncio, responde quando
chamada pelo nome, guarda notas ("Navi, lembre-se de ...") e, ao final, gera ata e backlog com um modelo de texto.

## Stack

- **Backend**: FastAPI (async) + Pydantic v2 · **Banco**: MongoDB (Motor) · **Templates**: Jinja2
- **Frontend**: TailwindCSS (CDN) + AlpineJS no painel; página da assistente em HTML/JS puro (sem CDN)
- **Integrações**: Recall.ai (bots, Output Media, transcrição, webhooks) · OpenAI (Realtime, Responses)
- **Deploy**: Docker → Google Cloud Run (`scripts/deploy_cloud_run.sh`)

## Arquitetura

Monolito em 3 camadas, fluxo unidirecional: Routes → Services → Models → MongoDB.

| Camada   | Responsabilidade                                  | NÃO faz                            |
|----------|---------------------------------------------------|-------------------------------------|
| Routes   | Validar input, chamar service, retornar response  | Lógica de negócio, queries ao banco |
| Services | Regras de negócio, orquestrar models e integrações| Receber Request, retornar HTTP      |
| Models   | CRUD no banco, queries específicas                | Lógica de negócio                   |

Mapa rápido:
- `app/services/meeting_service.py` — cria o bot na Recall (payload em `build_bot_payload`), status, saída.
- `app/services/assistant_service.py` — sessão Realtime (prompt, VAD, tools), decisão de chamado, notas, contexto.
- `app/services/transcript_service.py` — ingestão da transcrição da Recall (tempo real e final) e feed ao vivo.
- `app/services/minutes_service.py` — consolidação da transcrição, geração da ata (Responses API) e exportação.
- `app/static/js/assistant.js` + `app/templates/assistant/page.html` — página carregada dentro do bot.
- `app/routes/api/webhooks.py` — webhooks da Recall (status via dashboard; transcrição em tempo real).

## Setup Inicial do Projeto

```bash
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env   # preencher chaves
./scripts/dev_mongo.sh                 # MongoDB local em Docker (porta 27027)
python run.py                          # http://localhost:8000
```

Para a Recall alcançar a página da assistente e os webhooks, `BASE_URL` precisa ser pública
(`./scripts/tunnel.sh` abre um túnel cloudflared; copie a URL para `.env` e reinicie).

## Regras Invioláveis

- Nenhum arquivo com mais de 1.000 linhas (Python, HTML, JS). Perto de 800, planejar divisão.
- Segredos só no backend e via `app/config.py` (Pydantic Settings). Nunca no JS, nos templates ou no git.
- Acesso ao MongoDB apenas pelas classes em `app/models/`; `_id` sempre serializado como `id`.
- Services lançam exceções de domínio; routes convertem em `HTTPException`.
- Respostas da API: sucesso `{"success": true, ...}`; erro `{"detail": "..."}`.
- A página da assistente é autenticada por token HMAC (`routes/shared/auth.py`); nunca expor a chave da OpenAI nela.
- Resposta automática do Realtime continua DESABILITADA (`create_response=false`); a Navi só fala ao ser chamada.
- Templates: partials com prefixo `_`; JS inline até ~100 linhas, senão `app/static/js/`.

## Comandos Úteis

```bash
python run.py                       # dev (reload)
pytest -q                           # testes
ruff check app/ tests/              # lint
python scripts/dev_fake_meeting.py  # reunião simulada p/ testar a página da assistente sem a Recall
docker build -t navi . && docker run -p 8080:8080 --env-file .env navi
find app/ -name "*.py" | xargs wc -l | sort -n
```
