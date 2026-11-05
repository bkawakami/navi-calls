"""APIs usadas pela página da assistente (Output Media). Autenticadas pelo token da página."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.routes.shared.auth import require_page_token
from app.services.assistant_service import get_assistant_service
from app.services.core.openai_client import OpenAIConfigError
from app.services.meeting_service import MeetingNotFoundError, get_meeting_service

router = APIRouter(dependencies=[Depends(require_page_token)])


class TranscriptIn(BaseModel):
    text: str = Field("", max_length=5000)
    item_id: Optional[str] = None
    pending_text: Optional[str] = Field(None, max_length=5000)
    force: bool = False


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    call_id: Optional[str] = None


class ResponseIn(BaseModel):
    transcript: str = Field("", max_length=5000)
    request: Optional[str] = None
    response_id: Optional[str] = None


class EventIn(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)


async def _meeting(request: Request, meeting_id: str) -> dict:
    try:
        return await get_meeting_service(request.app.mongodb).get(meeting_id)
    except MeetingNotFoundError:
        raise HTTPException(404, "Reunião não encontrada")


@router.post("/{meeting_id}/session")
async def create_session(request: Request, meeting_id: str, reconnect: bool = Query(False)):
    meeting = await _meeting(request, meeting_id)
    try:
        return await get_assistant_service(request.app.mongodb).create_session(meeting, reconnect=reconnect)
    except OpenAIConfigError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao criar sessão Realtime: {exc}")


@router.post("/{meeting_id}/transcript")
async def transcript(request: Request, meeting_id: str, data: TranscriptIn):
    meeting = await _meeting(request, meeting_id)
    service = get_assistant_service(request.app.mongodb)
    return await service.handle_transcript(meeting, data.text, data.item_id, pending_text=data.pending_text, force=data.force)


@router.post("/{meeting_id}/notes")
async def note(request: Request, meeting_id: str, data: NoteIn):
    await _meeting(request, meeting_id)
    saved = await get_assistant_service(request.app.mongodb).save_note(meeting_id, data.text, origin="tool")
    return {"success": True, "note": {"id": saved["id"], "text": saved["text"]}}


@router.post("/{meeting_id}/response")
async def response(request: Request, meeting_id: str, data: ResponseIn):
    meeting = await _meeting(request, meeting_id)
    await get_assistant_service(request.app.mongodb).record_response(meeting, data.transcript, data.request, data.response_id)
    return {"success": True}


@router.post("/{meeting_id}/events")
async def event(request: Request, meeting_id: str, data: EventIn):
    await _meeting(request, meeting_id)
    await get_assistant_service(request.app.mongodb).log_event(meeting_id, f"realtime_{data.type}" if not data.type.startswith("realtime_") else data.type, data.payload)
    return {"success": True}


@router.get("/{meeting_id}/context")
async def context(request: Request, meeting_id: str):
    await _meeting(request, meeting_id)
    text = await get_assistant_service(request.app.mongodb).build_context_text(meeting_id)
    return {"context_text": text}
