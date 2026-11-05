"""Notas da reunião ("Navi, lembre-se de ...")."""
from typing import Dict, List

from .base import BaseModel


class Note(BaseModel):
    collection_name = "notes"

    async def ensure_indexes(self):
        await self.collection.create_index([("meeting_id", 1), ("created_at", 1)])

    async def find_by_meeting(self, meeting_id: str) -> List[Dict]:
        return await self.find_many({"meeting_id": meeting_id}, sort=[("created_at", 1)])
