"""Tests unitaires pour app/services/brevo_email.py."""

import pytest

from app.services import brevo_email


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response: _Resp, captured: dict):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured["url"] = url
        self._captured["json"] = json
        self._captured["headers"] = headers
        return self._response


@pytest.mark.asyncio
async def test_send_transactional_email_success_returns_message_id(monkeypatch):
    captured: dict = {}
    resp = _Resp(201, {"messageId": "<msg-1@brevo>"})
    monkeypatch.setattr(brevo_email.httpx, "AsyncClient", lambda **kw: _Client(resp, captured))

    message_id = await brevo_email.send_transactional_email(
        api_key="key-1",
        sender_email="from@example.com",
        sender_name="Plexarr",
        to_email="dest@example.com",
        subject="Hello",
        html_content="<p>Hi</p>",
    )

    assert message_id == "<msg-1@brevo>"
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["api-key"] == "key-1"
    assert captured["json"]["sender"] == {"email": "from@example.com", "name": "Plexarr"}
    assert captured["json"]["to"] == [{"email": "dest@example.com"}]
    assert captured["json"]["subject"] == "Hello"
    assert captured["json"]["htmlContent"] == "<p>Hi</p>"


@pytest.mark.asyncio
async def test_send_transactional_email_without_sender_name_omits_field(monkeypatch):
    captured: dict = {}
    resp = _Resp(201, {"messageId": "id"})
    monkeypatch.setattr(brevo_email.httpx, "AsyncClient", lambda **kw: _Client(resp, captured))

    await brevo_email.send_transactional_email(
        api_key="key-1", sender_email="from@example.com", sender_name=None,
        to_email="dest@example.com", subject="Hi", html_content="<p>x</p>",
    )

    assert captured["json"]["sender"] == {"email": "from@example.com"}


@pytest.mark.asyncio
async def test_send_transactional_email_raises_on_error_response(monkeypatch):
    captured: dict = {}
    resp = _Resp(401, {"code": "unauthorized", "message": "Key not found"})
    monkeypatch.setattr(brevo_email.httpx, "AsyncClient", lambda **kw: _Client(resp, captured))

    with pytest.raises(RuntimeError, match="401"):
        await brevo_email.send_transactional_email(
            api_key="bad-key", sender_email="from@example.com", sender_name=None,
            to_email="dest@example.com", subject="Hi", html_content="<p>x</p>",
        )
