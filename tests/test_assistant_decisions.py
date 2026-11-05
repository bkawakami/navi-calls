"""Decisão de chamado (handle_transcript) contra o MongoDB local de teste."""
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.models import ensure_indexes
from app.services.assistant_service import AssistantService


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
    database = client["navi_test"]
    try:
        await database.command("ping")
    except Exception:
        pytest.skip("MongoDB de teste indisponível em " + settings.MONGODB_URL)
    await database.transcript_segments.delete_many({})
    await database.notes.delete_many({})
    await database.events.delete_many({})
    await ensure_indexes(database)
    yield database
    client.close()


MEETING = {"id": "test-meeting-1", "title": "Teste"}


async def test_plain_speech_is_stored_without_wake(db):
    svc = AssistantService(db)
    result = await svc.handle_transcript(MEETING, "Vamos começar pela proposta do fornecedor.", "item_1")
    assert result == {"wake": False}
    stored = await db.transcript_segments.find_one({"dedupe_key": "openai:test-meeting-1:item_1"})
    assert stored and stored["source"] == "openai"


async def test_remember_request_saves_note_and_disables_tools(db):
    svc = AssistantService(db)
    result = await svc.handle_transcript(MEETING, "Navi, lembre-se de validar o contrato com o fornecedor.", "item_2")
    assert result["wake"] is True and result["kind"] == "note"
    assert result["note"] == "validar o contrato com o fornecedor"
    assert result["tools"] == []
    notes = await db.notes.find({"meeting_id": "test-meeting-1"}).to_list(10)
    assert len(notes) == 1 and notes[0]["origin"] == "wake"


async def test_question_disables_tools(db):
    svc = AssistantService(db)
    result = await svc.handle_transcript(MEETING, "Navi, o que você acha dessa proposta?", "item_3")
    assert result["kind"] == "question" and result["tools"] == []
    assert "o que você acha dessa proposta?" in result["instructions"]


async def test_note_like_request_enables_tool(db):
    svc = AssistantService(db)
    result = await svc.handle_transcript(MEETING, "Navi, dá um jeito de a gente não esquecer disso depois.", "item_4")
    assert result["kind"] == "question" and len(result["tools"]) == 1 and result["tools"][0]["name"] == "save_note"


async def test_pending_then_merge(db):
    svc = AssistantService(db)
    first = await svc.handle_transcript(MEETING, "Navi,", "item_5")
    assert first["kind"] == "pending" and first["pending_text"] == "Navi,"
    second = await svc.handle_transcript(MEETING, "quais tarefas ficaram definidas?", "item_6", pending_text=first["pending_text"])
    assert second["wake"] is True and second["kind"] == "question"
    assert "quais tarefas ficaram definidas" in second["request"]


async def test_pending_forced_without_request(db):
    svc = AssistantService(db)
    result = await svc.handle_transcript(MEETING, "", None, pending_text="Navi", force=True)
    assert result["wake"] is True and "não completou o pedido" in result["instructions"]


async def test_duplicate_notes_are_merged(db):
    svc = AssistantService(db)
    await svc.save_note("test-meeting-1", "validar o contrato com o fornecedor", origin="wake")
    again = await svc.save_note("test-meeting-1", "Validar o contrato com o fornecedor de telemetria antes da assinatura.", origin="tool")
    assert again["origin"] == "wake"  # devolveu a existente
    assert await db.notes.count_documents({"meeting_id": "test-meeting-1"}) == 1


async def test_dedupe_same_item_id(db):
    svc = AssistantService(db)
    await svc.handle_transcript(MEETING, "Texto repetido.", "item_7")
    await svc.handle_transcript(MEETING, "Texto repetido.", "item_7")
    assert await db.transcript_segments.count_documents({"dedupe_key": "openai:test-meeting-1:item_7"}) == 1
