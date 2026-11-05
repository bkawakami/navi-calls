"""Ciclo de vida da reunião: criação do bot na Recall, status, saída e encerramento."""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from app.config import settings
from app.models import Event, Meeting
from app.models.meeting import FINAL_STATUSES
from app.routes.shared.auth import make_page_token
from app.services.core.recall_client import RecallClient, RecallConfigError, RecallError, get_recall_client

logger = logging.getLogger(__name__)

# Formatos documentados em https://docs.recall.ai/docs/meeting-urls (a validação final é da própria Recall).
TEAMS_URL_PATTERNS = [
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/l/meetup-join/",
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/l/message/",
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/meet/\d+",
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/light-meetings/launch",
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/dl/launcher/",
    r"^https://teams\.(microsoft\.com|cloud\.microsoft)/(_|v2)#/",
    r"^https://teams\.live\.com/meet/\d+",
    r"^https://[a-z0-9.-]*teams\.microsoft\.(com|us)/",
    r"^https://[a-z0-9.-]*teams\.cloud\.microsoft/",
]

RECALL_PROVIDER_CONFIGS = {
    # Recall.ai Transcription: em português só "prioritize_accuracy" (eventos chegam com 3-10 min de atraso).
    "recallai_streaming": lambda lang: {"mode": "prioritize_low_latency" if lang == "en" else "prioritize_accuracy", "language_code": lang},
    "deepgram_streaming": lambda lang: {"model": "nova-3", "language": "pt-BR" if lang in ("pt", "pt-BR") else lang, "smart_format": True, "punctuate": True},
    "assembly_ai_v3_streaming": lambda lang: {"speech_model": "universal-streaming-multilingual", "language_detection": True, "format_turns": True},
    "speechmatics_streaming": lambda lang: {"language": lang.split("-")[0], "operating_point": "enhanced"},
    "elevenlabs_streaming": lambda lang: {"model_id": "eleven_whisper_v2_realtime", "language_code": lang.split("-")[0]},
    "soniox_streaming": lambda lang: {"model": "stt-rt-preview", "language_hints": [lang.split("-")[0]]},
    "meeting_captions": lambda lang: {"language_code": lang},
}

STATUS_LABELS = {
    "created": "Criando bot",
    "ready": "Bot criado",
    "joining_call": "Entrando na reunião",
    "in_waiting_room": "No lobby — admita a Navi no Teams",
    "in_call_not_recording": "Na reunião (sem gravar)",
    "recording_permission_allowed": "Permissão de gravação concedida",
    "recording_permission_denied": "Permissão de gravação negada",
    "in_call_recording": "Na reunião, ouvindo",
    "call_ended": "Reunião encerrada",
    "done": "Concluída",
    "fatal": "Falha ao entrar/permanecer na reunião",
    "media_expired": "Mídia expirada",
}

SUB_CODE_HINTS = {
    "meeting_not_accessible": "O organizador precisa permitir participantes anônimos (Meeting access / Who can bypass the lobby).",
    "meeting_requires_sign_in": "O tenant exige login: habilite 'Anonymous users can join a meeting' ou use um bot autenticado.",
    "microsoft_teams_sign_in_credentials_missing": "O tenant exige login para convidados anônimos.",
    "microsoft_teams_captcha_error": "O tenant exige captcha para anônimos; só bots autenticados conseguem entrar.",
    "meeting_not_found": "Link inválido ou reunião inexistente.",
    "meeting_link_expired": "Link expirado.",
    "meeting_ended": "A reunião já havia terminado.",
    "timeout_exceeded_waiting_room": "Ninguém admitiu a Navi no lobby a tempo.",
    "call_ended_by_platform_waiting_room_timeout": "O Teams limita a espera no lobby a 30 minutos.",
    "bot_kicked_from_call": "A Navi foi removida da reunião por um participante.",
    "bot_kicked_from_waiting_room": "A Navi foi recusada no lobby.",
    "bot_received_leave_call": "Saída solicitada pelo painel.",
    "timeout_exceeded_everyone_left": "Todos saíram da reunião.",
    "timeout_exceeded_noone_joined": "Ninguém entrou na reunião.",
    "microsoft_teams_call_dropped": "A chamada caiu no Teams.",
    "teams_blacklisted_tenant": "Este tenant do Teams bloqueia bots; não há contorno.",
}


class MeetingServiceError(Exception):
    pass


class MeetingNotFoundError(MeetingServiceError):
    pass


class MeetingValidationError(MeetingServiceError):
    pass


class MeetingService:
    def __init__(self, db, recall: Optional[RecallClient] = None):
        self.db = db
        self.meetings = Meeting(db)
        self.events = Event(db)
        self.recall = recall or get_recall_client()

    # === Criação ===

    @staticmethod
    def validate_meeting_url(url: str) -> str:
        url = (url or "").strip()
        if not url:
            raise MeetingValidationError("Informe o link da reunião do Teams")
        if not any(re.match(p, url, re.IGNORECASE) for p in TEAMS_URL_PATTERNS):
            raise MeetingValidationError("Link não reconhecido como reunião do Microsoft Teams")
        return url

    def assistant_page_url(self, meeting_id: str) -> str:
        return f"{settings.BASE_URL.rstrip('/')}/assistant/{meeting_id}?{urlencode({'token': make_page_token(meeting_id)})}"

    def realtime_webhook_url(self) -> str:
        # A Recall exige barra final antes da query string nos endpoints em tempo real.
        base = f"{settings.BASE_URL.rstrip('/')}/api/webhooks/recall/realtime/"
        if settings.RECALL_REALTIME_SECRET:
            base += "?" + urlencode({"secret": settings.RECALL_REALTIME_SECRET})
        return base

    def build_bot_payload(self, meeting_id: str, meeting_url: str) -> Dict[str, Any]:
        """Payload de POST /api/v1/bot/ (docs: Create Bot, Output Media, Real-time transcription)."""
        recording_config: Dict[str, Any] = {
            # Mantemos a Navi fora da gravação/transcrição da Recall (ela não ouve a própria voz).
            "include_bot_in_recording": {"audio": False},
            "start_recording_on": "participant_join",
        }
        provider_key = settings.RECALL_TRANSCRIPT_PROVIDER
        if provider_key and provider_key != "none":
            builder = RECALL_PROVIDER_CONFIGS.get(provider_key, lambda lang: {})
            recording_config["transcript"] = {
                "provider": {provider_key: builder(settings.RECALL_TRANSCRIPT_LANGUAGE)},
                "diarization": {"use_separate_streams_when_available": True},
            }
            recording_config["realtime_endpoints"] = [
                {"type": "webhook", "url": self.realtime_webhook_url(), "events": ["transcript.data"]},
            ]
        payload: Dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": settings.RECALL_BOT_NAME,
            "metadata": {"meeting_id": meeting_id, "app": "navi"},
            "variant": {"microsoft_teams": settings.RECALL_BOT_VARIANT},
            "output_media": {
                "camera": {"kind": "webpage", "config": {"url": self.assistant_page_url(meeting_id)}},
            },
            "recording_config": recording_config,
            "automatic_leave": {
                "waiting_room_timeout": 1200,
                "noone_joined_timeout": 1200,
                "everyone_left_timeout": {"timeout": 60, "activate_after": None},
                "in_call_not_recording_timeout": 3600,
            },
        }
        return payload

    async def _create_bot_with_retry(self, payload: Dict[str, Any], attempts: int = 3) -> Dict[str, Any]:
        """507 = pool regional de bots ad-hoc vazio; 429 = rate limit. Ambos pedem retry."""
        last: Optional[RecallError] = None
        for i in range(attempts):
            try:
                return await self.recall.create_bot(payload)
            except RecallError as exc:
                if exc.status in (507, 429, 502, 503, 504) and i < attempts - 1:
                    last = exc
                    await asyncio.sleep(5)
                    continue
                raise
        raise last  # type: ignore[misc]

    async def create(self, meeting_url: str, title: Optional[str] = None) -> Dict[str, Any]:
        meeting_url = self.validate_meeting_url(meeting_url)
        meeting_id = await self.meetings.create({
            "meeting_url": meeting_url,
            "title": (title or "").strip() or None,
            "platform": "microsoft_teams",
            "bot_name": settings.RECALL_BOT_NAME,
            "bot_id": None,
            "status": "created",
            "status_history": [{"code": "created", "sub_code": None, "source": "app", "at": datetime.now(timezone.utc)}],
            "recall_region": settings.RECALL_REGION,
        })
        payload = self.build_bot_payload(meeting_id, meeting_url)
        try:
            bot = await self._create_bot_with_retry(payload)
        except RecallConfigError as exc:
            await self._fail(meeting_id, "config_error", str(exc))
            raise MeetingServiceError(str(exc)) from exc
        except RecallError as exc:
            await self._fail(meeting_id, f"recall_{exc.status}", f"{exc} — {exc.body}")
            raise MeetingServiceError(f"Recall.ai recusou a criação do bot: {exc.body}") from exc

        await self.meetings.update(meeting_id, {
            "bot_id": bot.get("id"),
            "bot_payload": payload,
            "bot_raw": bot,
            "status": "ready",
        })
        await self.events.create({"meeting_id": meeting_id, "type": "bot_created", "payload": {"bot_id": bot.get("id")}})
        await self.apply_bot_status(meeting_id, bot, source="create")
        return await self.get(meeting_id)

    async def _fail(self, meeting_id: str, code: str, message: str) -> None:
        await self.meetings.set_status(meeting_id, "fatal", sub_code=code, source="app")
        await self.meetings.update(meeting_id, {"error": message})
        await self.events.create({"meeting_id": meeting_id, "type": "bot_error", "payload": {"code": code, "message": message}})

    # === Leitura ===

    async def get(self, meeting_id: str) -> Dict[str, Any]:
        meeting = await self.meetings.find_by_id(meeting_id)
        if not meeting:
            raise MeetingNotFoundError("Reunião não encontrada")
        return meeting

    async def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return await self.meetings.find_recent(limit)

    # === Status ===

    async def apply_bot_status(self, meeting_id: str, bot: Dict[str, Any], source: str = "poll") -> Optional[str]:
        """Aplica o último status de `status_changes` de um objeto bot da Recall."""
        changes = bot.get("status_changes") or []
        if not changes:
            return None
        last = changes[-1]
        code = last.get("code")
        if not code:
            return None
        changed = await self.meetings.set_status(meeting_id, code, sub_code=last.get("sub_code"), source=source)
        if changed:
            await self._after_status(meeting_id, code, last.get("sub_code"))
        return code

    async def apply_webhook_status(self, bot_id: str, code: str, sub_code: Optional[str], raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        meeting = await self.meetings.find_by_bot_id(bot_id)
        if not meeting:
            logger.warning("Webhook de status para bot desconhecido %s", bot_id)
            return None
        changed = await self.meetings.set_status(meeting["id"], code, sub_code=sub_code, source="webhook")
        await self.events.create({"meeting_id": meeting["id"], "type": "webhook", "payload": {"code": code, "sub_code": sub_code}})
        if changed:
            await self._after_status(meeting["id"], code, sub_code)
        return await self.meetings.find_by_id(meeting["id"])

    async def _after_status(self, meeting_id: str, code: str, sub_code: Optional[str]) -> None:
        if code in ("in_call_not_recording", "in_call_recording"):
            meeting = await self.meetings.find_by_id(meeting_id)
            if meeting and not meeting.get("in_call_at"):
                await self.meetings.update(meeting_id, {"in_call_at": datetime.now(timezone.utc)})
        if code == "fatal":
            await self.events.create({"meeting_id": meeting_id, "type": "bot_error", "payload": {"code": "fatal", "message": f"Bot encerrou com falha: {sub_code or 'sem detalhe'}"}})

    async def refresh_status(self, meeting_id: str) -> Dict[str, Any]:
        meeting = await self.get(meeting_id)
        if not meeting.get("bot_id"):
            return meeting
        bot = await self.recall.get_bot(meeting["bot_id"])
        await self.meetings.update(meeting_id, {"bot_raw": bot})
        await self.apply_bot_status(meeting_id, bot, source="poll")
        return await self.get(meeting_id)

    async def poll_active(self) -> int:
        """Atualiza status das reuniões ativas (fallback quando webhooks não chegam)."""
        active = await self.meetings.find_active()
        n = 0
        for meeting in active:
            if not meeting.get("bot_id"):
                continue
            try:
                await self.refresh_status(meeting["id"])
                n += 1
            except RecallError as exc:
                logger.warning("Falha ao consultar bot %s: %s", meeting.get("bot_id"), exc)
            except Exception:  # noqa: BLE001
                logger.exception("Erro no polling da reunião %s", meeting["id"])
        return n

    # === Encerramento ===

    async def leave(self, meeting_id: str) -> Dict[str, Any]:
        meeting = await self.get(meeting_id)
        if meeting.get("bot_id") and meeting.get("status") not in FINAL_STATUSES:
            try:
                await self.recall.leave_call(meeting["bot_id"])
                await self.events.create({"meeting_id": meeting_id, "type": "leave_requested", "payload": {}})
            except RecallError as exc:
                logger.warning("leave_call falhou: %s", exc)
                await self.events.create({"meeting_id": meeting_id, "type": "bot_error", "payload": {"code": "leave_failed", "message": str(exc.body)}})
        await self.meetings.set_status(meeting_id, "call_ended", sub_code="left_by_user", source="app")
        return await self.get(meeting_id)

    @staticmethod
    def status_label(code: Optional[str]) -> str:
        return STATUS_LABELS.get(code or "", code or "—")

    @staticmethod
    def sub_code_hint(sub_code: Optional[str]) -> Optional[str]:
        return SUB_CODE_HINTS.get(sub_code or "")


def get_meeting_service(db) -> MeetingService:
    return MeetingService(db)
