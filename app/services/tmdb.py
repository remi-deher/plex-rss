"""Client TMDB pour le catalogue de découverte (façon Overseerr).

Fournit les listes (tendances, populaires, à l'affiche, découverte par genre),
la recherche, et le détail enrichi (recommandations/similaires/ids externes).
Les réponses sont normalisées vers une forme commune consommée par le frontend.

La clé API TMDB (v3) est stockée dans Settings.tmdb_api_key. Sans clé, les
fonctions lèvent TmdbNotConfigured (le routeur renvoie alors un message clair).

Un cache léger (table SearchCache) évite de refaire les mêmes appels : TTL court
sur les listes/détails, suffisant pour rester bien sous les limites de TMDB.
"""

import json
import logging
from datetime import timedelta
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import SearchCache, Settings
from ..utils import now_utc_naive

logger = logging.getLogger(__name__)

API_BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"
LANG = "fr-FR"
REGION = "FR"
CACHE_TTL = timedelta(hours=12)


class TmdbNotConfigured(Exception):
    """Levée quand aucune clé API TMDB n'est configurée."""


async def _api_key(db: AsyncSession) -> str:
    s = (await db.execute(select(Settings))).scalars().first()
    if s and not s.tmdb_enabled:
        raise TmdbNotConfigured("TMDB est désactivé dans les paramètres")
    key = (s.tmdb_api_key if s else None) or ""
    if not key.strip():
        raise TmdbNotConfigured("Clé API TMDB non configurée")
    return key.strip()


def _poster(path: Optional[str], size: str = "w342") -> Optional[str]:
    return f"{IMG_BASE}/{size}{path}" if path else None


def _backdrop(path: Optional[str], size: str = "w780") -> Optional[str]:
    return f"{IMG_BASE}/{size}{path}" if path else None


async def _cache_get(db: AsyncSession, key: str) -> Optional[dict]:
    row = (await db.execute(
        select(SearchCache).filter(SearchCache.query == key, SearchCache.category == "tmdb")
    )).scalars().first()
    if not row:
        return None
    if row.cached_at and (now_utc_naive() - row.cached_at) > CACHE_TTL:
        return None
    try:
        return json.loads(row.results_json)
    except Exception:
        return None


async def _cache_put(db: AsyncSession, key: str, payload: dict) -> None:
    row = (await db.execute(
        select(SearchCache).filter(SearchCache.query == key, SearchCache.category == "tmdb")
    )).scalars().first()
    if row:
        row.results_json = json.dumps(payload)
        row.cached_at = now_utc_naive()
    else:
        db.add(SearchCache(query=key, category="tmdb", results_json=json.dumps(payload), cached_at=now_utc_naive()))
    await db.commit()


async def check_connection(db: AsyncSession, api_key: Optional[str] = None) -> tuple[bool, str]:
    """Valide la clé API TMDB via un appel léger (/configuration). Retourne (ok, message)."""
    if api_key is not None:
        key = api_key
    else:
        try:
            key = await _api_key(db)
        except TmdbNotConfigured:
            return False, "Clé API TMDB non configurée"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{API_BASE}/configuration", params={"api_key": key})
        if resp.status_code == 200:
            return True, "Clé TMDB valide"
        if resp.status_code == 401:
            return False, "Clé TMDB invalide (401 Unauthorized)"
        return False, f"Réponse TMDB inattendue ({resp.status_code})"
    except Exception as e:
        return False, f"Erreur de connexion TMDB : {e}"


async def _get(db: AsyncSession, path: str, params: Optional[dict] = None, *, cache: bool = True) -> dict:
    """Appel GET TMDB avec cache optionnel. `path` commence par '/'."""
    key = await _api_key(db)
    params = {**(params or {}), "api_key": key, "language": LANG}
    cache_key = f"{path}?{json.dumps({k: v for k, v in params.items() if k != 'api_key'}, sort_keys=True)}"
    if cache:
        cached = await _cache_get(db, cache_key)
        if cached is not None:
            return cached
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}{path}", params=params)
        resp.raise_for_status()
        data = resp.json()
    if cache:
        try:
            await _cache_put(db, cache_key, data)
        except Exception as e:
            logger.debug("Cache TMDB non écrit pour %s: %s", cache_key, e)
    return data


def _norm(item: dict, forced_type: Optional[str] = None) -> Optional[dict]:
    """Normalise un résultat TMDB (movie/tv) vers la forme commune du frontend."""
    mt = forced_type or item.get("media_type")
    if mt not in ("movie", "tv"):
        return None  # ignore les résultats "person" du multi-search
    is_movie = mt == "movie"
    title = item.get("title") if is_movie else item.get("name")
    date = (item.get("release_date") if is_movie else item.get("first_air_date")) or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    return {
        "tmdb_id": item.get("id"),
        "media_type": "movie" if is_movie else "show",  # convention interne du reste de l'app
        "title": title or "",
        "year": year,
        "overview": item.get("overview") or "",
        "poster_url": _poster(item.get("poster_path")),
        "backdrop_url": _backdrop(item.get("backdrop_path")),
        "vote": round(item.get("vote_average") or 0, 1),
        "genre_ids": item.get("genre_ids") or [],
    }


def _norm_list(data: dict, forced_type: Optional[str] = None) -> list[dict]:
    out = []
    for r in data.get("results", []):
        n = _norm(r, forced_type)
        if n and n["tmdb_id"]:
            out.append(n)
    return out


# --- API publiques (consommées par le routeur discover) ---------------------


async def trending(db: AsyncSession, media_type: str = "all", window: str = "week") -> list[dict]:
    mt = media_type if media_type in ("movie", "tv", "all") else "all"
    data = await _get(db, f"/trending/{mt}/{window}")
    forced = None if mt == "all" else mt
    return _norm_list(data, forced)


async def popular(db: AsyncSession, media_type: str, page: int = 1) -> list[dict]:
    mt = "movie" if media_type in ("movie", "movies") else "tv"
    data = await _get(db, f"/{mt}/popular", {"page": page, "region": REGION})
    return _norm_list(data, mt)


async def coming_soon(db: AsyncSession, media_type: str, page: int = 1) -> list[dict]:
    """Films : upcoming ; Séries : on_the_air."""
    if media_type in ("movie", "movies"):
        data = await _get(db, "/movie/upcoming", {"page": page, "region": REGION})
        return _norm_list(data, "movie")
    data = await _get(db, "/tv/on_the_air", {"page": page})
    return _norm_list(data, "tv")


async def genres(db: AsyncSession, media_type: str) -> list[dict]:
    mt = "movie" if media_type in ("movie", "movies") else "tv"
    data = await _get(db, f"/genre/{mt}/list")
    return data.get("genres", [])


async def discover(
    db: AsyncSession, media_type: str, genre: Optional[int] = None, sort_by: str = "popularity.desc", page: int = 1
) -> list[dict]:
    mt = "movie" if media_type in ("movie", "movies") else "tv"
    params = {"page": page, "sort_by": sort_by, "region": REGION}
    if genre:
        params["with_genres"] = genre
    data = await _get(db, f"/discover/{mt}", params)
    return _norm_list(data, mt)


async def search(db: AsyncSession, query: str, page: int = 1) -> list[dict]:
    data = await _get(db, "/search/multi", {"query": query, "page": page, "include_adult": "false"}, cache=False)
    return _norm_list(data)


async def detail(db: AsyncSession, media_type: str, tmdb_id: int) -> dict:
    mt = "movie" if media_type in ("movie", "movies") else "tv"
    data = await _get(
        db,
        f"/{mt}/{tmdb_id}",
        {"append_to_response": "external_ids,recommendations,similar,credits"},
    )
    ext = data.get("external_ids") or {}
    base = _norm({**data, "media_type": mt}, mt) or {}
    base.update(
        {
            "tvdb_id": ext.get("tvdb_id"),
            "imdb_id": ext.get("imdb_id") or data.get("imdb_id"),
            "genres": [g.get("name") for g in data.get("genres", [])],
            "runtime": data.get("runtime") or (data.get("episode_run_time") or [None])[0],
            "status": data.get("status"),
            "number_of_seasons": data.get("number_of_seasons"),
            "recommendations": _norm_list(data.get("recommendations") or {}, mt),
            "similar": _norm_list(data.get("similar") or {}, mt),
        }
    )
    return base


async def external_ids(db: AsyncSession, media_type: str, tmdb_id: int) -> dict:
    mt = "movie" if media_type in ("movie", "movies") else "tv"
    data = await _get(db, f"/{mt}/{tmdb_id}/external_ids")
    return {"tvdb_id": data.get("tvdb_id"), "imdb_id": data.get("imdb_id")}


async def get_tv_seasons_overview(db: AsyncSession, tmdb_id: int) -> list[dict]:
    """Liste des saisons (numéro, nom, nombre d'épisodes) — l'enveloppe légère
    affichée avant même de savoir quoi que ce soit sur la disponibilité ou le VF/VO
    (façon Seerr : `Media.getMedia`, une lecture rapide, jamais un appel Sonarr/Plex).
    Saison 0 (spéciaux) exclue : jamais suivie côté VF/disponibilité dans cette app.
    """
    data = await _get(db, f"/tv/{tmdb_id}")
    return [
        {
            "season_number": s.get("season_number"),
            "name": s.get("name"),
            "episode_count": s.get("episode_count"),
        }
        for s in data.get("seasons", [])
        if s.get("season_number") and s.get("season_number") > 0
    ]


async def get_tv_season_episodes(db: AsyncSession, tmdb_id: int, season_number: int) -> list[dict]:
    """Épisodes d'une saison (numéro, titre, date de diffusion) — même principe que
    `/tv/:id/season/:seasonNumber` chez Seerr : pure métadonnée, aucune notion de
    disponibilité ou de VF/VO ici."""
    data = await _get(db, f"/tv/{tmdb_id}/season/{season_number}")
    return [
        {
            "episode_number": e.get("episode_number"),
            "title": e.get("name"),
            "air_date": e.get("air_date"),
            "overview": e.get("overview") or "",
            "still_url": _backdrop(e.get("still_path"), "w300"),
        }
        for e in data.get("episodes", [])
    ]


async def find_by_external_id(db: AsyncSession, source: str, external_id: int | str) -> Optional[int]:
    """Trouve l'ID TMDB a partir d'un identifiant externe (ex : tvdb_id)."""
    try:
        data = await _get(db, f"/find/{external_id}", {"external_source": source})
        tv_results = data.get("tv_results") or []
        if tv_results:
            return tv_results[0].get("id")
        movie_results = data.get("movie_results") or []
        if movie_results:
            return movie_results[0].get("id")
    except Exception as e:
        logger.warning(f"TMDB /find failed for {source}={external_id}: {e}")
    return None
