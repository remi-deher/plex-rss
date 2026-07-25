"""Flux OAuth2 "authorization code + PKCE" avec l'identité Microsoft, pour l'envoi
SMTP via un compte outlook.com/hotmail.fr (authentification basique désactivée par
Microsoft — voir https://learn.microsoft.com/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth).

Le client_secret est optionnel : une app registration Azure AD peut être déclarée
"public client" (mobile/desktop), auquel cas seul PKCE protège l'échange du code.
S'il est fourni, il est envoyé en plus de PKCE (client confidentiel classique).

Opère sur un EmailProvider (provider_type="smtp_oauth2") : plusieurs comptes
Microsoft peuvent être connectés en parallèle (voir app/services/email_providers.py).
"""

import base64
import hashlib
import logging
import secrets
import urllib.parse
from datetime import timedelta

import httpx

from ..database import AsyncSessionLocal
from ..models import EmailProvider
from ..utils import now_utc_naive

logger = logging.getLogger(__name__)

# Scope minimal pour l'envoi SMTP + un refresh token durable. "openid" n'est pas
# nécessaire : on n'a besoin d'aucune information d'identité, seulement du jeton
# d'accès SMTP.Send.
_SCOPE = "https://outlook.office365.com/SMTP.Send offline_access"

# Marge appliquée avant l'expiration réelle du jeton, pour ne jamais tenter d'envoyer
# un email avec un access_token qui expire pendant la requête SMTP elle-même.
_EXPIRY_SAFETY_MARGIN_SECONDS = 60


def _authority(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant or 'consumers'}"


def generate_pkce_pair() -> tuple[str, str]:
    """Retourne (code_verifier, code_challenge) pour le flux authorization code + PKCE."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(provider: EmailProvider, redirect_uri: str, state: str, code_challenge: str) -> str:
    if not provider.oauth_client_id:
        raise ValueError("oauth_client_id n'est pas configuré")
    params = {
        "client_id": provider.oauth_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": _SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Force le compte à réautoriser offline_access explicitement — sans ça,
        # Microsoft peut réutiliser un consentement précédent sans renvoyer de
        # refresh_token si le scope n'a pas changé depuis.
        "prompt": "consent",
    }
    return f"{_authority(provider.oauth_tenant)}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"


async def _token_request(provider: EmailProvider, data: dict) -> dict:
    payload = {"client_id": provider.oauth_client_id, **data}
    if provider.oauth_client_secret:
        payload["client_secret"] = provider.oauth_client_secret
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_authority(provider.oauth_tenant)}/oauth2/v2.0/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        detail = resp.json().get("error_description", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise RuntimeError(f"Echec de la requête OAuth Microsoft ({resp.status_code}): {detail}")
    return resp.json()


async def exchange_code(provider: EmailProvider, code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Échange le code d'autorisation contre un access_token + refresh_token."""
    return await _token_request(
        provider,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "scope": _SCOPE,
        },
    )


async def _refresh(provider: EmailProvider, refresh_token: str) -> dict:
    return await _token_request(
        provider,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": _SCOPE,
        },
    )


async def store_tokens(provider: EmailProvider, tokens: dict) -> None:
    """Persiste les jetons reçus (échange initial ou refresh) en base et sur l'objet en mémoire.

    Ouvre sa propre session : appelé aussi bien depuis une route (avec sa propre
    session déjà ouverte, mais dont le commit reste sous contrôle de l'appelant)
    que depuis l'envoi d'un email (aucune session ambiante disponible à cet endroit
    de la pile — voir email_providers.send_via_provider).
    """
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token") or provider.oauth_refresh_token
    expires_in = int(tokens.get("expires_in") or 0)
    expires_at = now_utc_naive() + timedelta(seconds=expires_in) if expires_in else None

    provider.oauth_access_token = access_token
    provider.oauth_refresh_token = refresh_token
    provider.oauth_token_expires_at = expires_at

    async with AsyncSessionLocal() as db:
        row = await db.get(EmailProvider, provider.id)
        if row:
            row.oauth_access_token = access_token
            row.oauth_refresh_token = refresh_token
            row.oauth_token_expires_at = expires_at
            await db.commit()


async def get_valid_access_token(provider: EmailProvider) -> str:
    """Retourne un access_token valide, en le rafraîchissant si besoin.

    Best-effort de cache : si `provider` n'est pas encore expiré (avec marge), on
    évite un aller-retour réseau. Sinon, on rafraîchit via le refresh_token et on
    persiste le résultat pour les envois suivants.
    """
    if not provider.oauth_refresh_token:
        raise RuntimeError(
            f"Aucun compte Microsoft connecté pour le fournisseur d'email '{provider.name}' — "
            "reconnectez-vous depuis Paramètres > Notifications."
        )

    expires_at = provider.oauth_token_expires_at
    if (
        provider.oauth_access_token
        and expires_at
        and expires_at > now_utc_naive() + timedelta(seconds=_EXPIRY_SAFETY_MARGIN_SECONDS)
    ):
        return provider.oauth_access_token

    logger.debug("Rafraîchissement du jeton OAuth Microsoft (fournisseur '%s')", provider.name)
    tokens = await _refresh(provider, provider.oauth_refresh_token)
    await store_tokens(provider, tokens)
    return provider.oauth_access_token
