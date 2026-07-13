import json
import logging
from base64 import b64decode, b64encode
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from webauthn import (
    generate_registration_options,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from ..database import get_db_async
from ..dependencies import current_user
from ..models import PasskeyCredential, PlexUser, Settings
from ..services.auth import hash_password
from ..services.totp import generate_secret, verify_code
from ..utils import async_get_or_404

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["security"])


class PasswordChangePayload(BaseModel):
    password: str


class TotpVerifyPayload(BaseModel):
    code: str


class WebAuthnRegisterOptionsPayload(BaseModel):
    user_id: int


class WebAuthnRegisterVerifyPayload(BaseModel):
    user_id: int
    credential: dict
    name: Optional[str] = "Passkey"


def _check_permission(user_id: int, current_user_dict: dict) -> None:
    """S'assure que l'appelant est soit admin, soit l'utilisateur concerné lui-même."""
    if not current_user_dict:
        raise HTTPException(status_code=401, detail="Non authentifié")
    if current_user_dict.get("role") == "admin":
        return
    if current_user_dict.get("id") == user_id:
        return
    raise HTTPException(status_code=403, detail="Accès interdit")


@router.post("/{id}/password")
async def change_password(
    id: int,
    payload: PasswordChangePayload,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    user = await async_get_or_404(db, PlexUser, id)
    user.password_hash = hash_password(payload.password)

    # Si c'est l'admin local, synchroniser aussi la table Settings
    s = (await db.execute(select(Settings))).scalars().first()
    if s and s.auth_username == user.plex_user_id:
        s.auth_password_hash = user.password_hash

    await db.commit()
    return {"success": True}


@router.post("/{id}/totp/setup")
async def totp_setup(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    user = await async_get_or_404(db, PlexUser, id)

    secret = generate_secret()
    user.totp_secret = secret
    user.totp_enabled = False  # pas encore activé (en attente de vérification)
    await db.commit()

    username_clean = user.plex_user_id.replace(" ", "")
    uri = f"otpauth://totp/Plexarr:{username_clean}?secret={secret}&issuer=Plexarr"
    return {"secret": secret, "uri": uri}


@router.post("/{id}/totp/enable")
async def totp_enable(
    id: int,
    payload: TotpVerifyPayload,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    user = await async_get_or_404(db, PlexUser, id)

    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP non configuré. Initialisez d'abord.")

    if not verify_code(user.totp_secret, payload.code):
        raise HTTPException(status_code=400, detail="Code de vérification incorrect.")

    user.totp_enabled = True

    # Si c'est l'admin local, synchroniser aussi la table Settings
    s = (await db.execute(select(Settings))).scalars().first()
    if s and s.auth_username == user.plex_user_id:
        s.totp_secret = user.totp_secret
        s.totp_enabled = True

    await db.commit()
    return {"success": True}


@router.delete("/{id}/totp")
async def totp_disable(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    user = await async_get_or_404(db, PlexUser, id)
    user.totp_secret = None
    user.totp_enabled = False

    # Si c'est l'admin local, synchroniser aussi la table Settings
    s = (await db.execute(select(Settings))).scalars().first()
    if s and s.auth_username == user.plex_user_id:
        s.totp_secret = None
        s.totp_enabled = False

    await db.commit()
    return {"success": True}


@router.post("/webauthn/register/options")
async def register_options(
    request: Request,
    payload: WebAuthnRegisterOptionsPayload,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(payload.user_id, curr)
    user = await async_get_or_404(db, PlexUser, payload.user_id)

    rp_id = request.url.hostname
    if rp_id == "127.0.0.1":
        rp_id = "localhost"

    # Récupérer les clés existantes pour les exclure
    existing_keys = (await db.execute(select(PasskeyCredential).filter(PasskeyCredential.user_id == user.id))).scalars().all()
    exclude_credentials = []
    for k in existing_keys:
        try:
            exclude_credentials.append(PublicKeyCredentialDescriptor(id=b64decode(k.credential_id)))
        except Exception:
            pass

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Plexarr",
        user_id=str(user.id).encode("utf-8"),
        user_name=user.plex_user_id,
        user_display_name=user.custom_name or user.display_name or user.plex_user_id,
        exclude_credentials=exclude_credentials if exclude_credentials else None,
    )

    request.session["reg_challenge"] = b64encode(options.challenge).decode("utf-8")
    request.session["reg_user_id"] = user.id

    return json.loads(options_to_json(options))


@router.post("/webauthn/register/verify")
async def register_verify(
    request: Request,
    payload: WebAuthnRegisterVerifyPayload,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(payload.user_id, curr)
    user = await async_get_or_404(db, PlexUser, payload.user_id)

    challenge = request.session.pop("reg_challenge", None)
    sess_user_id = request.session.pop("reg_user_id", None)

    if not challenge or sess_user_id != user.id:
        raise HTTPException(status_code=400, detail="Défi d'enregistrement expiré ou invalide.")

    rp_id = request.url.hostname
    if rp_id == "127.0.0.1":
        rp_id = "localhost"

    host = request.headers.get("x-forwarded-host", request.url.netloc)
    expected_origin = [f"https://{host}", f"http://{host}"]

    try:
        verification = verify_registration_response(
            credential=payload.credential,
            expected_challenge=b64decode(challenge),
            expected_origin=expected_origin,
            expected_rp_id=rp_id,
            require_user_verification=False,
        )
    except Exception as e:
        logger.error(f"WebAuthn verification failed: {e}")
        raise HTTPException(status_code=400, detail=f"Échec de la validation WebAuthn: {e}")

    # Enregistrer la clé
    cred_id_str = b64encode(verification.credential_id).decode("utf-8")
    db.add(
        PasskeyCredential(
            user_id=user.id,
            credential_id=cred_id_str,
            public_key=b64encode(verification.credential_public_key).decode("utf-8"),
            sign_count=verification.sign_count,
            name=payload.name or "Passkey",
        )
    )
    await db.commit()

    return {"success": True}


@router.get("/{id}/passkeys")
async def list_passkeys(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    keys = (await db.execute(select(PasskeyCredential).filter(PasskeyCredential.user_id == id))).scalars().all()
    return [
        {
            "credential_id": k.credential_id,
            "name": k.name,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in keys
    ]


@router.delete("/{id}/passkeys/{credential_id}")
async def delete_passkey(
    id: int,
    credential_id: str,
    db: AsyncSession = Depends(get_db_async),
    curr: dict = Depends(current_user),
):
    _check_permission(id, curr)
    key = (await db.execute(
        select(PasskeyCredential).filter(PasskeyCredential.user_id == id, PasskeyCredential.credential_id == credential_id)
    )).scalars().first()
    if not key:
        raise HTTPException(status_code=404, detail="Passkey introuvable.")

    await db.delete(key)
    await db.commit()
    return {"success": True}
