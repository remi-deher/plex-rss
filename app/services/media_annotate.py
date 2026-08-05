"""Annotation d'état local sur des items TMDB normalisés (bibliothèque/demande/VF).

Extrait de app/routers/discover_api.py pour être réutilisable depuis un service
(app/services/media_detail.py) sans dépendre d'un module routeur.
"""

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import LibraryItem, MediaRequest
from ..serializers import request_status_value
from .operational_projection import plex_library_projection, request_operational_projection


async def annotate_media_items(db: AsyncSession, items: list[dict]) -> list[dict]:
    """Ajoute l'état local (bibliothèque/demande/VF) à chaque item, pour badge + lien
    vers la fiche Library (qui porte déjà tout le reste : recherche interactive, ajout
    de demandeur, relance, anomalie Plex, suppression — pas de duplication ici)."""
    ids_by_type: dict[str, set[str]] = {"movie": set(), "show": set()}
    for it in items:
        if it.get("tmdb_id") is not None and it.get("media_type") in ids_by_type:
            ids_by_type[it["media_type"]].add(str(it["tmdb_id"]))

    # Deux requêtes au total, quel que soit le nombre de médias ou de types présents.
    # Les anciennes boucles effectuaient une requête LibraryItem et MediaRequest par type.
    library_filters = [
        and_(LibraryItem.media_type == media_type, LibraryItem.tmdb_id.in_(ids))
        for media_type, ids in ids_by_type.items()
        if ids
    ]
    request_filters = [
        and_(MediaRequest.media_type == media_type, MediaRequest.tmdb_id.in_(ids))
        for media_type, ids in ids_by_type.items()
        if ids
    ]

    library_rows = []
    request_rows = []
    if library_filters:
        library_rows = (await db.execute(select(LibraryItem).filter(or_(*library_filters)))).scalars().all()
        request_rows = (
            await db.execute(
                select(MediaRequest)
                .filter(or_(*request_filters))
                .order_by(MediaRequest.requested_at.desc(), MediaRequest.id.desc())
            )
        ).scalars().all()

    lib: dict[tuple[str, str], LibraryItem] = {
        (li.media_type, li.tmdb_id): li for li in library_rows if li.tmdb_id
    }
    reqs: dict[tuple[str, str], MediaRequest] = {}
    status_priority = {
        "available": 6,
        "partially_available": 5,
        "sent_to_arr": 4,
        "pending": 3,
        "pending_approval": 2,
        "failed": 1,
    }
    for req in request_rows:
        if req.tmdb_id:
            key = (req.media_type, req.tmdb_id)
            current = reqs.get(key)
            if current is None or status_priority.get(request_status_value(req.status), 0) > status_priority.get(
                request_status_value(current.status), 0
            ):
                reqs[key] = req

    for it in items:
        k = (it.get("media_type"), str(it.get("tmdb_id")))
        li = lib.get(k)
        req = reqs.get(k)
        it["in_library"] = li is not None
        it["library_id"] = li.id if li else None
        it["request_id"] = req.id if req else None
        st = request_status_value(req.status) if req else None
        it["requested"] = st is not None
        it["request_status"] = st
        # Une serie "partiellement disponible" (au moins un episode deja regardable) compte
        # comme "dans Plex" au meme titre qu'une demande pleinement disponible -- coherent
        # avec le filtre "Dans Plex" de la Bibliotheque (voir LibraryView.matchesStatusFilter).
        it["available"] = it["in_library"] or st in ("available", "partially_available")
        it["has_vf"] = li.has_vf if li else (req.has_vf if req else None)
        it["vf_granularity"] = (li.vf_granularity if li else None) or (req.vf_granularity if req else None)
        # En cours de téléchargement (prioritaire sur l'anomalie) : cf. commentaire équivalent
        # dans app/routers/pages.py.
        it["is_downloading"] = bool(req and req.is_downloading)
        # Anomalie : *arr dit "disponible" mais absent de la bibliothèque Plex synchronisée,
        # à condition qu'il ne soit pas encore en cours de téléchargement/import.
        it["plex_anomaly"] = bool(req and st == "available" and not li and not req.is_downloading)
        it["plex_guid"] = li.plex_guid if li else (req.plex_guid if req else None)
        if li:
            it.update(plex_library_projection())
        elif req:
            it.update(request_operational_projection(req))
    return items


async def annotate_page(db: AsyncSession, payload: dict) -> dict:
    payload["items"] = await annotate_media_items(db, payload.get("items", []))
    return payload
