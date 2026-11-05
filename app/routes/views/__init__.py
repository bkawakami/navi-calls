"""Páginas HTML: painel e página da assistente (renderizada dentro do bot via Output Media)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.routes.shared.auth import require_dashboard, verify_page_token
from app.routes.shared.templates import get_templates
from app.services.meeting_service import MeetingNotFoundError, MeetingService, get_meeting_service
from app.services.minutes_service import get_minutes_service

router = APIRouter()
templates = get_templates()


def _config_status() -> dict:
    return {
        "recall": bool(settings.RECALL_API_KEY),
        "openai": bool(settings.OPENAI_API_KEY),
        "public_url": not settings.BASE_URL.startswith("http://localhost"),
        "webhook_secret": bool(settings.RECALL_WEBHOOK_SECRET),
        "realtime_secret": bool(settings.RECALL_REALTIME_SECRET),
        "base_url": settings.BASE_URL,
        "region": settings.RECALL_REGION,
        "realtime_model": settings.OPENAI_REALTIME_MODEL,
        "text_model": settings.OPENAI_TEXT_MODEL,
        "bot_name": settings.RECALL_BOT_NAME,
    }


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_dashboard)])
async def home(request: Request):
    service = get_meeting_service(request.app.mongodb)
    meetings = await service.list_recent(30)
    for m in meetings:
        m["status_label"] = MeetingService.status_label(m.get("status"))
    return templates.TemplateResponse(request, "dashboard/index.html", {"meetings": meetings, "config": _config_status()})


@router.get("/meetings/{meeting_id}", response_class=HTMLResponse, dependencies=[Depends(require_dashboard)])
async def meeting_page(request: Request, meeting_id: str):
    db = request.app.mongodb
    try:
        meeting = await get_meeting_service(db).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    minutes = await get_minutes_service(db).get_latest(meeting_id)
    meeting["status_label"] = MeetingService.status_label(meeting.get("status"))
    return templates.TemplateResponse(request, "dashboard/meeting.html", {"meeting": meeting, "minutes": minutes, "config": _config_status()})


@router.get("/assistant/{meeting_id}", response_class=HTMLResponse)
async def assistant_page(request: Request, meeting_id: str, token: str = Query("")):
    """Página carregada pelo bot da Recall (Output Media). Sem layout do painel."""
    if not verify_page_token(meeting_id, token):
        raise HTTPException(403, "Token inválido")
    try:
        meeting = await get_meeting_service(request.app.mongodb).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    transport = request.query_params.get("transport") or settings.NAVI_TRANSPORT
    return templates.TemplateResponse(request, "assistant/page.html", {"meeting": meeting, "token": token, "bot_name": settings.RECALL_BOT_NAME, "transport": transport})


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import Response

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><radialGradient id="g" cx="30%" cy="30%">'
           '<stop offset="0" stop-color="#a5f3fc"/><stop offset=".55" stop-color="#6366f1"/><stop offset="1" stop-color="#1e1b4b"/>'
           '</radialGradient></defs><circle cx="32" cy="32" r="30" fill="url(#g)"/></svg>')
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/healthz")
async def healthz():
    return {"ok": True, "app": settings.APP_NAME}
