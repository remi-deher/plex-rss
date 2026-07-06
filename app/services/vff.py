"""
Détection de la présence d'une piste audio française (VF/VFF) sur un média Plex.

Porté depuis le projet « Plex VFF Auditor » et adapté au style de plex-rss :
- fonctions pures, sans état global
- réutilise la connexion PlexServer (plexapi, déjà dans les dépendances)

Le point d'entrée principal est `item_has_french_audio(item)` qui inspecte
défensivement toutes les pistes audio d'un film ou d'un épisode Plex.

Pour une série, `show_has_full_french_audio(show)` renvoie True uniquement si
TOUS les épisodes possèdent une piste VF (comportement « complet »).
"""

import logging
from typing import Optional

from plexapi.server import PlexServer

logger = logging.getLogger(__name__)

# Codes ISO (2 ou 3 lettres) considérés comme français — source la plus fiable.
_LANG_CODES = {"fr", "fre", "fra"}
# Noms complets de langue.
_LANG_NAMES = {"french", "français", "francais"}
# Mots dans le titre de piste indiquant une VF ("Français 5.1", "VF", "TrueFrench"…).
_TITLE_WORDS = {"vf", "vff", "french", "français", "francais", "truefrench"}


def _stream_is_french(stream) -> bool:
    """Retourne True si cette piste audio est en français.

    Vérifie défensivement tous les attributs plexapi (certains peuvent être None).
    """
    # 1. Code langue ISO — le plus fiable
    try:
        code = (stream.languageCode or "").lower().strip()
        if code in _LANG_CODES:
            return True
    except Exception:
        pass

    # 2. Nom complet de la langue
    try:
        name = (stream.language or "").lower().strip()
        if name in _LANG_NAMES:
            return True
    except Exception:
        pass

    # 3. Titre / displayTitle de la piste — capte "Français 5.1", "VF", "MULTI", "TrueFrench"
    for attr in ("title", "displayTitle", "extendedDisplayTitle"):
        try:
            raw = (getattr(stream, attr, None) or "").strip()
            if not raw:
                continue
            low = raw.lower()
            # Match au niveau du mot pour éviter les faux positifs "vfx" ou "fr-CA"
            words = set(
                low.replace("-", " ").replace("(", " ").replace(")", " ").replace("/", " ").replace(".", " ").split()
            )
            if words & _TITLE_WORDS:
                return True
            if "multi" in low or "truefrench" in low:
                return True
        except Exception:
            pass

    return False


def get_audio_info(item) -> tuple[bool, list[dict]]:
    """Retourne (has_french, liste_de_pistes) pour un média Plex.

    Chaque piste : {"lang": str, "label": str, "is_fr": bool}
    Utilise getattr partout pour gérer les attributs manquants / None.
    """
    has_fr = False
    tracks: list[dict] = []
    seen: set[str] = set()
    filename_has_vf = False

    try:
        for media in item.media:
            for part in media.parts:
                # Analyse du nom de fichier
                filename = (getattr(part, "file", "") or "").lower()
                if filename:
                    words = set(
                        filename.replace("-", " ")
                        .replace("(", " ")
                        .replace(")", " ")
                        .replace("/", " ")
                        .replace(".", " ")
                        .replace("[", " ")
                        .replace("]", " ")
                        .replace("_", " ")
                        .split()
                    )
                    if words & {"vf", "vff", "truefrench", "french", "multi"}:
                        filename_has_vf = True

                for stream in part.audioStreams():
                    lc = getattr(stream, "languageCode", None)
                    lang = getattr(stream, "language", None)
                    title = getattr(stream, "title", None)
                    disp = getattr(stream, "displayTitle", None)

                    is_fr = _stream_is_french(stream)
                    if is_fr:
                        has_fr = True

                    label = disp or title or lc or lang or "?"
                    key = label.lower()
                    if key not in seen:
                        seen.add(key)
                        tracks.append(
                            {
                                "lang": (lc or lang or "?").lower(),
                                "label": label,
                                "is_fr": is_fr,
                            }
                        )

        # Fallback nom de fichier si aucune piste détectée
        if not has_fr and filename_has_vf:
            has_fr = True
            tracks.append(
                {
                    "lang": "fr",
                    "label": "VF/VFF (via nom de fichier)",
                    "is_fr": True,
                }
            )
    except Exception as exc:
        logger.warning("Erreur lecture pistes audio pour %r: %s", getattr(item, "title", "?"), exc)

    return has_fr, tracks


def item_has_french_audio(item) -> bool:
    """True si le média (film ou épisode) possède au moins une piste VF."""
    has_fr, _ = get_audio_info(item)
    return has_fr


def _reload(item, label: str = "item") -> None:
    """Appelle item.reload() pour récupérer les métadonnées complètes (pistes audio).

    lib.all() / season.episodes() renvoient des stubs sans détail de flux ;
    reload() complète ces informations.
    """
    try:
        item.reload()
    except Exception as exc:
        logger.warning("Impossible de recharger %s %r: %s", label, getattr(item, "title", "?"), exc)


def movie_has_french_audio(item) -> bool:
    """True si le film possède une piste VF (recharge d'abord les métadonnées complètes)."""
    _reload(item, "movie")
    return item_has_french_audio(item)


def show_has_full_french_audio(show) -> tuple[bool, bool, int, int]:
    """Analyse tous les épisodes d'une série.

    Returns:
        (complet, should_track, episodes_avec_vf, total_episodes)
        `complet` est True uniquement si TOUS les épisodes ont une piste VF.
        `should_track` détermine si on doit continuer à surveiller cette série en VO.
    """
    total = 0
    with_vf = 0
    seasons_info = {}

    try:
        for season in show.seasons():
            sn = getattr(season, "seasonNumber", None)
            if sn is None or sn == 0:  # ignore les spéciaux (saison 0)
                continue
            seasons_info[sn] = {"total": 0, "vf": 0}
            for ep in season.episodes():
                total += 1
                seasons_info[sn]["total"] += 1
                _reload(ep, "episode")
                if item_has_french_audio(ep):
                    with_vf += 1
                    seasons_info[sn]["vf"] += 1
    except Exception as exc:
        logger.warning("Erreur analyse épisodes pour %r: %s", getattr(show, "title", "?"), exc)

    complete = total > 0 and with_vf == total

    if complete:
        return True, False, with_vf, total

    # Calcul du nombre de saisons qui ont au moins 1 VF
    vf_seasons = {sn for sn, info in seasons_info.items() if info["vf"] > 0}
    num_vf_seasons = len(vf_seasons)

    should_track = False
    for sn, info in seasons_info.items():
        if info["total"] > info["vf"]:
            # Cette saison a des épisodes en VO uniquement
            track_this_season = False
            if info["vf"] > 0:
                # Règle 1 : saison partiellement en VF -> on la surveille
                track_this_season = True
            elif num_vf_seasons >= 2:
                # Règle 2 : au moins 2 saisons ont de la VF -> on surveille les autres
                track_this_season = True
            elif num_vf_seasons == 0:
                # Aucun épisode VF sur toute la série pour le moment -> on surveille tout
                track_this_season = True

            if track_this_season:
                should_track = True
                break

    return complete, should_track, with_vf, total


def connect(plex_url: str, plex_token: str, timeout: int = 30) -> PlexServer:
    """Ouvre une connexion au serveur Plex local (lève une exception si échec)."""
    return PlexServer(plex_url, plex_token, timeout=timeout)


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
    has_fr, tracks = get_audio_info(item)
    return {"found": True, "has_vf": has_fr, "tracks": tracks}


def get_show_episode_vf_blocking(
    plex_url: str,
    plex_token: str,
    show_libs: list[str],
    title: str,
    year: Optional[int],
    tmdb_id: Optional[str],
    tvdb_id: Optional[str],
    imdb_id: Optional[str],
) -> dict:
    """Carte VF par épisode d'une série présente dans Plex (bloquant, plexapi).

    Retourne {"found": bool, "episodes": {season_number: {episode_number: has_vf}}}.
    Seuls les épisodes réellement présents dans Plex apparaissent ici ; le croisement
    avec la liste attendue de Sonarr (épisodes absents) se fait côté appelant.
    """
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
                ep_map.setdefault(sn, {})[en] = item_has_french_audio(ep)
    except Exception as exc:
        logger.warning("Erreur détail épisodes VF pour %r: %s", getattr(item, "title", "?"), exc)
    return {"found": True, "episodes": ep_map}


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
) -> dict:
    """Localise un média dans Plex et détermine son statut VF (bloquant, plexapi).

    `show_libs` est une liste de tuples (nom_bibliothèque, kind) où kind vaut
    "series" ou "anime", utilisée pour catégoriser le résultat.

    Retourne {"found": False} si le média n'est pas trouvé, sinon
    {"found": True, "has_vf": bool, "category": "movie"|"series"|"anime"}.
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
    complete, should_track, _, _ = show_has_full_french_audio(item)
    return {"found": True, "has_vf": complete or (not should_track), "category": category}


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
                    # Extraction des GUIDs externes (TMDB, TVDB, IMDB)
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

                    items.append({
                        "title": m.title,
                        "year": getattr(m, "year", None),
                        "media_type": "show" if lib["kind"] in ("series", "anime") else "movie",
                        "plex_guid": getattr(m, "guid", None),
                        "tmdb_id": tmdb_id,
                        "tvdb_id": tvdb_id,
                        "imdb_id": imdb_id,
                        "poster_url": f"{plex_url.rstrip('/')}{m.thumb}?X-Plex-Token={plex_token}" if getattr(m, "thumb", None) else None,
                        "overview": getattr(m, "summary", None),
                        "added_at": getattr(m, "addedAt", None),
                    })
                except Exception as item_exc:
                    logger.warning(f"VFF sync : erreur lecture média '{getattr(m, 'title', '?')}' : {item_exc}")
        except Exception as lib_exc:
            logger.warning(f"VFF sync : impossible de lire la bibliothèque '{lib['name']}' : {lib_exc}")

    return items
