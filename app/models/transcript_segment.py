"""Segmentos de transcrição (fala finalizada) de várias fontes: recall, openai, navi."""
from typing import Dict, List, Optional

from .base import BaseModel


class TranscriptSegment(BaseModel):
    collection_name = "transcript_segments"

    async def ensure_indexes(self):
        await self.collection.create_index([("meeting_id", 1), ("seq", 1)])
        await self.collection.create_index([("meeting_id", 1), ("source", 1)])
        await self.collection.create_index("dedupe_key", unique=True, sparse=True)

    async def next_seq(self, meeting_id: str) -> int:
        doc = await self.collection.find_one({"meeting_id": meeting_id}, sort=[("seq", -1)], projection={"seq": 1})
        return (doc["seq"] + 1) if doc and "seq" in doc else 1

    async def find_by_meeting(self, meeting_id: str, source: Optional[str] = None, after_seq: int = 0, limit: int = 2000) -> List[Dict]:
        query: Dict = {"meeting_id": meeting_id, "seq": {"$gt": after_seq}}
        if source:
            query["source"] = source
        return await self.find_many(query, sort=[("seq", 1)], limit=limit)

    async def count_by_source(self, meeting_id: str) -> Dict[str, int]:
        pipeline = [{"$match": {"meeting_id": meeting_id}}, {"$group": {"_id": "$source", "n": {"$sum": 1}}}]
        out = {}
        async for row in self.collection.aggregate(pipeline):
            out[row["_id"]] = row["n"]
        return out

    async def create_dedup(self, data: Dict) -> Optional[str]:
        """Insere ignorando duplicatas (webhooks podem ser reenviados)."""
        from pymongo.errors import DuplicateKeyError

        try:
            return await self.create(data)
        except DuplicateKeyError:
            return None
