"""Integração com a OpenAI: credenciais efêmeras do Realtime e geração estruturada da ata."""
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIConfigError(Exception):
    pass


def get_client() -> AsyncOpenAI:
    if not settings.OPENAI_API_KEY:
        raise OpenAIConfigError("OPENAI_API_KEY não configurada")
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


# === Realtime: credencial efêmera ===

async def create_realtime_client_secret(session: Dict[str, Any], ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    """POST /v1/realtime/client_secrets.

    A configuração completa da sessão (instruções, VAD, transcrição, voz, tools) vai embutida
    no client secret; o navegador só precisa fazer a troca de SDP via WebRTC.
    """
    client = get_client()
    ttl = ttl_seconds or settings.OPENAI_EPHEMERAL_TTL_SECONDS
    resp = await client.realtime.client_secrets.create(
        expires_after={"anchor": "created_at", "seconds": max(10, min(ttl, 7200))},
        session=session,  # type: ignore[arg-type]
    )
    return {"value": resp.value, "expires_at": resp.expires_at, "session": resp.session.model_dump(exclude_none=True)}


# === Ata: saída estruturada ===

class Decisao(BaseModel):
    descricao: str = Field(description="Decisão tomada, em uma frase objetiva")
    referencia: str = Field(description="Trecho de origem no formato '[hh:mm:ss] Falante: trecho curto'")


class Pendencia(BaseModel):
    descricao: str = Field(description="Assunto em aberto / não resolvido")
    responsavel: str = Field(description="Quem ficou de resolver, ou 'a definir'")
    referencia: str = Field(description="Trecho de origem no formato '[hh:mm:ss] Falante: trecho curto'")


class Tarefa(BaseModel):
    descricao: str = Field(description="Ação concreta a executar")
    responsavel: str = Field(description="Nome do responsável citado na reunião, ou 'a definir'")
    prazo: str = Field(description="Prazo citado (data ou referência como 'até sexta'), ou 'a definir'")
    referencia: str = Field(description="Trecho de origem no formato '[hh:mm:ss] Falante: trecho curto'")


class AtaReuniao(BaseModel):
    titulo: str = Field(description="Título curto da reunião inferido do conteúdo")
    resumo: str = Field(description="Resumo executivo em 1 a 3 parágrafos, em português do Brasil")
    participantes: List[str] = Field(description="Nomes dos participantes identificados (sem a Navi)")
    decisoes: List[Decisao]
    pendencias: List[Pendencia]
    tarefas: List[Tarefa]


MINUTES_INSTRUCTIONS = """Você é a Navi, assistente que acompanhou uma reunião e agora redige a ata.
Trabalhe APENAS com o que está na transcrição e nas notas; não invente fatos, nomes, prazos ou responsáveis.
Regras:
- Escreva em português do Brasil, tom profissional e objetivo.
- Resumo: o que foi discutido, contexto e conclusões principais.
- Decisões: apenas o que foi efetivamente decidido/aprovado.
- Pendências: assuntos em aberto, dúvidas sem resposta, dependências externas.
- Tarefas (backlog): ações concretas. Para cada uma informe descrição, responsável, prazo e referência.
- Quando responsável ou prazo não forem citados, preencha exatamente com "a definir".
- "referencia" deve apontar para o trecho de origem na transcrição, no formato "[hh:mm:ss] Falante: trecho curto"
  (copie o timestamp e o falante da linha da transcrição; se vier de uma nota da Navi, use "[nota] trecho").
- As notas pedidas à Navi durante a reunião ("Navi, lembre-se de ...") normalmente viram tarefas ou pendências.
- Não inclua a própria Navi como participante nem como responsável.
"""


async def generate_minutes(transcript_text: str, notes: List[str], navi_log: List[str], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Gera a ata estruturada a partir da transcrição consolidada usando um modelo de texto."""
    client = get_client()
    notes_block = "\n".join(f"- {n}" for n in notes) if notes else "(nenhuma)"
    navi_block = "\n".join(f"- {n}" for n in navi_log) if navi_log else "(nenhuma)"
    user_input = (
        f"Dados da reunião: {meta}\n\n"
        f"=== NOTAS PEDIDAS À NAVI ===\n{notes_block}\n\n"
        f"=== INTERVENÇÕES DA NAVI (perguntas e respostas) ===\n{navi_block}\n\n"
        f"=== TRANSCRIÇÃO (formato [hh:mm:ss] Falante: texto) ===\n{transcript_text or '(transcrição vazia)'}\n"
    )
    kwargs: Dict[str, Any] = {}
    if settings.OPENAI_TEXT_REASONING:
        kwargs["reasoning"] = {"effort": settings.OPENAI_TEXT_REASONING}

    models = [settings.OPENAI_TEXT_MODEL] + [m.strip() for m in settings.OPENAI_TEXT_MODEL_FALLBACKS.split(",") if m.strip()]
    last_error: Optional[Exception] = None
    for model in models:
        try:
            response = await client.responses.parse(
                model=model,
                instructions=MINUTES_INSTRUCTIONS,
                input=user_input,
                text_format=AtaReuniao,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — tenta o próximo modelo (ex.: modelo indisponível na conta)
            logger.warning("Geração da ata falhou com %s: %s", model, exc)
            last_error = exc
            continue
        parsed: Optional[AtaReuniao] = response.output_parsed
        if parsed is None:
            last_error = RuntimeError(f"{model} não retornou a ata estruturada (status={response.status})")
            continue
        usage = response.usage.model_dump() if response.usage else {}
        return {"ata": parsed.model_dump(), "model": model, "usage": usage, "response_id": response.id}
    raise RuntimeError(f"Não foi possível gerar a ata: {last_error}")
