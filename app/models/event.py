"""Eventos operacionais da reunião (chamados, respostas, conexões, webhooks, erros)."""
from typing import Dict, List, Optional

from .base import BaseModel


class Event(BaseModel):
    collection_name = "events"

    async def ensure_indexes(self):
        await self.collection.create_index([("meeting_id", 1), ("created_at", 1)])

    async def find_by_meeting(self, meeting_id: str, types: Optional[List[str]] = None, limit: int = 500) -> List[Dict]:
        query: Dict = {"meeting_id": meeting_id}
        if types:
            query["type"] = {"$in": types}
        return await self.find_many(query, sort=[("created_at", 1)], limit=limit)
