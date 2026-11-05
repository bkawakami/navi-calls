"""Reuniões: uma por bot da Recall.ai."""
from typing import Dict, List, Optional

from .base import BaseModel, utcnow

ACTIVE_STATUSES = {"created", "joining_call", "in_waiting_room", "in_call_not_recording", "in_call_recording", "recording_permission_allowed"}
FINAL_STATUSES = {"call_ended", "done", "fatal", "media_expired"}


class Meeting(BaseModel):
    collection_name = "meetings"

    async def ensure_indexes(self):
        await self.collection.create_index("bot_id")
        await self.collection.create_index([("created_at", -1)])

    async def find_by_bot_id(self, bot_id: str) -> Optional[Dict]:
        return await self.find_one({"bot_id": bot_id})

    async def find_recent(self, limit: int = 50) -> List[Dict]:
        return await self.find_many({}, sort=[("created_at", -1)], limit=limit)

    async def find_active(self) -> List[Dict]:
        return await self.find_many({"status": {"$in": list(ACTIVE_STATUSES)}}, limit=200)

    async def set_status(self, id: str, code: str, sub_code: Optional[str] = None, source: str = "webhook", at=None) -> bool:
        oid = self._oid(id)
        if not oid:
            return False
        entry = {"code": code, "sub_code": sub_code, "source": source, "at": at or utcnow()}
        update: Dict = {
            "$set": {"status": code, "status_sub_code": sub_code, "updated_at": utcnow()},
            "$push": {"status_history": entry},
        }
        if code in FINAL_STATUSES:
            update["$set"]["ended_at"] = utcnow()
        result = await self.collection.update_one({"_id": oid, "status": {"$ne": code}}, update)
        return result.modified_count > 0
