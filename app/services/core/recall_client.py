"""Cliente HTTP assíncrono da Recall.ai (API v1). A chave fica apenas no backend."""
import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RecallError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class RecallConfigError(RecallError):
    pass


class RecallClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.RECALL_API_KEY
        self.base_url = (base_url or settings.recall_base_url).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RecallConfigError("RECALL_API_KEY não configurada")
        return {"Authorization": f"Token {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"}

    async def _request(self, method: str, path: str, json: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=self._headers(), json=json, params=params)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            logger.error("Recall %s %s -> %s %s", method, path, resp.status_code, body)
            raise RecallError(f"Recall.ai respondeu {resp.status_code}", status=resp.status_code, body=body)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # === Bots ===

    async def create_bot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/api/v1/bot/", json=payload)

    async def get_bot(self, bot_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/v1/bot/{bot_id}/")

    async def leave_call(self, bot_id: str) -> Any:
        return await self._request("POST", f"/api/v1/bot/{bot_id}/leave_call/")

    async def delete_bot(self, bot_id: str) -> Any:
        return await self._request("DELETE", f"/api/v1/bot/{bot_id}/")

    async def update_output_media(self, bot_id: str, payload: Dict[str, Any]) -> Any:
        return await self._request("POST", f"/api/v1/bot/{bot_id}/output_media/", json=payload)

    async def stop_output_media(self, bot_id: str) -> Any:
        return await self._request("DELETE", f"/api/v1/bot/{bot_id}/output_media/")

    # === Transcrições ===

    async def get_transcript(self, transcript_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/v1/transcript/{transcript_id}/")

    async def download_json(self, url: str) -> Any:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()


def get_recall_client() -> RecallClient:
    return RecallClient()
