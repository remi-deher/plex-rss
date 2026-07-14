import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import current_user, require_admin, require_auth
from ..models import LibraryItem, MediaIssue, MediaRequest
from ..services import radarr, sonarr
from ..utils import async_get_or_404, now_utc_naive
from .arr_api import _resolve_arr_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["issues"], dependencies=[Depends(require_auth)])


class MediaIssueCreate(BaseModel):
    library_id: Optional[int] = None
    request_id: Optional[int] = None
    issue_type: str = Field(..., min_length=2, max_length=50)
    message: Optional[str] = Field(default=None, max_length=2000)


class MediaIssueUpdate(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = Field(default=None, max_length=2000)


def _serialize_issue(issue: MediaIssue) -> dict:
    return {
        "id": issue.id,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        "status": issue.status,
        "issue_type": issue.issue_type,
        "message": issue.message,
        "reporter_plex_user_id": issue.reporter_plex_user_id,
        "reporter_name": issue.reporter_name,
        "library_item_id": issue.library_item_id,
        "request_id": issue.request_id,
        "title": issue.title,
        "media_type": issue.media_type,
        "admin_note": issue.admin_note,
    }


@router.post("/media/issues")
async def create_media_issue(
    body: MediaIssueCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
):
    if not body.library_id and not body.request_id:
        raise HTTPException(400, "library_id or request_id is required")
    library_item = (await db.execute(select(LibraryItem).filter(LibraryItem.id == body.library_id))).scalars().first() if body.library_id else None
    media_request = (
        (await db.execute(select(MediaRequest).filter(MediaRequest.id == body.request_id))).scalars().first() if body.request_id else None
    )
    if body.library_id and not library_item:
        raise HTTPException(404, "Library item not found")
    if body.request_id and not media_request:
        raise HTTPException(404, "Request not found")

    media_obj = library_item or media_request
    user = current_user(request, db)
    issue = MediaIssue(
        issue_type=body.issue_type.strip(),
        message=(body.message or "").strip() or None,
        reporter_plex_user_id=user.get("plex_user_id") if user else None,
        reporter_name=user.get("username") if user else None,
        library_item_id=library_item.id if library_item else None,
        request_id=media_request.id if media_request else None,
        title=media_obj.title,
        media_type=media_obj.media_type,
        tmdb_id=getattr(media_obj, "tmdb_id", None),
        tvdb_id=getattr(media_obj, "tvdb_id", None),
        imdb_id=getattr(media_obj, "imdb_id", None),
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.get("/media/issues", dependencies=[Depends(require_admin)])
async def list_media_issues(status: Optional[str] = "open", db: AsyncSession = Depends(get_db_async)):
    q = select(MediaIssue)
    if status:
        q = q.filter(MediaIssue.status == status)
    return [_serialize_issue(issue) for issue in (await db.execute(q.order_by(MediaIssue.created_at.desc()).limit(200))).scalars().all()]


@router.patch("/media/issues/{issue_id}", dependencies=[Depends(require_admin)])
async def update_media_issue(issue_id: int, body: MediaIssueUpdate, db: AsyncSession = Depends(get_db_async)):
    issue = await async_get_or_404(db, MediaIssue, issue_id, "Issue not found")
    if body.status is not None:
        if body.status not in {"open", "investigating", "resolved", "closed"}:
            raise HTTPException(400, "Invalid issue status")
        issue.status = body.status
    if body.admin_note is not None:
        issue.admin_note = body.admin_note
    issue.updated_at = now_utc_naive()
    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.post("/media/issues/{issue_id}/retry", dependencies=[Depends(require_admin)])
async def retry_issue_media_search(issue_id: int, db: AsyncSession = Depends(get_db_async)):
    issue = await async_get_or_404(db, MediaIssue, issue_id, "Issue not found")
    arr_id = None
    arr_instance_id = None

    if issue.library_item_id:
        lib_item = (await db.execute(select(LibraryItem).filter(LibraryItem.id == issue.library_item_id))).scalars().first()
        if lib_item:
            arr_id = lib_item.arr_id
            arr_instance_id = lib_item.arr_instance_id

    if not arr_id and issue.request_id:
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == issue.request_id))).scalars().first()
        if req:
            arr_id = req.arr_id
            arr_instance_id = req.arr_instance_id

    if not arr_id or not arr_instance_id:
        raise HTTPException(status_code=400, detail="Média non associé à une instance Sonarr/Radarr")

    try:
        if issue.media_type in ("show", "series"):
            inst = await _resolve_arr_instance(db, arr_instance_id, "sonarr")
            success = await sonarr.search_series(inst.url, inst.api_key, arr_id)
        else:
            inst = await _resolve_arr_instance(db, arr_instance_id, "radarr")
            success = await radarr.search_movie(inst.url, inst.api_key, arr_id)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur d'appel *arr : {e}")
