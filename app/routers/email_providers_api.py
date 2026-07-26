"""CRUD des fournisseurs d'envoi d'email (SMTP classique, SMTP+OAuth2 Microsoft, Brevo).

Miroir de /api/arr-instances (voir arr_instances_api.py) : liste de fournisseurs, chacun
activable/désactivable indépendamment, essayés par ordre de priorité avec repli
automatique en cas d'échec (voir app/services/email_providers.py).
"""

import logging
import secrets
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import get_settings_or_404, require_admin
from ..models import EmailProvider, Settings
from ..services import email_providers, microsoft_oauth
from ..utils import async_get_or_404, safe_error_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["email-providers"], dependencies=[Depends(require_admin)])

_MASKED_SECRET_FIELDS = ("smtp_password", "oauth_client_secret")
_MASK = "••••••••"


class EmailProviderCreate(BaseModel):
    name: str
    provider_type: str  # "smtp" | "smtp_oauth2" | "brevo"
    enabled: Optional[bool] = True
    priority: Optional[int] = 0
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_tls: Optional[bool] = True
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    oauth_tenant: Optional[str] = "consumers"
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_mailbox: Optional[str] = None
    brevo_api_key: Optional[str] = None


class ReorderBody(BaseModel):
    order: list[int]


class TestProviderBody(BaseModel):
    recipient: str


def _serialize(provider: EmailProvider) -> dict:
    d = {c.name: getattr(provider, c.name) for c in provider.__table__.columns}
    d["oauth_connected"] = bool(provider.oauth_refresh_token)
    for field in _MASKED_SECRET_FIELDS:
        if d.get(field):
            d[field] = _MASK
    d.pop("oauth_refresh_token", None)
    d.pop("oauth_access_token", None)
    if d.get("brevo_api_key"):
        d["brevo_api_key"] = _MASK
    return d


@router.get("/email-providers")
async def list_email_providers(db: AsyncSession = Depends(get_db_async)):
    return [_serialize(p) for p in await email_providers.list_providers(db)]


@router.post("/email-providers")
async def create_email_provider(data: EmailProviderCreate, db: AsyncSession = Depends(get_db_async)):
    provider = EmailProvider(**data.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return _serialize(provider)


@router.put("/email-providers/{provider_id}")
async def update_email_provider(provider_id: int, data: EmailProviderCreate, db: AsyncSession = Depends(get_db_async)):
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    payload = data.model_dump()
    for key, val in payload.items():
        if key in _MASKED_SECRET_FIELDS and val == _MASK:
            continue
        setattr(provider, key, val)
    await db.commit()
    await db.refresh(provider)
    return _serialize(provider)


@router.delete("/email-providers/{provider_id}")
async def delete_email_provider(provider_id: int, db: AsyncSession = Depends(get_db_async)):
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    await db.delete(provider)
    await db.commit()
    return {"status": "deleted"}


@router.patch("/email-providers/{provider_id}/toggle")
async def toggle_email_provider(provider_id: int, db: AsyncSession = Depends(get_db_async)):
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    provider.enabled = not provider.enabled
    await db.commit()
    return {"id": provider.id, "enabled": provider.enabled}


@router.post("/email-providers/reorder")
async def reorder_email_providers(body: ReorderBody, db: AsyncSession = Depends(get_db_async)):
    """Réordonne la liste (glisser-déposer côté UI) : `order` = liste d'ids dans le nouvel ordre."""
    providers = {p.id: p for p in await email_providers.list_providers(db)}
    for index, provider_id in enumerate(body.order):
        if provider_id in providers:
            providers[provider_id].priority = index
    await db.commit()
    return {"status": "ok"}


@router.post("/test/email-provider/{provider_id}")
async def test_email_provider(
    provider_id: int, body: TestProviderBody, db: AsyncSession = Depends(get_db_async), s: Settings = Depends(get_settings_or_404)
):
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    ok, msg = await email_providers.test_provider(provider, s.smtp_from, body.recipient)
    return {"success": ok, "message": msg}


def _smtp_oauth_redirect_uri(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}/api/email-providers/smtp-oauth/callback"


@router.get("/email-providers/{provider_id}/smtp-oauth/authorize")
async def email_provider_oauth_authorize(provider_id: int, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Redirige vers l'écran de consentement Microsoft pour CE fournisseur (flux PKCE)."""
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    if not provider.oauth_client_id:
        raise HTTPException(status_code=400, detail="Renseignez d'abord le Client ID Microsoft de ce fournisseur.")

    verifier, challenge = microsoft_oauth.generate_pkce_pair()
    state = secrets.token_urlsafe(24)
    request.session["email_oauth_state"] = state
    request.session["email_oauth_verifier"] = verifier
    request.session["email_oauth_provider_id"] = provider.id

    url = microsoft_oauth.build_authorize_url(provider, _smtp_oauth_redirect_uri(request), state, challenge)
    return RedirectResponse(url, status_code=302)


@router.get("/email-providers/smtp-oauth/callback")
async def email_provider_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db_async),
):
    expected_state = request.session.pop("email_oauth_state", None)
    verifier = request.session.pop("email_oauth_verifier", None)
    provider_id = request.session.pop("email_oauth_provider_id", None)

    def _redirect_with(status: str, message: str = "") -> RedirectResponse:
        params = {"email_oauth": status}
        if message:
            params["msg"] = message
        return RedirectResponse(f"/settings?tab=notifications-channels&{urllib.parse.urlencode(params)}", status_code=302)

    if error:
        logger.warning("Email provider OAuth Microsoft: refus/erreur (%s): %s", error, error_description)
        return _redirect_with("error", error_description or error)
    if not code or not state or not verifier or not provider_id or state != expected_state:
        return _redirect_with("error", "Requête OAuth invalide ou expirée, réessayez.")

    provider = (await db.execute(select(EmailProvider).filter(EmailProvider.id == provider_id))).scalars().first()
    if not provider:
        return _redirect_with("error", "Fournisseur introuvable (supprimé entre-temps ?)")

    try:
        tokens = await microsoft_oauth.exchange_code(provider, code, verifier, _smtp_oauth_redirect_uri(request))
        await microsoft_oauth.store_tokens(provider, tokens)
    except Exception as e:
        logger.exception("Email provider OAuth Microsoft: échec de l'échange du code")
        return _redirect_with("error", safe_error_message(e))

    return _redirect_with("success")


@router.post("/email-providers/{provider_id}/smtp-oauth/disconnect")
async def email_provider_oauth_disconnect(provider_id: int, db: AsyncSession = Depends(get_db_async)):
    provider = await async_get_or_404(db, EmailProvider, provider_id, "Fournisseur introuvable")
    provider.oauth_refresh_token = None
    provider.oauth_access_token = None
    provider.oauth_token_expires_at = None
    await db.commit()
    return {"status": "ok"}
