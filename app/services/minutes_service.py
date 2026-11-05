"""Consolidação da transcrição e geração/exportação da ata."""
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models import Event, Meeting, Minutes, Note, TranscriptSegment
from app.services.core.openai_client import generate_minutes

logger = logging.getLogger(__name__)


class MinutesError(Exception):
    pass


class MinutesNotFoundError(MinutesError):
    pass


def fmt_ts(value) -> str:
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return "--:--:--"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class MinutesService:
    def __init__(self, db):
        self.db = db
        self.meetings = Meeting(db)
        self.segments = TranscriptSegment(db)
        self.notes = Note(db)
        self.events = Event(db)
        self.minutes = Minutes(db)

    # === Transcrição consolidada ===

    async def consolidated_segments(self, meeting_id: str) -> List[Dict[str, Any]]:
        """Prefere a transcrição da Recall (com nome do falante); senão usa a da OpenAI. Inclui falas da Navi."""
        all_segments = await self.segments.find_by_meeting(meeting_id, limit=20000)
        recall = [s for s in all_segments if s["source"] == "recall"]
        openai = [s for s in all_segments if s["source"] == "openai"]
        navi = [s for s in all_segments if s["source"] == "navi"]
        base = recall if recall else openai
        merged = base + navi
        merged.sort(key=lambda s: ((s.get("start_ts") if s.get("start_ts") is not None else 1e12), s.get("seq", 0)))
        return merged

    async def transcript_text(self, meeting_id: str) -> str:
        segments = await self.consolidated_segments(meeting_id)
        return "\n".join(f"[{fmt_ts(s.get('start_ts'))}] {s.get('speaker') or 'Participante'}: {s['text']}" for s in segments)

    # === Geração ===

    async def generate(self, meeting_id: str, force: bool = False) -> Dict[str, Any]:
        meeting = await self.meetings.find_by_id(meeting_id)
        if not meeting:
            raise MinutesNotFoundError("Reunião não encontrada")
        existing = await self.minutes.find_latest(meeting_id)
        if existing and not force:
            return existing

        transcript = await self.transcript_text(meeting_id)
        notes = [n["text"] for n in await self.notes.find_by_meeting(meeting_id)]
        navi_events = await self.events.find_by_meeting(meeting_id, types=["navi_response"])
        navi_log = [f"Pedido: {e['payload'].get('request') or '-'} | Resposta: {e['payload'].get('transcript')}" for e in navi_events]
        meta = {
            "titulo_informado": meeting.get("title") or "",
            "plataforma": "Microsoft Teams",
            "inicio": (meeting.get("in_call_at") or meeting.get("created_at")).isoformat() if meeting.get("created_at") else "",
            "fim": meeting.get("ended_at").isoformat() if meeting.get("ended_at") else "",
        }
        result = await generate_minutes(transcript, notes, navi_log, meta)
        segments = await self.consolidated_segments(meeting_id)
        source = "recall" if any(s["source"] == "recall" for s in segments) else "openai"
        doc = {
            "meeting_id": meeting_id,
            "ata": result["ata"],
            "model": result["model"],
            "usage": result.get("usage"),
            "notes": notes,
            "transcript_chars": len(transcript),
            "transcript_source": source,
            "segments_count": len(segments),
            "generated_at": datetime.now(timezone.utc),
        }
        minutes_id = await self.minutes.create(doc)
        await self.meetings.update(meeting_id, {"minutes_id": minutes_id})
        await self.events.create({"meeting_id": meeting_id, "type": "minutes_generated", "payload": {"minutes_id": minutes_id, "model": result["model"]}})
        return await self.minutes.find_by_id(minutes_id)

    async def get_latest(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        return await self.minutes.find_latest(meeting_id)

    async def maybe_upgrade_with_recall(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Se a ata foi gerada só com a transcrição da OpenAI e a da Recall (com falantes) chegou depois, regera."""
        latest = await self.minutes.find_latest(meeting_id)
        if not latest or latest.get("transcript_source") == "recall":
            return None
        counts = await self.segments.count_by_source(meeting_id)
        if not counts.get("recall"):
            return None
        logger.info("Regerando ata da reunião %s com a transcrição da Recall", meeting_id)
        return await self.generate(meeting_id, force=True)

    # === Exportação ===

    @staticmethod
    def to_markdown(meeting: Dict[str, Any], minutes: Dict[str, Any]) -> str:
        ata = minutes["ata"]
        gen = minutes.get("generated_at")
        gen_str = gen.strftime("%d/%m/%Y %H:%M UTC") if isinstance(gen, datetime) else ""
        lines = [f"# Ata — {ata.get('titulo') or meeting.get('title') or 'Reunião'}", ""]
        lines += [f"*Gerada pela Navi em {gen_str}. Link da reunião: {meeting.get('meeting_url', '')}*", ""]
        if ata.get("participantes"):
            lines += ["## Participantes", ""] + [f"- {p}" for p in ata["participantes"]] + [""]
        lines += ["## Resumo", "", ata.get("resumo", ""), ""]
        lines += ["## Decisões", ""]
        lines += [f"- {d['descricao']}  \n  _Origem: {d['referencia']}_" for d in ata.get("decisoes", [])] or ["- (nenhuma decisão registrada)"]
        lines += ["", "## Pendências", ""]
        lines += [f"- {p['descricao']} — **Responsável:** {p['responsavel']}  \n  _Origem: {p['referencia']}_" for p in ata.get("pendencias", [])] or ["- (nenhuma pendência registrada)"]
        lines += ["", "## Tarefas (backlog)", ""]
        tasks = ata.get("tarefas", [])
        if tasks:
            lines += ["| # | Descrição | Responsável | Prazo | Origem |", "|---|---|---|---|---|"]
            for i, t in enumerate(tasks, 1):
                lines.append(f"| {i} | {_cell(t['descricao'])} | {_cell(t['responsavel'])} | {_cell(t['prazo'])} | {_cell(t['referencia'])} |")
        else:
            lines.append("- (nenhuma tarefa registrada)")
        if minutes.get("notes"):
            lines += ["", "## Notas pedidas à Navi durante a reunião", ""] + [f"- {n}" for n in minutes["notes"]]
        lines += ["", "---", f"_Modelo: {minutes.get('model', '')} · Segmentos de transcrição: {minutes.get('segments_count', 0)}_", ""]
        return "\n".join(lines)

    @staticmethod
    def to_json(meeting: Dict[str, Any], minutes: Dict[str, Any]) -> str:
        payload = {
            "meeting": {"id": meeting["id"], "title": meeting.get("title"), "meeting_url": meeting.get("meeting_url"), "status": meeting.get("status")},
            "generated_at": minutes.get("generated_at").isoformat() if isinstance(minutes.get("generated_at"), datetime) else None,
            "model": minutes.get("model"),
            "ata": minutes["ata"],
            "notas_navi": minutes.get("notes", []),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def to_docx(meeting: Dict[str, Any], minutes: Dict[str, Any]) -> bytes:
        from docx import Document

        ata = minutes["ata"]
        doc = Document()
        doc.add_heading(f"Ata — {ata.get('titulo') or meeting.get('title') or 'Reunião'}", level=0)
        gen = minutes.get("generated_at")
        doc.add_paragraph(f"Gerada pela Navi em {gen.strftime('%d/%m/%Y %H:%M UTC') if isinstance(gen, datetime) else ''}")
        if ata.get("participantes"):
            doc.add_heading("Participantes", level=1)
            for p in ata["participantes"]:
                doc.add_paragraph(p, style="List Bullet")
        doc.add_heading("Resumo", level=1)
        doc.add_paragraph(ata.get("resumo", ""))
        doc.add_heading("Decisões", level=1)
        for d in ata.get("decisoes", []) or []:
            doc.add_paragraph(f"{d['descricao']} (origem: {d['referencia']})", style="List Bullet")
        if not ata.get("decisoes"):
            doc.add_paragraph("Nenhuma decisão registrada.")
        doc.add_heading("Pendências", level=1)
        for p in ata.get("pendencias", []) or []:
            doc.add_paragraph(f"{p['descricao']} — Responsável: {p['responsavel']} (origem: {p['referencia']})", style="List Bullet")
        if not ata.get("pendencias"):
            doc.add_paragraph("Nenhuma pendência registrada.")
        doc.add_heading("Tarefas (backlog)", level=1)
        tasks = ata.get("tarefas", []) or []
        if tasks:
            table = doc.add_table(rows=1, cols=5)
            table.style = "Light Grid Accent 1"
            for i, h in enumerate(["#", "Descrição", "Responsável", "Prazo", "Origem"]):
                table.rows[0].cells[i].text = h
            for i, t in enumerate(tasks, 1):
                row = table.add_row().cells
                row[0].text, row[1].text, row[2].text, row[3].text, row[4].text = str(i), t["descricao"], t["responsavel"], t["prazo"], t["referencia"]
        else:
            doc.add_paragraph("Nenhuma tarefa registrada.")
        if minutes.get("notes"):
            doc.add_heading("Notas pedidas à Navi", level=1)
            for n in minutes["notes"]:
                doc.add_paragraph(n, style="List Bullet")
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    async def transcript_export(self, meeting_id: str, fmt: str = "txt") -> str:
        segments = await self.consolidated_segments(meeting_id)
        if fmt == "json":
            return json.dumps(
                [{"seq": s.get("seq"), "start": s.get("start_ts"), "end": s.get("end_ts"), "speaker": s.get("speaker"), "source": s.get("source"), "text": s["text"]} for s in segments],
                ensure_ascii=False,
                indent=2,
            )
        return "\n".join(f"[{fmt_ts(s.get('start_ts'))}] {s.get('speaker') or 'Participante'}: {s['text']}" for s in segments)


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def get_minutes_service(db) -> MinutesService:
    return MinutesService(db)
