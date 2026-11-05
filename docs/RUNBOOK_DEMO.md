# Roteiro da demonstração (Teams real)

Tempo de preparação: ~30 min na primeira vez. Faça um ensaio completo antes da demo.

## A. Véspera / manhã — preparação

1. **Recall.ai** (`docs/SETUP_RECALL.md`): cadastro em https://us-west-2.recall.ai/auth/signup, criar API key e
   Workspace Secret, preencher `RECALL_API_KEY`, `RECALL_REGION=us-west-2`, `RECALL_WEBHOOK_SECRET`.
   Opcional para transcrição ao vivo com nomes: chave Deepgram no dashboard da Recall e
   `RECALL_TRANSCRIPT_PROVIDER=deepgram_streaming`, `RECALL_TRANSCRIPT_LANGUAGE=pt-BR`.
2. **OpenAI** (`docs/SETUP_OPENAI.md`): `OPENAI_API_KEY` com acesso a `gpt-realtime-2.1`, `gpt-transcribe` e
   `gpt-5.6-sol` (o painel mostra os modelos configurados). Defina limite de gasto.
3. **Teams** (`docs/TEAMS.md`): crie a reunião da demo, nas opções defina "Quem pode ignorar o lobby: Todos" (ou
   combine quem admite a Navi) e confirme que o tenant permite participantes anônimos.
4. Rode local:
   ```bash
   ./scripts/dev_mongo.sh && ./scripts/tunnel.sh      # terminal 1 (anote a URL https://....trycloudflare.com)
   # edite .env: BASE_URL=https://....trycloudflare.com
   python run.py                                      # terminal 2
   ```
   Cadastre `https://....trycloudflare.com/api/webhooks/recall` no dashboard da Recall (eventos bot.*, transcript.done).
   Se preferir Cloud Run, siga `docs/DEPLOY_CLOUD_RUN.md` e use a URL do serviço.
5. `python scripts/check_setup.py` — tudo deve aparecer com ✅ (a chave da Recall é por região).
6. Ensaio: abra o painel, cole o link da reunião, **Adicionar Navi**, admita a Navi no Teams, fale com ela,
   encerre e confira a ata. Em caso de problema, abra o Bot Explorer da Recall → Debug Data → Remote Devtools
   para ver o console da página da assistente.

## B. Durante a demo (15 min)

| Passo | O que fazer | O que mostrar |
|---|---|---|
| 1 | Painel → colar link → **Adicionar Navi** | status "Entrando na reunião" → "No lobby" |
| 2 | No Teams, admitir "Navi \| Assistente IA (Unverified)" | tela da câmera da Navi: "Ouvindo a reunião" |
| 3 | Conversar normalmente 1–2 min | transcrição ao vivo no painel; Navi em silêncio |
| 4 | "**Navi, lembre-se de validar o contrato com o fornecedor.**" | Navi: "Anotado: …"; nota aparece no painel |
| 5 | "**Navi, o que você acha dessa proposta?**" | resposta breve, em português, com contexto do que foi dito |
| 6 | "**Navi, quais tarefas ficaram definidas até agora?**" | resumo oral das tarefas |
| 7 | Painel → **Encerrar e gerar ata** | ata: resumo, decisões, pendências, backlog (responsável/prazo/origem) |
| 8 | **Baixar .docx / .md / .json** | arquivos prontos; "a definir" onde faltou informação |

Dicas de fala: nome no início ou no fim da frase; pergunta completa sem pausa longa; esperar a Navi terminar
antes de falar de novo (ela não ouve enquanto fala).

## C. Plano B

- **Navi não entra (fatal)**: veja o `sub_code` no painel (dica em vermelho) e `docs/TEAMS.md`; ajuste o lobby /
  acesso anônimo e clique em Adicionar Navi de novo.
- **Entrou mas não fala**: no Bot Explorer → Debug Data → Remote Devtools veja o console (`[navi]`). Se o WebRTC não
  conectou, a página cai sozinha para WebSocket; para forçar, defina `NAVI_TRANSPORT=websocket` e crie nova reunião.
- **Não responde ao nome**: confira no painel se a fala foi transcrita com "Navi"; repita com o nome no início da frase.
- **Sem transcrição da Recall**: a ata usa a transcrição da OpenAI (sem falantes); a da Recall chega depois e a ata é regerada.
- **Túnel caiu**: reinicie `./scripts/tunnel.sh`, atualize `BASE_URL` e crie nova reunião (o bot antigo carregou a URL antiga).
- **Sem Recall**: `python scripts/dev_fake_meeting.py` cria uma reunião simulada; abra a URL da assistente no Chrome
  (microfone do notebook) para demonstrar o diálogo e a ata sem o Teams.
