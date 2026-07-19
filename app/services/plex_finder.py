import logging
from typing import Optional
from plexapi.server import PlexServer

from .audio_analyzer import _reload, get_audio_info, get_french_audio_state, movie_has_french_audio, show_has_full_french_audio

logger = logging.getLogger(__name__)

def connect(plex_url: str, plex_token: str, timeout: int = 30) -> PlexServer:
    """Ouvre une connexion au serveur Plex local (lève une exception si échec)."""
    return PlexServer(plex_url, plex_token, timeout=timeout)


def refresh_sections_blocking(plex_url: str, plex_token: str, section_names: list[str]) -> None:
    """Déclenche un scan Plex (refresh complet de section) pour les sections données.

    Utilisé pour prévenir Plex dès qu'un import Sonarr/Radarr est détecté, au lieu
    d'attendre son propre calendrier de scan de bibliothèque. Best-effort : une section
    en erreur (introuvable, Plex temporairement indisponible...) n'interrompt pas les
    autres.
    """
    plex = connect(plex_url, plex_token)
    for name in section_names:
        try:
            plex.library.section(name).update()
        except Exception as exc:
            logger.warning(f"Refresh Plex échoué pour la section {name!r}: {exc}")


def _external_id_matches(item, tmdb_id: Optional[str], tvdb_id: Optional[str], imdb_id: Optional[str]) -> bool:
    """True si les GUIDs Plex de l'item correspondent à l'un des identifiants fournis."""
    try:
        for guid in getattr(item, "guids", []):
            gid = guid.id or ""
            if tmdb_id and gid == f"tmdb://{tmdb_id}":
                return True
            if tvdb_id and gid == f"tvdb://{tvdb_id}":
                return True
            if imdb_id and gid == f"imdb://{imdb_id}":
                return True
        # Vérification du guid principal (prise en charge des agents classiques)
        main_guid = getattr(item, "guid", "") or ""
        if tmdb_id and (f"tmdb://{tmdb_id}" in main_guid or f"themoviedb://{tmdb_id}" in main_guid):
            return True
        if tvdb_id and (f"tvdb://{tvdb_id}" in main_guid or f"thetvdb://{tvdb_id}" in main_guid):
            return True
        if imdb_id and (f"imdb://{imdb_id}" in main_guid or f"themoviedb://{imdb_id}" in main_guid):
            return True
    except Exception:
        pass
    return False


def get_movie_audio_detail_blocking(
    plex_url: str,
    plex_token: str,
    movie_libs: list[str],
    title: str,
    year: Optional[int],
    tmdb_id: Optional[str],
    tvdb_id: Optional[str],
    imdb_id: Optional[str],
) -> dict:
    """Détail audio d'un film (bloquant, plexapi) : pistes détectées + has_vf.

    Retourne {"found": bool, "has_vf": bool, "tracks": [...]}.
    """
    try:
        plex = connect(plex_url, plex_token)
    except Exception as exc:
        return {"found": False, "error": str(exc)}
    item = find_item_in_libraries(plex, movie_libs, title, year, tmdb_id, tvdb_id, imdb_id)
    if not item:
        return {"found": False}
    _reload(item, "movie")
    has_fr, tracks, subtitles = get_audio_info(item)
    return {"found": True, "has_vf": has_fr, "tracks": tracks, "subtitles": subtitles}


def get_show_episode_vf_blocking(
    plex_url: str,
    plex_token: str,
    show_libs: list[str],
    title: str,
    year: Optional[int],
    tmdb_id: Optional[str],
    tvdb_id: Optional[str],
    imdb_id: Optional[str],
    known_vf: Optional[dict[int, set[int]]] = None,
) -> dict:
    """Carte VF par épisode d'une série présente dans Plex (bloquant, plexapi).

    `known_vf` : cache des épisodes déjà confirmés VF lors d'un scan précédent
    (voir `show_has_full_french_audio`) — ils ne sont pas re-scannés dans Plex.

    Retourne {"found": bool, "episodes": {season_number: {episode_number: has_vf}}}.
    Seuls les épisodes réellement présents dans Plex apparaissent ici ; le croisement
    avec la liste attendue de Sonarr (épisodes absents) se fait côté appelant.
    """
    known_vf = known_vf or {}
    try:
        plex = connect(plex_url, plex_token)
    except Exception as exc:
        return {"found": False, "error": str(exc)}
    item = None
    for name in show_libs:
        item = find_item_in_libraries(plex, [name], title, year, tmdb_id, tvdb_id, imdb_id)
        if item:
            break
    if not item:
        return {"found": False}

    ep_map: dict[int, dict[int, bool]] = {}
    priority_map: dict[int, dict[int, bool]] = {}
    try:
        for season in item.seasons():
            sn = getattr(season, "seasonNumber", None)
            if sn is None:
                continue
            for ep in season.episodes():
                en = getattr(ep, "index", None)
                if en is None:
                    continue
                _reload(ep, "episode")
                audio_state = get_french_audio_state(ep)
                ep_map.setdefault(sn, {})[en] = audio_state["has_fr"]
                priority_map.setdefault(sn, {})[en] = audio_state["fr_is_default"]
    except Exception as exc:
        logger.warning("Erreur détail épisodes VF pour %r: %s", getattr(item, "title", "?"), exc)
    return {"found": True, "episodes": ep_map, "french_default": priority_map}


def find_item_in_libraries(
    plex: PlexServer,
    library_names: list[str],
    title: str,
    year: Optional[int] = None,
    tmdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
    imdb_id: Optional[str] = None,
    plex_guid: Optional[str] = None,
):
    """Localise un média dans les bibliothèques Plex données.

    Priorité de correspondance : GUID Plex, identifiants externes (TMDB/TVDB/IMDB) puis titre+année.
    Renvoie l'objet plexapi (Movie ou Show) ou None.
    """
    for lib_name in library_names:
        try:
            section = plex.library.section(lib_name)
        except Exception as exc:
            logger.debug("Bibliothèque %r indisponible: %s", lib_name, exc)
            continue

        # 1. Recherche par GUID Plex si présent
        if plex_guid:
            try:
                candidates = section.search(guid=plex_guid) if hasattr(section, "search") else []
                if candidates:
                    return candidates[0]
            except Exception as e:
                logger.debug(f"Search by guid {plex_guid} in {lib_name} failed: {e}")

        # 2. Recherche par GUID d'identifiant externe direct (TMDB / TVDB / IMDB)
        for provider, val in [("tmdb", tmdb_id), ("tvdb", tvdb_id), ("imdb", imdb_id)]:
            if val:
                try:
                    candidates = section.search(guid=f"{provider}://{val}")
                    if candidates:
                        return candidates[0]
                except Exception:
                    pass

        # 3. Recherche par ID externe textuel (Plex indexe les IDs externes dans l'index de recherche)
        for val in [imdb_id, tmdb_id, tvdb_id]:
            if val:
                try:
                    candidates = section.search(title=val)
                    for cand in candidates:
                        try:
                            cand.reload()
                        except Exception:
                            pass
                        if _external_id_matches(cand, tmdb_id, tvdb_id, imdb_id):
                            return cand
                except Exception:
                    pass

        # 4. Recherche par titre (fuzzy/rapide via l'index Plex)
        try:
            candidates = section.search(title=title) if hasattr(section, "search") else []
        except Exception:
            candidates = []

        # 5. Validation par identifiants externes sur les candidats trouvés par titre
        if tmdb_id or tvdb_id or imdb_id:
            for cand in candidates:
                try:
                    cand.reload()
                except Exception:
                    pass
                if _external_id_matches(cand, tmdb_id, tvdb_id, imdb_id):
                    return cand

        # 6. Fallback titre exact (+ année si connue)
        tl = title.lower().strip()
        for cand in candidates:
            if (getattr(cand, "title", "") or "").lower().strip() == tl:
                if year is None or getattr(cand, "year", None) in (None, year):
                    return cand

        # 7. Fallback ultime : Parcours complet de la bibliothèque en Python (rapide, sans rechargement)
        if tmdb_id or tvdb_id or imdb_id:
            try:
                all_items = section.all()
                for cand in all_items:
                    if _external_id_matches(cand, tmdb_id, tvdb_id, imdb_id):
                        return cand
            except Exception as e:
                logger.debug(f"Ultimate fallback scan in {lib_name} failed: {e}")

    return None


def scan_media_vf(
    plex: PlexServer,
    media_type: str,
    movie_libs: list[str],
    show_libs: list[tuple[str, str]],
    title: str,
    year: Optional[int],
    tmdb_id: Optional[str],
    tvdb_id: Optional[str],
    imdb_id: Optional[str],
    plex_guid: Optional[str] = None,
    known_vf: Optional[dict[int, set[int]]] = None,
) -> dict:
    """Localise un média dans Plex et détermine son statut VF (bloquant, plexapi).

    `show_libs` est une liste de tuples (nom_bibliothèque, kind) où kind vaut
    "series" ou "anime", utilisée pour catégoriser le résultat.

    `known_vf` (séries uniquement) : cache des épisodes déjà confirmés VF, voir
    `show_has_full_french_audio`. Ignoré pour les films.

    Retourne {"found": False} si le média n'est pas trouvé, sinon
    {"found": True, "has_vf": bool, "category": "movie"|"series"|"anime"}
    (+ "episode_status" pour les séries, à persister dans le cache par l'appelant).
    """
    if media_type == "movie":
        item = find_item_in_libraries(plex, movie_libs, title, year, tmdb_id, tvdb_id, imdb_id, plex_guid=plex_guid)
        if not item:
            return {"found": False}
        return {"found": True, "has_vf": movie_has_french_audio(item), "category": "movie"}

    item = None
    category = "series"
    for name, kind in show_libs:
        item = find_item_in_libraries(plex, [name], title, year, tmdb_id, tvdb_id, imdb_id, plex_guid=plex_guid)
        if item:
            category = "anime" if kind == "anime" else "series"
            break
    if not item:
        return {"found": False}
    complete, should_track, _, _, episode_status, french_default = show_has_full_french_audio(item, known_vf=known_vf)
    return {
        "found": True,
        "has_vf": complete or (not should_track),
        "category": category,
        "episode_status": episode_status,
        "french_default": french_default,
    }


def _plex_item_to_dict(m, lib: dict, plex_url: str, plex_token: str) -> dict:
    """Convertit un item plexapi (Movie/Show) en dict structuré pour l'integration en base.

    Partagee par le scan complet et le scan incremental ("recemment ajoutes") : meme
    forme de sortie consommee par `_integrate_plex_items`, quelle que soit la source.
    """
    tmdb_id = None
    tvdb_id = None
    imdb_id = None
    for guid in getattr(m, "guids", []):
        gid = guid.id or ""
        if gid.startswith("tmdb://"):
            tmdb_id = gid.split("tmdb://")[-1]
        elif gid.startswith("tvdb://"):
            tvdb_id = gid.split("tvdb://")[-1]
        elif gid.startswith("imdb://"):
            imdb_id = gid.split("imdb://")[-1]

    return {
        "title": m.title,
        "year": getattr(m, "year", None),
        "media_type": "show" if lib["kind"] in ("series", "anime") else "movie",
        "plex_guid": getattr(m, "guid", None),
        "tmdb_id": tmdb_id,
        "tvdb_id": tvdb_id,
        "imdb_id": imdb_id,
        "poster_url": f"{plex_url.rstrip('/')}{m.thumb}?X-Plex-Token={plex_token}"
        if getattr(m, "thumb", None)
        else None,
        "overview": getattr(m, "summary", None),
        "added_at": getattr(m, "addedAt", None),
    }


def sync_plex_library_blocking(plex_url: str, plex_token: str, libs: list[dict]) -> list[dict]:
    """Récupère l'intégralité des médias présents dans les bibliothèques Plex spécifiées.

    Retourne une liste de dictionnaires structurés.
    """
    try:
        plex = connect(plex_url, plex_token)
    except Exception as exc:
        logger.error(f"VFF sync : connexion Plex impossible : {exc}")
        return []

    items = []
    for lib in libs:
        try:
            section = plex.library.section(lib["name"])
            all_media = section.all()
            for m in all_media:
                try:
                    items.append(_plex_item_to_dict(m, lib, plex_url, plex_token))
                except Exception as item_exc:
                    logger.warning(f"VFF sync : erreur lecture média '{getattr(m, 'title', '?')}' : {item_exc}")
        except Exception as lib_exc:
            logger.warning(f"VFF sync : impossible de lire la bibliothèque '{lib['name']}' : {lib_exc}")

    return items


def sync_plex_library_recent_blocking(plex_url: str, plex_token: str, libs: list[dict], since) -> list[dict]:
    """Recupere uniquement les medias ajoutes a Plex depuis `since` (scan incremental).

    Utilise le filtre avance `filters={"addedAt>>": since}` de plexapi (traduit
    serveur-side en epoch, voir LibrarySection._validateFieldValueDate) plutot que
    `section.all()` : cout quasi nul meme sur une grosse bibliotheque, pense pour
    tourner toutes les quelques minutes (voir sync_plex_media_recent) au lieu
    d'attendre le scan complet quotidien -- meme principe que le "Recently Added Scan"
    de Seer/Overseerr.

    Note : la forme kwarg `addedAt__gte=...` existe aussi cote plexapi mais declenche
    un filtrage cote client qui compare la valeur brute renvoyee par Plex (str) a notre
    datetime Python et leve une TypeError -- `filters={"addedAt>>": ...}` est la seule
    forme qui passe par la conversion epoch serveur.
    """
    try:
        plex = connect(plex_url, plex_token)
    except Exception as exc:
        logger.error(f"VFF sync (recent) : connexion Plex impossible : {exc}")
        return []

    items = []
    for lib in libs:
        try:
            section = plex.library.section(lib["name"])
            recent_media = section.search(filters={"addedAt>>": since})
            for m in recent_media:
                try:
                    items.append(_plex_item_to_dict(m, lib, plex_url, plex_token))
                except Exception as item_exc:
                    logger.warning(f"VFF sync (recent) : erreur lecture média '{getattr(m, 'title', '?')}' : {item_exc}")
        except Exception as lib_exc:
            logger.warning(f"VFF sync (recent) : impossible de lire la bibliothèque '{lib['name']}' : {lib_exc}")

    return items
