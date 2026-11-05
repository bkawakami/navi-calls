"""Proteções de acesso.

- Painel/APIs do painel: HTTP Basic opcional (DASHBOARD_PASSWORD).
- Página da assistente e suas APIs: token assinado (HMAC) por reunião.
- Webhooks em tempo real da Recall: segredo na URL.
"""
import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_basic = HTTPBasic(auto_error=False)


async def require_dashboard(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)):
    """Exige Basic Auth no painel quando DASHBOARD_PASSWORD estiver definido."""
    if not settings.DASHBOARD_PASSWORD:
        return True
    ok = (
        credentials is not None
        and secrets.compare_digest(credentials.username, settings.DASHBOARD_USER)
        and secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
    )
    if not ok:
        raise HTTPException(401, "Não autenticado", headers={"WWW-Authenticate": "Basic"})
    return True


def make_page_token(meeting_id: str) -> str:
    """Token determinístico por reunião para a página da assistente (Output Media)."""
    return hmac.new(settings.SECRET_KEY.encode(), f"assistant:{meeting_id}".encode(), hashlib.sha256).hexdigest()[:40]


def verify_page_token(meeting_id: str, token: Optional[str]) -> bool:
    return bool(token) and hmac.compare_digest(make_page_token(meeting_id), token)


async def require_page_token(
    meeting_id: str,
    token: Optional[str] = Query(None),
    x_navi_token: Optional[str] = Header(None),
):
    """A página da assistente envia o token por query (?token=) ou header X-Navi-Token."""
    if not verify_page_token(meeting_id, x_navi_token or token):
        raise HTTPException(403, "Token da assistente inválido")
    return True


async def require_realtime_secret(request: Request, secret: Optional[str] = Query(None)):
    """Webhooks em tempo real da Recall não são assinados: validamos um segredo na URL."""
    expected = settings.RECALL_REALTIME_SECRET
    if not expected:
        return True  # sem segredo configurado (dev); documentado como inseguro
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(403, "Segredo inválido")
    return True
