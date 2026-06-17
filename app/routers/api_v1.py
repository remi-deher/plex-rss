from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaRequest, PlexUser, PollHistory, RequestStatus
from ..scheduler import poll_watchlists
from ..schemas import HealthOut, MetricsOut, PollHistoryOut, RequestOut, UserOut
from ..utils import get_or_404
from .api import get_metrics, get_poll_history, health_check, require_auth

router = APIRouter(prefix="/api/v1", tags=["v1"], dependencies=[Depends(require_auth)])

@router.get("/requests", response_model=List[RequestOut])
def list_requests_v1(
    status: Optional[str] = Query(None, description="Filter requests by status (pending, sent_to_arr, available, failed)"),
    media_type: Optional[str] = Query(None, description="Filter requests by media type (movie, show)"),
    limit: int = Query(200, description="Max number of items to return"),
    offset: int = Query(0, description="Number of items to skip"),
    db: Session = Depends(get_db)
):
    """Liste les demandes de médias avec filtres et pagination."""
    q = db.query(MediaRequest)
    if status:
        q = q.filter(MediaRequest.status == status)
    if media_type:
        q = q.filter(MediaRequest.media_type == media_type)
    return q.order_by(MediaRequest.requested_at.desc()).offset(offset).limit(limit).all()

@router.get("/requests/{request_id}", response_model=RequestOut)
def get_request_v1(request_id: int, db: Session = Depends(get_db)):
    """Récupère les détails d'une demande spécifique."""
    return get_or_404(db, MediaRequest, request_id, "Request not found")

@router.post("/requests/{request_id}/retry")
async def retry_request_v1(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en attente (pending) et force un poll immédiat."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in (RequestStatus.pending, RequestStatus.failed):
        raise HTTPException(status_code=400, detail="Only failed or pending requests can be retried")
    req.status = RequestStatus.pending
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}

@router.delete("/requests/{request_id}")
def delete_request_v1(request_id: int, db: Session = Depends(get_db)):
    """Supprime définitivement une demande."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    db.delete(req)
    db.commit()
    return {"status": "deleted"}

@router.get("/users", response_model=List[UserOut])
def list_users_v1(db: Session = Depends(get_db)):
    """Liste tous les utilisateurs Plex enregistrés."""
    return db.query(PlexUser).all()

@router.get("/health", response_model=HealthOut)
async def health_check_v1(db: Session = Depends(get_db)):
    """Retourne l'état de santé détaillé des services connectés."""
    return await health_check(db)

@router.get("/metrics", response_model=MetricsOut)
def get_metrics_v1(db: Session = Depends(get_db)):
    """Retourne les métriques courantes de l'application et de la base de données."""
    return get_metrics(db)

@router.get("/poll-history", response_model=List[PollHistoryOut])
def get_poll_history_v1(limit: int = 50, job: Optional[str] = None, db: Session = Depends(get_db)):
    """Retourne l'historique des exécutions du scheduler."""
    return get_poll_history(limit, job, db)
