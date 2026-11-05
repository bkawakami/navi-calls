#!/usr/bin/env bash
# Expõe o backend local em HTTPS público (necessário para a Recall carregar a página da assistente
# e entregar webhooks). Prefere cloudflared (sem página intersticial); cai para ngrok se não houver.
#
# Uso: ./scripts/tunnel.sh [porta]
# Depois, copie a URL impressa para BASE_URL no .env e reinicie o servidor (python run.py).
set -euo pipefail
PORT="${1:-8000}"
if command -v cloudflared >/dev/null 2>&1; then
  echo "Abrindo túnel cloudflared para http://localhost:${PORT} ..."
  echo "Copie a URL https://*.trycloudflare.com impressa abaixo para BASE_URL no .env."
  exec cloudflared tunnel --url "http://localhost:${PORT}" --no-autoupdate
elif command -v ngrok >/dev/null 2>&1; then
  echo "Abrindo túnel ngrok para http://localhost:${PORT} ..."
  echo "ATENÇÃO: no plano gratuito do ngrok há uma página intersticial que impede o bot de carregar a página da assistente."
  echo "Use um domínio pago/estático ou prefira o cloudflared (brew install cloudflared)."
  exec ngrok http "${PORT}"
else
  echo "Instale cloudflared (brew install cloudflared) ou ngrok." >&2
  exit 1
fi
