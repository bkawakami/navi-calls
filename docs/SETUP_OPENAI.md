# OpenAI — credenciais, modelos e custos

Fonte: documentação oficial consultada em 05/11/2026 (https://developers.openai.com/api/docs).

## Credenciais

1. Crie uma chave em https://platform.openai.com/api-keys (projeto dedicado à Navi facilita o controle de gasto).
2. Coloque em `OPENAI_API_KEY` no `.env` (ou no Secret Manager, no Cloud Run). **A chave nunca vai ao navegador.**
3. A página da assistente recebe apenas um **client secret efêmero** (`ek_...`), emitido pelo backend em
   `POST /v1/realtime/client_secrets` com validade de `OPENAI_EPHEMERAL_TTL_SECONDS` (padrão 600 s; o docs permite
   10 s a 7200 s). Toda a configuração da sessão (instruções, VAD, transcrição, voz, ferramentas) vai embutida
   nesse segredo, então o navegador não envia `session.update`.
4. Defina um limite mensal de gasto no projeto (Settings → Limits) antes da demo.

## Conexão da página da assistente

- **WebRTC (preferencial)**: a página faz `POST https://api.openai.com/v1/realtime/calls` com o SDP e
  `Authorization: Bearer ek_...`; o áudio da reunião vai na track de microfone e a voz da Navi volta como track remota.
- **WebSocket (fallback automático)**: se o WebRTC não conectar em 12 s (ex.: UDP bloqueado no contêiner do bot),
  a página abre `wss://api.openai.com/v1/realtime?model=...` com o subprotocolo `openai-insecure-api-key.<ek>`,
  envia PCM16 24 kHz (`input_audio_buffer.append`) e toca `response.output_audio.delta`.
- Sessões duram no máximo **60 minutos**; a página reconecta 2 min antes do limite (e em qualquer queda) e o backend
  reinjeta nas instruções um resumo do que já foi dito e das notas (contexto preservado).

## Modelos usados (configuráveis no `.env`)

| Variável | Padrão | Alternativas | Observações |
|---|---|---|---|
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1` | `gpt-realtime-2.1-mini` (mais barato), `gpt-realtime-1.5` (sem raciocínio, contexto 32k) | `gpt-realtime` e `-mini` antigos estão depreciados (desligam em 20/01/2027) |
| `OPENAI_REALTIME_REASONING` | `low` | `minimal`, `medium` | só modelos 2.x |
| `OPENAI_REALTIME_VOICE` | `marin` | `cedar`, `alloy`, `sage`, ... | a voz não muda depois da primeira fala |
| `OPENAI_TRANSCRIBE_MODEL` | `gpt-transcribe` | `gpt-4o-mini-transcribe` (depreciado em 26/02/2027) | `gpt-transcribe` usa `languages: ["pt"]` e `keywords: ["Navi"]` |
| `OPENAI_TURN_DETECTION` | `server_vad` | `semantic_vad` | `create_response=false`: a Navi nunca responde sozinha |
| `OPENAI_TEXT_MODEL` | `gpt-5.6-sol` | `gpt-5.5`, `gpt-5.4-mini`, família GPT-6 quando disponível na conta | ata via Responses API com saída estruturada (Pydantic) |
| `OPENAI_TEXT_MODEL_FALLBACKS` | `gpt-5.5,gpt-5.4-mini` | | usados se o principal falhar |

Verifique os modelos disponíveis na sua conta com `GET /v1/models` (o painel usa a chave do `.env`).

## Custos de referência (lista pública em 05/11/2026)

- `gpt-realtime-2.1`: áudio de entrada US$ 32/1M tokens (≈ 600 tokens/min → US$ 0,019/min), saída US$ 64/1M
  (≈ 1.200 tokens/min); entrada em cache US$ 0,40/1M. Cada resposta reenvia o contexto da sessão (quase todo em cache).
- `gpt-realtime-2.1-mini`: ≈ 1/3 do custo acima.
- `gpt-transcribe`: US$ 0,0045/min de áudio transcrito (roda em paralelo ao modelo, para o painel e a detecção do nome).
- Ata (`gpt-5.6-sol`): centavos por reunião (transcrição de 1 h ≈ 10k tokens de entrada).

Estimativa de uma reunião de 1 h com ~10 chamados à Navi: US$ 1,5 a 3 em Realtime + US$ 0,27 de transcrição + ata.
Para reduzir custo use `gpt-realtime-2.1-mini`; a `truncation` por `retention_ratio` já limita o contexto reenviado.

## Referências

- Realtime (visão geral e migração GA): https://developers.openai.com/api/docs/guides/realtime
- WebRTC: https://developers.openai.com/api/docs/guides/voice-webrtc?api=realtime
- WebSocket: https://developers.openai.com/api/docs/guides/voice-websockets?api=realtime
- Client secrets: https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create
- Eventos cliente/servidor: https://developers.openai.com/api/reference/resources/realtime/client-events ·
  https://developers.openai.com/api/reference/resources/realtime/server-events
- VAD sem resposta automática: https://developers.openai.com/api/docs/guides/realtime-conversations
- Saída estruturada: https://developers.openai.com/api/docs/guides/structured-outputs
- Preços e depreciações: https://developers.openai.com/api/docs/pricing · https://developers.openai.com/api/docs/deprecations
