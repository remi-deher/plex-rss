"""Projection lisible du parcours demande -> *ARR -> Plex.

Les donnees historiques n'ont pas toutes une demande utilisateur. Cette projection
conserve donc l'origine reelle au lieu de fabriquer une etape "demande" pour les
medias decouverts dans *ARR ou deja presents dans Plex.
"""

from typing import Any


ARR_SOURCES = {"arr", "arr_sync", "sonarr", "radarr", "manual_import"}
PLEX_SOURCES = {"plex", "plex_sync", "library"}
SEER_SOURCES = {"seer", "overseerr", "jellyseerr"}


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def request_origin(source: str | None) -> dict[str, str]:
    normalized = (source or "").strip().lower()
    if normalized in ARR_SOURCES:
        return {"kind": "arr", "label": "Ajoute directement dans *ARR"}
    if normalized in PLEX_SOURCES:
        return {"kind": "plex", "label": "Deja present dans Plex"}
    if normalized in SEER_SOURCES:
        return {"kind": "request", "label": "Demande via Seerr"}
    return {"kind": "request", "label": "Demande utilisateur"}


def request_operational_projection(req: Any) -> dict[str, Any]:
    origin = request_origin(getattr(req, "source", None))
    fulfillment = _value(getattr(req, "fulfillment_status", None)) or "not_submitted"
    error = getattr(req, "fulfillment_error", None)

    labels = {
        "not_submitted": "En attente d'approbation",
        "awaiting_submission": "En attente d'envoi vers *ARR",
        "submitted": "Transmis a *ARR",
        "queued": "En file de telechargement",
        "downloading": "Telechargement en cours",
        "importing": "Import *ARR en cours",
        "awaiting_plex": "Importe, en attente de Plex",
        "partially_available": "Partiellement disponible dans Plex",
        "completed": "Disponible dans Plex",
        "failed": "Traitement en erreur",
        "removed": "Retire de *ARR",
    }
    waiting_reasons = {
        "not_submitted": "La demande doit encore etre approuvee.",
        "awaiting_submission": "Aucune confirmation d'envoi vers Sonarr/Radarr n'a encore ete recue.",
        "submitted": "Le media est suivi par *ARR, mais aucune release n'est encore en file.",
        "queued": "Une release est en file et attend son demarrage.",
        "downloading": "Le client de telechargement n'a pas encore termine.",
        "importing": "Sonarr/Radarr est en train d'importer les fichiers termines.",
        "awaiting_plex": "L'import *ARR est termine; Plex doit encore indexer et confirmer le media.",
        "partially_available": "Une partie seulement du media est confirmee dans Plex.",
        "failed": error or "Une erreur technique bloque le parcours.",
        "removed": "Le media n'est plus suivi par *ARR.",
    }
    return {
        "origin_kind": origin["kind"],
        "origin_label": origin["label"],
        "operational_status": fulfillment,
        "operational_status_label": labels.get(fulfillment, fulfillment),
        "waiting_reason": waiting_reasons.get(fulfillment),
    }


def plex_library_projection() -> dict[str, Any]:
    return {
        "origin_kind": "plex",
        "origin_label": "Deja present dans Plex",
        "operational_status": "completed",
        "operational_status_label": "Disponible dans Plex",
        "waiting_reason": None,
    }
