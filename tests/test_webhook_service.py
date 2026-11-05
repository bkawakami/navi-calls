import base64
import hashlib
import hmac
import time

import pytest

from app.services.webhook_service import WebhookSignatureError, verify_request, verify_svix_signature

SECRET_RAW = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
SECRET = f"whsec_{SECRET_RAW}"


def _sign(body: bytes, msg_id: str, ts: int) -> str:
    key = base64.b64decode(SECRET_RAW)
    sig = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(sig).decode()


def test_valid_signature_svix_headers():
    body = b'{"event":"bot.in_call_recording"}'
    ts = int(time.time())
    headers = {"svix-id": "msg_1", "svix-timestamp": str(ts), "svix-signature": _sign(body, "msg_1", ts)}
    assert verify_request(SECRET, body, headers) is True


def test_valid_signature_webhook_headers():
    body = b'{"event":"transcript.data"}'
    ts = int(time.time())
    headers = {"Webhook-Id": "msg_9", "Webhook-Timestamp": str(ts), "Webhook-Signature": _sign(body, "msg_9", ts)}
    assert verify_request(SECRET, body, headers) is True


def test_multiple_signatures_one_valid():
    body = b'{"a":1}'
    ts = int(time.time())
    sigs = "v1,AAAA " + _sign(body, "msg_2", ts)
    assert verify_svix_signature(SECRET, body, "msg_2", str(ts), sigs) is True


def test_invalid_signature():
    body = b'{"a":1}'
    ts = int(time.time())
    with pytest.raises(WebhookSignatureError):
        verify_svix_signature(SECRET, body, "msg_3", str(ts), "v1,bm90LXZhbGlk")


def test_old_timestamp_rejected():
    body = b'{"a":1}'
    ts = int(time.time()) - 3600
    with pytest.raises(WebhookSignatureError):
        verify_svix_signature(SECRET, body, "msg_4", str(ts), _sign(body, "msg_4", ts))


def test_missing_headers_rejected_when_secret_set():
    with pytest.raises(WebhookSignatureError):
        verify_request(SECRET, b"{}", {})


def test_no_secret_configured_allows_dev_mode():
    assert verify_request(None, b"{}", {}) is True
