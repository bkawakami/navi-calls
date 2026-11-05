#!/usr/bin/env bash
# Sobe (ou religa) o MongoDB local da Navi em Docker, na porta 27027.
set -euo pipefail
NAME=navi-mongo
if docker ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  docker start "$NAME" >/dev/null
else
  docker run -d --name "$NAME" -p 27027:27017 -v navi-mongo-data:/data/db mongo:7 >/dev/null
fi
echo "MongoDB em mongodb://localhost:27027 (container ${NAME})"
