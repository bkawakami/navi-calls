"""API do painel: reuniões, feed ao vivo, encerramento, ata e exportações."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.routes.shared.auth import require_dashboard
from app.services.assistant_service import get_assistant_service
from app.services.core.openai_client import OpenAIConfigError
from app.services.meeting_service import (
    MeetingNotFoundError,
    MeetingServiceError,
    MeetingValidationError,
    get_meeting_service,
)
from app.services.minutes_service import MinutesNotFoundError, get_minutes_service
from app.services.transcript_service import get_transcript_service

router = APIRouter(dependencies=[Depends(require_dashboard)])


class MeetingCreate(BaseModel):
    meeting_url: str = Field(..., min_length=10, max_length=2000)
    title: Optional[str] = Field(None, max_length=200)


class NoteCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _public(meeting: dict) -> dict:
    service_label = get_meeting_service.__module__  # noqa: F841 (mantém import estável)
    from app.services.meeting_service import MeetingService

    return {
        "id": meeting["id"],
        "title": meeting.get("title"),
        "meeting_url": meeting.get("meeting_url"),
        "bot_id": meeting.get("bot_id"),
        "bot_name": meeting.get("bot_name"),
        "status": meeting.get("status"),
        "status_label": MeetingService.status_label(meeting.get("status")),
        "status_sub_code": meeting.get("status_sub_code"),
        "status_hint": MeetingService.sub_code_hint(meeting.get("status_sub_code")),
        "status_history": [
            {"code": h.get("code"), "sub_code": h.get("sub_code"), "source": h.get("source"), "at": h["at"].isoformat() if h.get("at") else None}
            for h in meeting.get("status_history", [])
        ],
        "error": meeting.get("error"),
        "minutes_id": meeting.get("minutes_id"),
        "created_at": meeting["created_at"].isoformat() if meeting.get("created_at") else None,
        "in_call_at": meeting["in_call_at"].isoformat() if meeting.get("in_call_at") else None,
        "ended_at": meeting["ended_at"].isoformat() if meeting.get("ended_at") else None,
    }


@router.get("")
async def list_meetings(request: Request):
    service = get_meeting_service(request.app.mongodb)
    meetings = await service.list_recent()
    return {"items": [_public(m) for m in meetings], "total": len(meetings)}


@router.post("")
async def create_meeting(request: Request, data: MeetingCreate):
    service = get_meeting_service(request.app.mongodb)
    try:
        meeting = await service.create(data.meeting_url, data.title)
    except MeetingValidationError as exc:
        raise HTTPException(400, str(exc))
    except MeetingServiceError as exc:
        raise HTTPException(502, str(exc))
    return {"success": True, "meeting": _public(meeting)}


@router.get("/{meeting_id}")
async def get_meeting(request: Request, meeting_id: str):
    service = get_meeting_service(request.app.mongodb)
    try:
        return {"meeting": _public(await service.get(meeting_id))}
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")


@router.post("/{meeting_id}/refresh")
async def refresh_meeting(request: Request, meeting_id: str):
    service = get_meeting_service(request.app.mongodb)
    try:
        return {"success": True, "meeting": _public(await service.refresh_status(meeting_id))}
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao consultar a Recall.ai: {exc}")


@router.get("/{meeting_id}/live")
async def live(request: Request, meeting_id: str, after_seq: int = Query(0, ge=0)):
    db = request.app.mongodb
    try:
        meeting = await get_meeting_service(db).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    feed = await get_transcript_service(db).live_feed(meeting_id, after_seq=after_seq)
    minutes = await get_minutes_service(db).get_latest(meeting_id)
    feed["meeting"] = _public(meeting)
    feed["has_minutes"] = minutes is not None
    return feed


@router.post("/{meeting_id}/leave")
async def leave(request: Request, meeting_id: str, background: BackgroundTasks, generate: bool = Query(True)):
    db = request.app.mongodb
    service = get_meeting_service(db)
    try:
        meeting = await service.leave(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    if generate:
        background.add_task(_generate_safely, db, meeting_id)
    return {"success": True, "meeting": _public(meeting), "generating": generate}


async def _generate_safely(db, meeting_id: str, force: bool = False):
    import logging

    try:
        await get_minutes_service(db).generate(meeting_id, force=force)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Falha ao gerar ata da reunião %s", meeting_id)
        await get_assistant_service(db).log_event(meeting_id, "minutes_error", {"message": "Falha ao gerar a ata; veja os logs"})


@router.post("/{meeting_id}/minutes")
async def generate_minutes(request: Request, meeting_id: str, force: bool = Query(False)):
    db = request.app.mongodb
    try:
        minutes = await get_minutes_service(db).generate(meeting_id, force=force)
    except MinutesNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    except OpenAIConfigError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao gerar a ata: {exc}")
    return {"success": True, "minutes": _public_minutes(minutes)}


@router.get("/{meeting_id}/minutes")
async def get_minutes(request: Request, meeting_id: str):
    minutes = await get_minutes_service(request.app.mongodb).get_latest(meeting_id)
    if not minutes:
        raise HTTPException(404, "Ata ainda não gerada")
    return {"minutes": _public_minutes(minutes)}


def _public_minutes(minutes: dict) -> dict:
    return {
        "id": minutes["id"],
        "meeting_id": minutes["meeting_id"],
        "ata": minutes["ata"],
        "notes": minutes.get("notes", []),
        "model": minutes.get("model"),
        "transcript_source": minutes.get("transcript_source"),
        "segments_count": minutes.get("segments_count"),
        "generated_at": minutes["generated_at"].isoformat() if minutes.get("generated_at") else None,
    }


@router.post("/{meeting_id}/notes")
async def add_note(request: Request, meeting_id: str, data: NoteCreate):
    db = request.app.mongodb
    try:
        await get_meeting_service(db).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    note = await get_assistant_service(db).save_note(meeting_id, data.text, origin="dashboard")
    return {"success": True, "note": {"id": note["id"], "text": note["text"]}}


EXPORTS = {
    "minutes.md": ("text/markdown; charset=utf-8", "ata-{id}.md"),
    "minutes.json": ("application/json; charset=utf-8", "ata-{id}.json"),
    "minutes.docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ata-{id}.docx"),
    "transcript.txt": ("text/plain; charset=utf-8", "transcricao-{id}.txt"),
    "transcript.json": ("application/json; charset=utf-8", "transcricao-{id}.json"),
}


@router.get("/{meeting_id}/export/{kind}")
async def export(request: Request, meeting_id: str, kind: str):
    if kind not in EXPORTS:
        raise HTTPException(404, "Formato não suportado")
    db = request.app.mongodb
    try:
        meeting = await get_meeting_service(db).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")
    service = get_minutes_service(db)
    media_type, filename = EXPORTS[kind]
    headers = {"Content-Disposition": f'attachment; filename="{filename.format(id=meeting_id[-6:])}"'}
    if kind.startswith("transcript"):
        content = await service.transcript_export(meeting_id, fmt=kind.split(".")[1])
        return PlainTextResponse(content, media_type=media_type, headers=headers)
    minutes = await service.get_latest(meeting_id)
    if not minutes:
        raise HTTPException(404, "Ata ainda não gerada")
    if kind == "minutes.md":
        return PlainTextResponse(service.to_markdown(meeting, minutes), media_type=media_type, headers=headers)
    if kind == "minutes.json":
        return PlainTextResponse(service.to_json(meeting, minutes), media_type=media_type, headers=headers)
    return Response(service.to_docx(meeting, minutes), media_type=media_type, headers=headers)
