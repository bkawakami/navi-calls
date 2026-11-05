"""Ingestão da transcrição da Recall.ai (tempo real e final) e leitura do feed ao vivo."""
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.models import Event, Meeting, Note, TranscriptSegment
from app.services.core.recall_client import RecallError, get_recall_client

logger = logging.getLogger(__name__)

NAVI_BOT_PARTICIPANT_ID = 2147483647  # id que a Recall atribui ao áudio do próprio bot (quando incluído)


class TranscriptService:
    def __init__(self, db):
        self.db = db
        self.meetings = Meeting(db)
        self.segments = TranscriptSegment(db)
        self.notes = Note(db)
        self.events = Event(db)

    # === Webhook em tempo real da Recall ===

    @staticmethod
    def parse_utterance(inner: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Converte um "utterance" ({words, participant, language_code}) em um segmento.

        Formato (docs "Real-time event payloads" e "Download schemas"):
        {"words": [{"text", "start_timestamp": {"relative", "absolute"?}, "end_timestamp": {...}|null}],
         "participant": {"id", "name", "is_host", "platform", "extra_data", "email"}, "language_code": "pt"}
        """
        words = inner.get("words") or []
        participant = inner.get("participant") or {}
        text = " ".join((w.get("text") or "").strip() for w in words if w.get("text")).strip()
        if not text:
            return None

        def ts(word: Optional[Dict[str, Any]], key: str, kind: str):
            value = (word or {}).get(key) or {}
            return value.get(kind) if isinstance(value, dict) else None

        last_end = None
        for w in reversed(words):
            last_end = ts(w, "end_timestamp", "relative")
            if last_end is not None:
                break
        pid = participant.get("id")
        speaker = participant.get("name") or ("Navi" if pid == NAVI_BOT_PARTICIPANT_ID else "Participante")
        return {
            "text": text,
            "speaker": speaker,
            "participant_id": pid,
            "is_host": participant.get("is_host"),
            "start_ts": ts(words[0], "start_timestamp", "relative"),
            "end_ts": last_end,
            "absolute": ts(words[0], "start_timestamp", "absolute"),
            "language": inner.get("language_code"),
        }

    @staticmethod
    def parse_realtime_event(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event = body.get("event") or ""
        data = body.get("data") or {}
        parsed = TranscriptService.parse_utterance(data.get("data") or {})
        if not parsed:
            return None
        parsed["event"] = event
        parsed["bot_id"] = (data.get("bot") or {}).get("id")
        return parsed

    async def _store(self, meeting_id: str, parsed: Dict[str, Any]) -> Optional[str]:
        digest = hashlib.sha1(f"{parsed.get('participant_id')}|{parsed.get('start_ts')}|{parsed['text']}".encode()).hexdigest()[:16]
        seq = await self.segments.next_seq(meeting_id)
        return await self.segments.create_dedup({
            "meeting_id": meeting_id,
            "seq": seq,
            "source": "recall",
            "speaker": parsed["speaker"],
            "participant_id": parsed.get("participant_id"),
            "text": parsed["text"],
            "start_ts": parsed.get("start_ts"),
            "end_ts": parsed.get("end_ts"),
            "absolute_ts": parsed.get("absolute"),
            "language": parsed.get("language"),
            "dedupe_key": f"recall:{meeting_id}:{digest}",
        })

    async def ingest_realtime(self, body: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self.parse_realtime_event(body)
        if not parsed:
            return {"stored": False, "reason": "sem texto"}
        if parsed["event"] != "transcript.data":  # parciais não são armazenadas
            return {"stored": False, "reason": f"evento {parsed['event']} ignorado"}
        meeting = await self.meetings.find_by_bot_id(parsed["bot_id"]) if parsed["bot_id"] else None
        if not meeting:
            logger.warning("Webhook realtime para bot desconhecido: %s", parsed["bot_id"])
            return {"stored": False, "reason": "bot desconhecido"}
        segment_id = await self._store(meeting["id"], parsed)
        return {"stored": segment_id is not None, "meeting_id": meeting["id"]}

    # === Transcrição final (webhook transcript.done) ===

    async def ingest_final_transcript(self, bot_id: str, transcript_id: Optional[str]) -> Dict[str, Any]:
        """Baixa a transcrição consolidada da Recall e insere os trechos que ainda não temos."""
        meeting = await self.meetings.find_by_bot_id(bot_id)
        if not meeting:
            return {"stored": 0, "reason": "bot desconhecido"}
        recall = get_recall_client()
        try:
            download_url = None
            if transcript_id:
                artifact = await recall.get_transcript(transcript_id)
                download_url = ((artifact or {}).get("data") or {}).get("download_url")
            if not download_url:
                bot = await recall.get_bot(bot_id)
                for rec in bot.get("recordings") or []:
                    shortcut = ((rec.get("media_shortcuts") or {}).get("transcript") or {})
                    download_url = (shortcut.get("data") or {}).get("download_url")
                    if download_url:
                        break
            if not download_url:
                return {"stored": 0, "reason": "download_url indisponível"}
            utterances = await recall.download_json(download_url)
        except RecallError as exc:
            logger.warning("Falha ao baixar transcrição final do bot %s: %s", bot_id, exc)
            return {"stored": 0, "reason": str(exc)}

        stored = 0
        for utt in utterances or []:
            parsed = self.parse_utterance(utt)
            if parsed and await self._store(meeting["id"], parsed):
                stored += 1
        await self.events.create({"meeting_id": meeting["id"], "type": "transcript_final", "payload": {"utterances": len(utterances or []), "new_segments": stored}})
        logger.info("Transcrição final do bot %s: %d utterances, %d novos", bot_id, len(utterances or []), stored)
        return {"stored": stored, "meeting_id": meeting["id"]}

    # === Feed ao vivo para o painel ===

    async def live_feed(self, meeting_id: str, after_seq: int = 0) -> Dict[str, Any]:
        segments = await self.segments.find_by_meeting(meeting_id, after_seq=after_seq, limit=500)
        notes = await self.notes.find_by_meeting(meeting_id)
        events = await self.events.find_by_meeting(
            meeting_id,
            types=["wake_detected", "navi_response", "note_saved", "realtime_connected", "realtime_disconnected", "realtime_error", "minutes_generated", "minutes_error", "bot_error", "transcript_final"],
            limit=300,
        )
        counts = await self.segments.count_by_source(meeting_id)
        return {
            "segments": [_public_segment(s) for s in segments],
            "notes": [{"id": n["id"], "text": n["text"], "created_at": _iso(n.get("created_at"))} for n in notes],
            "events": [{"id": e["id"], "type": e["type"], "payload": e.get("payload", {}), "created_at": _iso(e.get("created_at"))} for e in events],
            "counts": counts,
        }


def _public_segment(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s["id"],
        "seq": s.get("seq"),
        "source": s.get("source"),
        "speaker": s.get("speaker"),
        "text": s.get("text"),
        "start_ts": s.get("start_ts"),
        "created_at": _iso(s.get("created_at")),
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def get_transcript_service(db) -> TranscriptService:
    return TranscriptService(db)
