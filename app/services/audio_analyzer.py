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


def _truthy_attr(value) -> bool:
    if isinstance(value, str):
        return value.lower().strip() in {"1", "true", "yes", "selected", "default"}
    return bool(value)


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


def get_audio_info(item) -> tuple[bool, list[dict], list[dict]]:
    """Retourne (has_french, liste_de_pistes, liste_de_sous_titres) pour un média Plex.

    Chaque piste : {"lang": str, "label": str, "is_fr": bool}
    Chaque sous-titre : {"lang": str, "label": str, "is_default": bool}
    Utilise getattr partout pour gérer les attributs manquants / None.
    """
    has_fr = False
    tracks: list[dict] = []
    subtitles: list[dict] = []
    seen: set[str] = set()
    seen_subs: set[str] = set()
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

                    is_default = any(
                        _truthy_attr(getattr(stream, attr, None))
                        for attr in ("selected", "default", "defaultAudioStream")
                    )

                    label = disp or title or lc or lang or "?"
                    key = label.lower()
                    if key not in seen:
                        seen.add(key)
                        tracks.append(
                            {
                                "lang": (lc or lang or "?").lower(),
                                "label": label,
                                "is_fr": is_fr,
                                "is_default": is_default,
                            }
                        )

                for stream in part.subtitleStreams():
                    lc = getattr(stream, "languageCode", None)
                    lang = getattr(stream, "language", None)
                    title = getattr(stream, "title", None)
                    disp = getattr(stream, "displayTitle", None)

                    is_default = any(
                        _truthy_attr(getattr(stream, attr, None))
                        for attr in ("selected", "default", "defaultSubtitleStream", "forced")
                    )

                    label = disp or title or lc or lang or "?"
                    key = label.lower()
                    if key not in seen_subs:
                        seen_subs.add(key)
                        subtitles.append(
                            {
                                "lang": (lc or lang or "?").lower(),
                                "label": label,
                                "is_default": is_default,
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

    return has_fr, tracks, subtitles


def item_has_french_audio(item) -> bool:
    """True si le média (film ou épisode) possède au moins une piste VF."""
    has_fr, _, _ = get_audio_info(item)
    return has_fr


def get_french_audio_state(item) -> dict:
    """Etat compact de priorite audio FR pour un film ou episode Plex."""
    has_fr, tracks, subtitles = get_audio_info(item)
    if not has_fr:
        return {"has_fr": False, "fr_is_default": False, "tracks": tracks, "subtitles": subtitles}

    try:
        first_audio_is_fr = None
        fr_marked_default = False
        any_marked_default = False
        for media in item.media:
            for part in media.parts:
                for stream in part.audioStreams():
                    is_fr = _stream_is_french(stream)
                    if first_audio_is_fr is None:
                        first_audio_is_fr = is_fr
                    is_default = any(
                        _truthy_attr(getattr(stream, attr, None))
                        for attr in ("selected", "default", "defaultAudioStream")
                    )
                    if is_default:
                        any_marked_default = True
                        if is_fr:
                            fr_marked_default = True
        if fr_marked_default:
            return {"has_fr": True, "fr_is_default": True, "tracks": tracks, "subtitles": subtitles}
        if any_marked_default:
            return {"has_fr": True, "fr_is_default": False, "tracks": tracks, "subtitles": subtitles}
        if first_audio_is_fr is None:
            return {"has_fr": True, "fr_is_default": True, "tracks": tracks, "subtitles": subtitles}
        return {"has_fr": True, "fr_is_default": bool(first_audio_is_fr), "tracks": tracks, "subtitles": subtitles}
    except Exception as exc:
        logger.warning("Erreur lecture priorite audio pour %r: %s", getattr(item, "title", "?"), exc)
        return {"has_fr": True, "fr_is_default": True, "tracks": tracks, "subtitles": subtitles}


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


def show_has_full_french_audio(
    show, known_vf: Optional[dict[int, set[int]]] = None
) -> tuple[bool, bool, int, int, dict[int, dict[int, bool]], dict[int, dict[int, bool]]]:
    """Analyse tous les épisodes d'une série.

    `known_vf` : {season_number: {episode_number déjà confirmés VF lors d'un scan
    précédent}}. Ces épisodes ne sont PAS re-scannés (aucun appel Plex) — une fois
    qu'un épisode a une piste VF, elle ne disparaît pas, donc c'est un cache sûr.
    Passer None ou {} pour un scan complet sans cache.

    Returns:
        (complet, should_track, episodes_avec_vf, total_episodes, episode_status)
        `complet` est True uniquement si TOUS les épisodes ont une piste VF.
        `should_track` détermine si on doit continuer à surveiller cette série en VO.
        `episode_status` : {season_number: {episode_number: has_vf}} pour persistance.
    """
    known_vf = known_vf or {}
    total = 0
    with_vf = 0
    seasons_info = {}
    episode_status: dict[int, dict[int, bool]] = {}
    french_default_status: dict[int, dict[int, bool]] = {}

    try:
        for season in show.seasons():
            sn = getattr(season, "seasonNumber", None)
            if sn is None or sn == 0:  # ignore les spéciaux (saison 0)
                continue
            seasons_info[sn] = {"total": 0, "vf": 0}
            episode_status[sn] = {}
            french_default_status[sn] = {}
            known_season = known_vf.get(sn, set())
            for ep in season.episodes():
                en = getattr(ep, "index", None)
                if en is None:
                    continue
                total += 1
                seasons_info[sn]["total"] += 1
                if en in known_season:
                    # Déjà confirmé VF lors d'un scan précédent : pas de re-scan Plex.
                    has_fr = True
                    fr_is_default = True
                else:
                    _reload(ep, "episode")
                    audio_state = get_french_audio_state(ep)
                    has_fr = audio_state["has_fr"]
                    fr_is_default = audio_state["fr_is_default"]
                episode_status[sn][en] = has_fr
                french_default_status[sn][en] = fr_is_default
                if has_fr:
                    with_vf += 1
                    seasons_info[sn]["vf"] += 1
    except Exception as exc:
        logger.warning("Erreur analyse épisodes pour %r: %s", getattr(show, "title", "?"), exc)

    complete = total > 0 and with_vf == total

    if complete:
        return True, False, with_vf, total, episode_status, french_default_status

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

    return complete, should_track, with_vf, total, episode_status, french_default_status


def compute_vf_granularity(episode_status: dict[int, dict[int, bool]] | None) -> str:
    """Niveau de granularité VF d'une série non-complète, à partir de son statut par épisode.

    - "season_partial"  : au moins une saison entièrement en VF (mais pas toute la série)
    - "episode_partial" : au moins un épisode en VF, mais aucune saison complète
    - "none"             : aucun épisode en VF (ou pas encore de données)

    Une saison est considérée « entièrement en VF » par rapport aux épisodes connus de
    Plex (mêmes données que `has_vf` au niveau série) — si Sonarr n'a pas encore
    tout téléchargé, seuls les épisodes présents comptent.
    """
    if not episode_status:
        return "none"
    any_vf = False
    any_full_season = False
    for season_eps in episode_status.values():
        if not season_eps:
            continue
        vals = list(season_eps.values())
        if any(vals):
            any_vf = True
        if all(vals):
            any_full_season = True
    if any_full_season:
        return "season_partial"
    if any_vf:
        return "episode_partial"
    return "none"

