"""Lógica da assistente: configuração da sessão Realtime, decisão sobre chamados e contexto."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models import Event, Note, TranscriptSegment
from app.services.core.openai_client import create_realtime_client_secret
from app.utils.text import extract_note, extract_request, find_wake_word, request_is_complete

logger = logging.getLogger(__name__)

NAVI_INSTRUCTIONS = """Você é a Navi, assistente de IA que participa de uma reunião do Microsoft Teams como convidada.
Você ouve a reunião em silêncio e SÓ fala quando alguém chama você pelo nome ("Navi").
Quando chamada:
- Responda em português do Brasil, com voz natural, cordial e objetiva.
- Seja breve: 1 a 3 frases, no máximo cerca de 20 segundos de fala. Nada de listas longas.
- Baseie-se no que foi dito na reunião até agora (você ouviu tudo). Se não tiver a informação, diga isso em uma frase.
- Se pedirem para lembrar, anotar ou registrar algo, confirme em uma frase que anotou e repita o essencial.
- Não faça perguntas de volta, a menos que o pedido seja incompreensível.
- Vá direto ao ponto: nunca anuncie que vai responder ("deixa eu organizar", "vou verificar"); comece pela resposta.
- Só use a função save_note quando alguém pedir EXPLICITAMENTE para lembrar/anotar algo nesta fala. Nunca repita
  uma nota já salva nem anote por conta própria.
- Nunca fale sem ser chamada e nunca interrompa. Depois de responder, volte ao silêncio.
- Não leia URLs, não soletre, não use markdown. Fale como numa reunião.
"""

SAVE_NOTE_TOOL = {
    "type": "function",
    "name": "save_note",
    "description": "Salva uma nota/lembrete da reunião. Use SOMENTE quando alguém pedir explicitamente à Navi para lembrar, anotar, registrar ou guardar algo e a nota ainda não tiver sido salva.",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Conteúdo da nota, em português, de forma clara e completa."}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


NOTE_HINT_WORDS = ("lembr", "esquec", "anot", "regist", "guard", "nota", "salv", "marca ai", "marque")


def looks_like_note_request(request: str) -> bool:
    from app.utils.text import fold

    folded = fold(request or "")
    return any(w in folded for w in NOTE_HINT_WORDS)


def build_turn_detection() -> Dict[str, Any]:
    if settings.OPENAI_TURN_DETECTION == "semantic_vad":
        return {"type": "semantic_vad", "eagerness": "medium", "create_response": False, "interrupt_response": False}
    return {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 500,  # folga maior para não cortar o "Navi" no início da frase
        "silence_duration_ms": settings.OPENAI_VAD_SILENCE_MS,
        "create_response": False,
        "interrupt_response": False,
    }


def build_transcription() -> Dict[str, Any]:
    """gpt-transcribe/gpt-live-transcribe usam `languages` (lista) + `keywords`; modelos antigos usam `language` + `prompt`."""
    model = settings.OPENAI_TRANSCRIBE_MODEL
    if model in ("gpt-transcribe", "gpt-live-transcribe"):
        return {
            "model": model,
            "languages": ["pt"],
            "keywords": ["Navi"],
            "prompt": "Reunião de trabalho em português do Brasil. A assistente de IA se chama Navi e costuma ser chamada pelo nome no início ou no fim das frases.",
        }
    cfg: Dict[str, Any] = {"model": model, "language": "pt"}
    if model.startswith("gpt-4o"):
        cfg["prompt"] = "Reunião de negócios em português do Brasil. A assistente se chama Navi."
    return cfg


def build_truncation() -> Dict[str, Any]:
    """Limita o contexto reenviado a cada resposta (custo) mantendo boa taxa de cache."""
    big_context = any(tag in settings.OPENAI_REALTIME_MODEL for tag in ("-2", "2.1"))
    limit = 64000 if big_context else 24000
    return {"type": "retention_ratio", "retention_ratio": 0.8, "token_limits": {"post_instructions": limit}}


def build_session_config(meeting: Dict[str, Any], context_text: str = "") -> Dict[str, Any]:
    """Sessão Realtime GA: resposta automática DESABILITADA (create_response=false)."""
    instructions = NAVI_INSTRUCTIONS
    if meeting.get("title"):
        instructions += f"\nTítulo da reunião: {meeting['title']}.\n"
    if context_text:
        instructions += f"\nContexto já registrado desta reunião (antes de uma reconexão):\n{context_text}\n"
    session: Dict[str, Any] = {
        "type": "realtime",
        "model": settings.OPENAI_REALTIME_MODEL,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "noise_reduction": {"type": "far_field"},
                "transcription": build_transcription(),
                "turn_detection": build_turn_detection(),
            },
            "output": {"voice": settings.OPENAI_REALTIME_VOICE, "speed": 1.0},
        },
        "tools": [SAVE_NOTE_TOOL],
        "tool_choice": "auto",
        "truncation": build_truncation(),
    }
    if settings.OPENAI_REALTIME_REASONING and any(tag in settings.OPENAI_REALTIME_MODEL for tag in ("-2", "2.1")):
        session["reasoning"] = {"effort": settings.OPENAI_REALTIME_REASONING}
    return session


class AssistantService:
    def __init__(self, db):
        self.db = db
        self.segments = TranscriptSegment(db)
        self.notes = Note(db)
        self.events = Event(db)

    # === Sessão ===

    async def create_session(self, meeting: Dict[str, Any], reconnect: bool = False) -> Dict[str, Any]:
        context_text = await self.build_context_text(meeting["id"]) if reconnect else ""
        session = build_session_config(meeting, context_text)
        secret = await create_realtime_client_secret(session)
        await self.events.create({
            "meeting_id": meeting["id"],
            "type": "realtime_session_created",
            "payload": {"reconnect": reconnect, "model": settings.OPENAI_REALTIME_MODEL, "expires_at": secret["expires_at"]},
        })
        return {
            "client_secret": secret["value"],
            "expires_at": secret["expires_at"],
            "model": settings.OPENAI_REALTIME_MODEL,
            "wake_words": settings.wake_words,
            "max_answer_seconds": settings.NAVI_MAX_ANSWER_SECONDS,
            "context_text": context_text,
        }

    async def build_context_text(self, meeting_id: str, max_segments: int = 60) -> str:
        """Resumo bruto do que já aconteceu (últimas falas + notas) para reinjetar após reconexão."""
        segments = await self.segments.find_by_meeting(meeting_id, limit=5000)
        recall = [s for s in segments if s["source"] == "recall"]
        chosen = recall if recall else [s for s in segments if s["source"] in ("openai", "navi")]
        lines = [f"[{_fmt_ts(s.get('start_ts'))}] {s.get('speaker') or 'Participante'}: {s['text']}" for s in chosen[-max_segments:]]
        notes = await self.notes.find_by_meeting(meeting_id)
        text = "\n".join(lines)
        if notes:
            text += "\n\nNotas já registradas:\n" + "\n".join(f"- {n['text']}" for n in notes)
        return text[-6000:]

    # === Chamados ===

    async def handle_transcript(self, meeting: Dict[str, Any], text: str, item_id: Optional[str], pending_text: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Armazena a fala transcrita pela OpenAI e decide se foi um chamado à Navi.

        Retorna: {"wake": bool, "kind": "note"|"question"|"pending"|None, "instructions": str|None, "note": str|None}
        """
        meeting_id = meeting["id"]
        text = (text or "").strip()
        if text and item_id:
            seq = await self.segments.next_seq(meeting_id)
            await self.segments.create_dedup({
                "meeting_id": meeting_id,
                "seq": seq,
                "source": "openai",
                "speaker": None,
                "text": text,
                "start_ts": _relative_seconds(meeting),
                "dedupe_key": f"openai:{meeting_id}:{item_id}",
            })

        combined = f"{pending_text} {text}".strip() if pending_text else text
        if not combined:
            return {"wake": False}

        span = find_wake_word(combined, settings.wake_words) if not pending_text else (0, 0)
        if span is None:
            return {"wake": False}

        request = extract_request(combined, settings.wake_words) if not pending_text else combined
        request = request or combined
        if not force and not request_is_complete(request):
            return {"wake": True, "kind": "pending", "pending_text": combined}

        note = extract_note(request)
        tools: List[Dict[str, Any]] = []
        if note:
            await self.save_note(meeting_id, note, source_text=combined, origin="wake")
            instructions = (
                f"Alguém pediu para você anotar o seguinte lembrete: \"{note}\". A nota JÁ FOI salva pelo sistema; "
                "NÃO chame nenhuma função. Confirme em uma frase curta, em português, repetindo o essencial "
                "(ex.: 'Anotado: validar o contrato com o fornecedor.')."
            )
            kind = "note"
        elif force and not request_is_complete(request):
            instructions = "Alguém chamou seu nome mas não completou o pedido. Pergunte, em poucas palavras e em português, como pode ajudar."
            kind = "question"
        elif looks_like_note_request(request):
            tools = [SAVE_NOTE_TOOL]
            instructions = (
                f"Você foi chamada pelo nome. O pedido foi: \"{request}\". Se a pessoa está pedindo para você lembrar, "
                "anotar ou registrar algo, chame a função save_note com o conteúdo da nota (uma única vez) e depois "
                "confirme em uma frase. Caso contrário, responda em português do Brasil, de forma breve e objetiva."
            )
            kind = "question"
        else:
            instructions = (
                f"Você foi chamada pelo nome. O pedido foi: \"{request}\". Responda em português do Brasil, "
                "de forma breve (1 a 3 frases) e objetiva, começando direto pela resposta, usando o que foi dito "
                "na reunião até agora. Não anote nada e não chame funções."
            )
            kind = "question"

        await self.events.create({
            "meeting_id": meeting_id,
            "type": "wake_detected",
            "payload": {"text": combined, "request": request, "kind": kind, "note": note},
        })
        return {"wake": True, "kind": kind, "instructions": instructions, "note": note, "request": request, "tools": tools}

    async def save_note(self, meeting_id: str, text: str, source_text: Optional[str] = None, origin: str = "tool") -> Dict[str, Any]:
        from app.utils.text import normalize

        text = text.strip()
        new_norm = normalize(text).rstrip(".")
        for existing in await self.notes.find_by_meeting(meeting_id):
            old_norm = normalize(existing["text"]).rstrip(".")
            if old_norm == new_norm or old_norm in new_norm or new_norm in old_norm:
                logger.info("Nota duplicada ignorada: %r", text)
                return existing
        note_id = await self.notes.create({"meeting_id": meeting_id, "text": text, "source_text": source_text, "origin": origin})
        await self.events.create({"meeting_id": meeting_id, "type": "note_saved", "payload": {"text": text, "origin": origin}})
        return await self.notes.find_by_id(note_id)

    async def record_response(self, meeting: Dict[str, Any], transcript: str, request: Optional[str], response_id: Optional[str]) -> None:
        """Guarda a resposta falada pela Navi como segmento (source=navi) e como evento."""
        meeting_id = meeting["id"]
        transcript = (transcript or "").strip()
        if not transcript:
            return
        seq = await self.segments.next_seq(meeting_id)
        await self.segments.create_dedup({
            "meeting_id": meeting_id,
            "seq": seq,
            "source": "navi",
            "speaker": "Navi",
            "text": transcript,
            "start_ts": _relative_seconds(meeting),
            "dedupe_key": f"navi:{meeting_id}:{response_id}" if response_id else None,
        })
        await self.events.create({"meeting_id": meeting_id, "type": "navi_response", "payload": {"request": request, "transcript": transcript}})

    async def log_event(self, meeting_id: str, type_: str, payload: Optional[Dict[str, Any]] = None) -> None:
        await self.events.create({"meeting_id": meeting_id, "type": type_, "payload": payload or {}})


def _relative_seconds(meeting: Dict[str, Any]) -> Optional[float]:
    """Segundos desde o início da gravação/entrada na call (aproximação para fontes sem timestamp)."""
    start = meeting.get("in_call_at") or meeting.get("created_at")
    if not isinstance(start, datetime):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - start).total_seconds())


def _fmt_ts(value) -> str:
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return "--:--:--"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_assistant_service(db) -> AssistantService:
    return AssistantService(db)
