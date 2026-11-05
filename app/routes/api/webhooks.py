"""Webhooks da Recall.ai: status do bot / artefatos (dashboard) e transcrição em tempo real."""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.meeting_service import get_meeting_service
from app.services.transcript_service import get_transcript_service
from app.services.webhook_service import WebhookSignatureError, has_signature_headers, verify_request

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_or_401(request: Request, body: bytes) -> None:
    try:
        verify_request(settings.RECALL_WEBHOOK_SECRET, body, request.headers)
    except WebhookSignatureError as exc:
        logger.warning("Webhook Recall rejeitado: %s", exc)
        raise HTTPException(401, f"Assinatura inválida: {exc}")


@router.post("/recall")
@router.post("/recall/")
async def recall_status(request: Request):
    """Webhooks cadastrados no dashboard da Recall (bot.*, transcript.*, recording.*)."""
    body = await request.body()
    _verify_or_401(request, body)
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON inválido")

    event = payload.get("event") or ""
    data = payload.get("data") or {}
    bot = data.get("bot") or {}
    inner = data.get("data") or {}
    logger.info("Webhook Recall: %s bot=%s sub_code=%s", event, bot.get("id"), inner.get("sub_code"))

    db = request.app.mongodb
    if event.startswith("bot.") and bot.get("id"):
        code = inner.get("code") or event.split(".", 1)[1]
        meeting = await get_meeting_service(db).apply_webhook_status(bot["id"], code, inner.get("sub_code"), payload)
        if meeting and code in ("call_ended", "done"):
            from app.routes.api.meetings import _generate_safely

            asyncio.create_task(_generate_safely(db, meeting["id"]))
    elif event == "transcript.done" and bot.get("id"):
        transcript_id = (data.get("transcript") or {}).get("id")
        asyncio.create_task(_ingest_final_and_upgrade(db, bot["id"], transcript_id))
    return {"ok": True, "event": event}


async def _ingest_final_and_upgrade(db, bot_id: str, transcript_id):
    from app.services.minutes_service import get_minutes_service

    try:
        result = await get_transcript_service(db).ingest_final_transcript(bot_id, transcript_id)
        if result.get("meeting_id"):
            await get_minutes_service(db).maybe_upgrade_with_recall(result["meeting_id"])
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao processar transcript.done do bot %s", bot_id)


@router.post("/recall/realtime")
@router.post("/recall/realtime/")
async def recall_realtime(request: Request, secret: str = Query(None)):
    """Endpoint em tempo real (recording_config.realtime_endpoints). Responde rápido; a Recall entrega em série."""
    body = await request.body()
    if settings.RECALL_WEBHOOK_SECRET and has_signature_headers(request.headers):
        _verify_or_401(request, body)
    elif settings.RECALL_REALTIME_SECRET:
        if not secret or secret != settings.RECALL_REALTIME_SECRET:
            raise HTTPException(403, "Segredo inválido")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "JSON inválido")
    result = await get_transcript_service(request.app.mongodb).ingest_realtime(payload)
    return {"ok": True, **result}
