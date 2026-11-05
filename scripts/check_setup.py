"""Verifica credenciais e pré-requisitos antes da demo.

Uso: venv/bin/python scripts/check_setup.py
Checa: MongoDB, chave/região da Recall.ai, chave e modelos da OpenAI, BASE_URL pública e segredos.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.config import settings  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def line(status: str, text: str) -> None:
    print(f"{status} {text}")


async def check_mongo() -> None:
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=3000)
        await client[settings.MONGODB_DB_NAME].command("ping")
        line(OK, f"MongoDB acessível ({settings.MONGODB_URL}, banco {settings.MONGODB_DB_NAME})")
    except Exception as exc:  # noqa: BLE001
        line(FAIL, f"MongoDB indisponível: {exc} — rode ./scripts/dev_mongo.sh")


async def check_recall() -> None:
    if not settings.RECALL_API_KEY:
        line(FAIL, "RECALL_API_KEY vazia — crie em https://<região>.recall.ai/dashboard/developers/api-keys")
        return
    url = f"{settings.recall_base_url}/api/v1/bot/"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Token {settings.RECALL_API_KEY}"}, params={"page_size": 1})
        if resp.status_code == 200:
            line(OK, f"Recall.ai OK na região {settings.RECALL_REGION} ({url})")
        elif resp.status_code in (401, 403):
            line(FAIL, f"Recall.ai recusou a chave ({resp.status_code}). A chave é por região: confira RECALL_REGION={settings.RECALL_REGION}")
        else:
            line(WARN, f"Recall.ai respondeu {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:  # noqa: BLE001
        line(FAIL, f"Falha ao falar com a Recall.ai: {exc}")
    line(OK if settings.RECALL_WEBHOOK_SECRET else WARN, "RECALL_WEBHOOK_SECRET " + ("configurado (webhooks verificados)" if settings.RECALL_WEBHOOK_SECRET else "vazio — webhooks aceitos sem verificação (ok só em dev)"))
    line(OK if settings.RECALL_REALTIME_SECRET else WARN, "RECALL_REALTIME_SECRET " + ("configurado" if settings.RECALL_REALTIME_SECRET else "vazio — endpoint em tempo real sem segredo"))
    provider = settings.RECALL_TRANSCRIPT_PROVIDER
    if provider == "recallai_streaming" and settings.RECALL_TRANSCRIPT_LANGUAGE != "en":
        line(WARN, "Transcrição da Recall em português chega com 3-10 min de atraso (modo de precisão). Para tempo real use deepgram_streaming com chave no dashboard da Recall.")
    elif provider not in ("none", "recallai_streaming"):
        line(WARN, f"Provedor {provider}: confirme que a chave do provedor está cadastrada no dashboard da Recall (Transcription).")


async def check_openai() -> None:
    if not settings.OPENAI_API_KEY:
        line(FAIL, "OPENAI_API_KEY vazia")
        return
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        ids = {m.id async for m in client.models.list()}
        for label, model in (("Realtime", settings.OPENAI_REALTIME_MODEL), ("Transcrição", settings.OPENAI_TRANSCRIBE_MODEL), ("Ata", settings.OPENAI_TEXT_MODEL)):
            line(OK if model in ids else FAIL, f"OpenAI {label}: {model}" + ("" if model in ids else " — não disponível nesta conta; ajuste no .env"))
        secret = await client.realtime.client_secrets.create(expires_after={"anchor": "created_at", "seconds": 10}, session={"type": "realtime", "model": settings.OPENAI_REALTIME_MODEL})
        line(OK, f"Client secret efêmero emitido ({secret.value[:6]}…)")
    except Exception as exc:  # noqa: BLE001
        line(FAIL, f"OpenAI: {exc}")


async def check_base_url() -> None:
    base = settings.BASE_URL.rstrip("/")
    if "localhost" in base or "127.0.0.1" in base:
        line(FAIL, f"BASE_URL={base} não é pública — a Recall não consegue carregar a página da assistente. Use ./scripts/tunnel.sh ou Cloud Run.")
        return
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(f"{base}/healthz")
        line(OK if resp.status_code == 200 else FAIL, f"BASE_URL pública responde {resp.status_code} em {base}/healthz")
    except Exception as exc:  # noqa: BLE001
        line(FAIL, f"BASE_URL {base} inacessível: {exc}")
    line(OK if settings.SECRET_KEY != "troque-esta-chave" else WARN, "SECRET_KEY " + ("definida" if settings.SECRET_KEY != "troque-esta-chave" else "ainda é o valor padrão"))
    line(OK if settings.DASHBOARD_PASSWORD else WARN, "Painel " + ("protegido por senha" if settings.DASHBOARD_PASSWORD else "sem senha (DASHBOARD_PASSWORD vazio)"))


async def main() -> None:
    print(f"Navi — verificação de setup (APP_ENV={settings.APP_ENV})\n")
    await check_mongo()
    await check_recall()
    await check_openai()
    await check_base_url()


if __name__ == "__main__":
    asyncio.run(main())
