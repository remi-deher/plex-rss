from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import get_db_async
from ..dependencies import require_api_scope, require_auth
from ..models import MediaRequest, PlexUser, PollHistory, RequestStatus
from ..scheduler import poll_watchlists
from ..schemas import HealthOut, MetricsOut, PollHistoryOut, RequestOut, UserOut
from ..utils import async_get_or_404
from .metrics_api import get_metrics, get_poll_history, health_check

router = APIRouter(prefix="/api/v1", tags=["v1"], dependencies=[Depends(require_auth)])


@router.get("/requests", response_model=List[RequestOut], dependencies=[Depends(require_api_scope("requests:read"))])
async def list_requests_v1(
    status: Optional[str] = Query(
        None, description="Filter requests by status (pending, sent_to_arr, available, failed)"
    ),
    media_type: Optional[str] = Query(None, description="Filter requests by media type (movie, show)"),
    limit: int = Query(200, description="Max number of items to return"),
    offset: int = Query(0, description="Number of items to skip"),
    db: AsyncSession = Depends(get_db_async),
):
    """Liste les demandes de médias avec filtres et pagination."""
    q = select(MediaRequest)
    if status:
        q = q.filter(MediaRequest.status == status)
    if media_type:
        q = q.filter(MediaRequest.media_type == media_type)
    return (await db.execute(q.order_by(MediaRequest.requested_at.desc()).offset(offset).limit(limit))).scalars().all()


@router.get(
    "/requests/{request_id}", response_model=RequestOut, dependencies=[Depends(require_api_scope("requests:read"))]
)
async def get_request_v1(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Récupère les détails d'une demande spécifique."""
    return await async_get_or_404(db, MediaRequest, request_id, "Request not found")


@router.post("/requests/{request_id}/retry", dependencies=[Depends(require_api_scope("requests:write"))])
async def retry_request_v1(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Repasse une demande en attente (pending) et force un poll immédiat."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in (RequestStatus.pending, RequestStatus.failed):
        raise HTTPException(status_code=400, detail="Only failed or pending requests can be retried")
    req.status = RequestStatus.pending
    await db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.delete("/requests/{request_id}", dependencies=[Depends(require_api_scope("requests:write"))])
async def delete_request_v1(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Supprime définitivement une demande."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    await db.delete(req)
    await db.commit()
    return {"status": "deleted"}


@router.get("/users", response_model=List[UserOut], dependencies=[Depends(require_api_scope("users:read"))])
async def list_users_v1(db: AsyncSession = Depends(get_db_async)):
    """Liste tous les utilisateurs Plex enregistrés."""
    return (await db.execute(select(PlexUser))).scalars().all()


@router.get("/health", response_model=HealthOut, dependencies=[Depends(require_api_scope("system:read"))])
async def health_check_v1(db: AsyncSession = Depends(get_db_async)):
    """Retourne l'état de santé détaillé des services connectés."""
    return await health_check(db)


@router.get("/metrics", response_model=MetricsOut, dependencies=[Depends(require_api_scope("system:read"))])
async def get_metrics_v1(db: AsyncSession = Depends(get_db_async)):
    """Retourne les métriques courantes de l'application et de la base de données."""
    return await get_metrics(db)


@router.get(
    "/poll-history", response_model=List[PollHistoryOut], dependencies=[Depends(require_api_scope("system:read"))]
)
async def get_poll_history_v1(limit: int = 50, job: Optional[str] = None, db: AsyncSession = Depends(get_db_async)):
    """Retourne l'historique des exécutions du scheduler."""
    return await get_poll_history(limit, job, db)
