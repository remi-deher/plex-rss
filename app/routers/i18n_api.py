"""Catalogue de traductions servi au client."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import get_current_plex_user, require_auth
from ..i18n import SUPPORTED_LOCALES, catalog, normalize_locale
from ..models import PlexUser, Settings

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

@router.get("/i18n/catalog", dependencies=[Depends(require_auth)])
async def i18n_catalog(
    request: Request, db: AsyncSession = Depends(get_db_async), user: PlexUser | None = Depends(get_current_plex_user)
):
    settings = (await db.execute(select(Settings))).scalars().first()
    requested = request.query_params.get("locale")
    locale = normalize_locale(
        requested or (user.locale if user else None) or (settings.default_locale if settings else None)
    )
    return {"locale": locale, "supported": sorted(SUPPORTED_LOCALES), "messages": catalog(locale)}
