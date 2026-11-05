"""Model base com helpers de serialização e CRUD genérico (MongoDB/Motor)."""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bson import ObjectId


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseModel:
    collection_name: str = ""

    def __init__(self, db):
        self.db = db
        self.collection = db[self.collection_name]

    # === Helpers ===

    @staticmethod
    def _serialize(doc: Optional[Dict]) -> Optional[Dict]:
        """Converte _id para id string."""
        if not doc:
            return None
        doc = dict(doc)
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    @staticmethod
    def _oid(id: str) -> Optional[ObjectId]:
        try:
            return ObjectId(id)
        except Exception:
            return None

    # === CRUD ===

    async def find_by_id(self, id: str) -> Optional[Dict]:
        oid = self._oid(id)
        if not oid:
            return None
        return self._serialize(await self.collection.find_one({"_id": oid}))

    async def find_one(self, query: Dict) -> Optional[Dict]:
        return self._serialize(await self.collection.find_one(query))

    async def find_many(
        self,
        query: Optional[Dict] = None,
        sort: Optional[List[tuple]] = None,
        limit: int = 500,
        skip: int = 0,
    ) -> List[Dict]:
        cursor = self.collection.find(query or {})
        if sort:
            cursor = cursor.sort(sort)
        docs = await cursor.skip(skip).limit(limit).to_list(limit)
        return [self._serialize(d) for d in docs]

    async def count(self, query: Optional[Dict] = None) -> int:
        return await self.collection.count_documents(query or {})

    async def create(self, data: Dict) -> str:
        now = utcnow()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        result = await self.collection.insert_one(data)
        return str(result.inserted_id)

    async def update(self, id: str, data: Dict) -> bool:
        oid = self._oid(id)
        if not oid:
            return False
        data["updated_at"] = utcnow()
        result = await self.collection.update_one({"_id": oid}, {"$set": data})
        return result.matched_count > 0

    async def delete(self, id: str) -> bool:
        oid = self._oid(id)
        if not oid:
            return False
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0
