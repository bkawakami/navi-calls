"""Cria uma reunião "simulada" (sem bot da Recall) para testar a página da assistente localmente.

Uso: venv/bin/python scripts/dev_fake_meeting.py [título]
Imprime a URL da página da assistente (abra em um navegador com microfone ou use scripts/e2e_assistant.mjs).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.models import Meeting, ensure_indexes
from app.routes.shared.auth import make_page_token


async def main():
    title = " ".join(sys.argv[1:]) or "Reunião simulada (dev)"
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    await ensure_indexes(db)
    now = datetime.now(timezone.utc)
    meeting_id = await Meeting(db).create({
        "meeting_url": "https://teams.microsoft.com/l/meetup-join/simulada",
        "title": title,
        "platform": "microsoft_teams",
        "bot_name": settings.RECALL_BOT_NAME,
        "bot_id": None,
        "status": "in_call_recording",
        "status_history": [{"code": "in_call_recording", "sub_code": "simulated", "source": "dev", "at": now}],
        "in_call_at": now,
        "simulated": True,
    })
    print(f"meeting_id={meeting_id}")
    print(f"painel:     {settings.BASE_URL}/meetings/{meeting_id}")
    print(f"assistente: {settings.BASE_URL}/assistant/{meeting_id}?token={make_page_token(meeting_id)}&debug=1")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
