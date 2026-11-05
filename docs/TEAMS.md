# Microsoft Teams — condições de entrada da Navi

A Navi entra como **participante anônima pelo cliente web do Teams** (bot da Recall.ai), com o nome
"Navi | Assistente IA". No Teams corporativo o nome aparece com o sufixo **"(Unverified)"**, padrão da Microsoft
para quem entra sem conta Microsoft; no Teams pessoal (teams.live.com) não há sufixo.

## Links aceitos

- `https://teams.microsoft.com/l/meetup-join/19:meeting_...@thread.v2/0?context=...` (convite padrão)
- `https://teams.microsoft.com/meet/<id>?p=<senha>` e `https://teams.cloud.microsoft/...` (links curtos)
- `https://teams.live.com/meet/<id>?p=<senha>` (Teams pessoal)
- Links de "launcher" (`/dl/launcher/launcher.html?url=...`) e `light-meetings`

Links protegidos por Microsoft Defender SafeLinks ou encurtadores de calendário não são desembrulhados: copie o
link final do convite. A validação definitiva é da Recall (erro 400 descreve o problema).

## O que o organizador precisa garantir

1. **Participantes anônimos podem entrar** — política do tenant ("Anonymous users can join a meeting") e opções
   da reunião ("Quem pode ignorar o lobby" / "Acesso à reunião"). Se o tenant exigir login, o bot falha com
   `fatal` + `meeting_requires_sign_in` ou `microsoft_teams_sign_in_credentials_missing`.
2. **Lobby** — por padrão a Navi cai no lobby (`in_waiting_room`) e o painel avisa para admiti-la. Para entrar
   direto, o organizador define **"Quem pode ignorar o lobby: Todos"** nas opções da reunião. O Teams limita a
   espera no lobby a **30 minutos** (`call_ended_by_platform_waiting_room_timeout`).
3. **Não suportado**: webinars/eventos com inscrição, Town Hall e Live Events, chamadas diretas, breakout rooms,
   GCC High. Alguns tenants bloqueiam bots por completo (`teams_blacklisted_tenant`, sem contorno).
4. **Captcha para anônimos** habilitado no tenant → `microsoft_teams_captcha_error` (só bots autenticados passam).

## Como a Navi se comporta na reunião

- Ela aparece com a câmera ligada mostrando a tela da assistente (estado: Ouvindo / Pensando / Falando e a
  legenda da última resposta). Não é possível ter Output Media sem vídeo.
- Ouve o áudio mixado dos participantes (sem a própria voz) e só fala quando chamada pelo nome.
- A gravação da Recall começa quando o primeiro participante está presente (`start_recording_on=participant_join`);
  a transcrição em tempo real só flui no estado `in_call_recording`.
- Sai quando todos saem (60 s) ou quando o painel pede ("Encerrar e gerar ata"). Depois de sair não reentra;
  crie uma nova reunião no painel para ela voltar.

## Boas práticas para a demo

- Avise os participantes que uma assistente/gravadora entrará e peça ao organizador para liberar o lobby
  ("Todos") ou ficar atento ao pedido de admissão.
- Teste antes com a sua própria reunião (link do seu Teams) para confirmar políticas do tenant.
- Fale o nome **no início ou no fim da frase**: "Navi, …" ou "…, Navi?". Menções no meio da frase
  ("falei com a Navi ontem") são ignoradas de propósito.
- Após "Navi," faça a pergunta na mesma frase; se houver pausa, ela espera até 6 s pelo restante.

## Códigos de falha mais comuns (sub_code)

| sub_code | Significado | Ação |
|---|---|---|
| `meeting_not_accessible` | acesso à reunião bloqueado para anônimos | ajustar "Acesso à reunião"/lobby |
| `meeting_requires_sign_in` | tenant exige login | habilitar anônimos ou usar bot autenticado |
| `timeout_exceeded_waiting_room` | ninguém admitiu a Navi em 20 min | admitir mais rápido ou liberar lobby |
| `bot_kicked_from_waiting_room` / `bot_kicked_from_call` | recusada/removida por um participante | reconvidar |
| `meeting_not_found` / `meeting_link_expired` | link inválido/expirado | usar o link atual do convite |
| `timeout_exceeded_everyone_left` | todos saíram | comportamento esperado |
| `bot_received_leave_call` | saída pedida pelo painel | comportamento esperado |

Fontes: https://docs.recall.ai/docs/microsoft-teams · https://docs.recall.ai/docs/teams-bots-bypass-the-lobby ·
https://docs.recall.ai/docs/meeting-urls · https://docs.recall.ai/docs/sub-codes
