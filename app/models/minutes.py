"""Ata gerada ao final da reunião (resumo, decisões, pendências, tarefas)."""
from typing import Dict, Optional

from .base import BaseModel


class Minutes(BaseModel):
    collection_name = "minutes"

    async def ensure_indexes(self):
        await self.collection.create_index([("meeting_id", 1), ("created_at", -1)])

    async def find_latest(self, meeting_id: str) -> Optional[Dict]:
        docs = await self.find_many({"meeting_id": meeting_id}, sort=[("created_at", -1)], limit=1)
        return docs[0] if docs else None
