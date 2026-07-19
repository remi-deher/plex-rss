"""Conditions de rapprochement partagees entre demandes, Plex et *arr."""

from sqlalchemy import false, or_

from ..models import LibraryItem, MediaRequest


def request_identity_filter(
    *,
    arr_id: int | None = None,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    title: str | None = None,
):
    conditions = []
    if arr_id:
        conditions.append(MediaRequest.arr_id == int(arr_id))
    if tmdb_id:
        conditions.append(MediaRequest.tmdb_id == str(tmdb_id))
    if tvdb_id:
        conditions.append(MediaRequest.tvdb_id == str(tvdb_id))
    if imdb_id:
        conditions.append(MediaRequest.imdb_id == str(imdb_id))
    if conditions:
        return or_(*conditions)
    return MediaRequest.title.ilike(f"%{title}%") if title else false()


def library_identity_filter(req: MediaRequest):
    conditions = []
    if req.tmdb_id:
        conditions.append(LibraryItem.tmdb_id == str(req.tmdb_id))
    if req.tvdb_id:
        conditions.append(LibraryItem.tvdb_id == str(req.tvdb_id))
    if req.imdb_id:
        conditions.append(LibraryItem.imdb_id == str(req.imdb_id))
    return or_(*conditions) if conditions else None
