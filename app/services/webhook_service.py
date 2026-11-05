"""Verificação de assinatura dos webhooks da Recall.ai.

A Recall assina com o esquema Svix: HMAC-SHA256(base64decode(secret sem "whsec_"), f"{id}.{timestamp}.{body}").
- Contas criadas a partir de 2025-12-15 e webhooks em tempo real: cabeçalhos `webhook-id`, `webhook-timestamp`,
  `webhook-signature`, assinados com o "Workspace Secret".
- Contas antigas (webhooks do dashboard): cabeçalhos `svix-id`, `svix-timestamp`, `svix-signature`, assinados
  com o segredo do endpoint.
"""
import base64
import hashlib
import hmac
import time
from typing import Mapping, Optional, Tuple

TOLERANCE_SECONDS = 5 * 60


class WebhookSignatureError(Exception):
    pass


def extract_signature_headers(headers: Mapping[str, str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Aceita os dois conjuntos de cabeçalhos (webhook-* e svix-*)."""
    lower = {k.lower(): v for k, v in headers.items()}
    msg_id = lower.get("webhook-id") or lower.get("svix-id")
    ts = lower.get("webhook-timestamp") or lower.get("svix-timestamp")
    sig = lower.get("webhook-signature") or lower.get("svix-signature")
    return msg_id, ts, sig


def has_signature_headers(headers: Mapping[str, str]) -> bool:
    msg_id, ts, sig = extract_signature_headers(headers)
    return bool(msg_id and ts and sig)


def verify_svix_signature(
    secret: Optional[str],
    body: bytes,
    msg_id: Optional[str],
    timestamp: Optional[str],
    signature: Optional[str],
    now: Optional[float] = None,
) -> bool:
    """Valida a assinatura. Sem segredo configurado, retorna True (modo dev; documentado no README)."""
    if not secret:
        return True
    if not (msg_id and timestamp and signature):
        raise WebhookSignatureError("Cabeçalhos de assinatura ausentes")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookSignatureError("timestamp inválido") from exc
    current = now if now is not None else time.time()
    if abs(current - ts) > TOLERANCE_SECONDS:
        raise WebhookSignatureError("timestamp fora da tolerância")
    raw_secret = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except Exception as exc:  # noqa: BLE001
        raise WebhookSignatureError("segredo inválido (esperado whsec_<base64>)") from exc
    to_sign = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()
    for candidate in signature.split(" "):
        if "," not in candidate:
            continue
        version, sig = candidate.split(",", 1)
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    raise WebhookSignatureError("assinatura não confere")


def verify_request(secret: Optional[str], body: bytes, headers: Mapping[str, str]) -> bool:
    msg_id, ts, sig = extract_signature_headers(headers)
    return verify_svix_signature(secret, body, msg_id, ts, sig)
