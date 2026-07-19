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
        "workflow_timeline": request_workflow_timeline(req, origin=origin, fulfillment=fulfillment),
    }


def request_workflow_timeline(
    req: Any, *, origin: dict[str, str] | None = None, fulfillment: str | None = None
) -> list[dict[str, Any]]:
    """Construit le parcours visible sans inventer les etapes anterieures a l'entree."""
    origin = origin or request_origin(getattr(req, "source", None))
    fulfillment = fulfillment or _value(getattr(req, "fulfillment_status", None)) or "not_submitted"

    if origin["kind"] == "plex":
        return [{
            "key": "completed",
            "label": "Deja present dans Plex",
            "state": "completed",
            "occurred_at": getattr(req, "available_at", None),
        }]

    steps: list[dict[str, Any]] = []
    if origin["kind"] == "request":
        steps.append({
            "key": "requested",
            "label": origin["label"],
            "state": "completed",
            "occurred_at": getattr(req, "requested_at", None),
        })
        if getattr(req, "approved_at", None) is not None or fulfillment == "not_submitted":
            steps.append({
                "key": "approval",
                "label": "Approbation de la demande",
                "state": "completed" if getattr(req, "approved_at", None) else "current",
                "occurred_at": getattr(req, "approved_at", None),
            })

    technical_steps = [
        ("awaiting_submission", "En attente d'envoi vers *ARR"),
        ("submitted", "Transmis a *ARR"),
        ("queued", "En file de telechargement"),
        ("downloading", "Telechargement en cours"),
        ("importing", "Import *ARR en cours"),
        ("awaiting_plex", "En attente d'indexation Plex"),
        ("partially_available", "Partiellement disponible dans Plex"),
        ("completed", "Disponible dans Plex"),
    ]
    start_key = "submitted" if origin["kind"] == "arr" else "awaiting_submission"
    start_index = next(i for i, (key, _) in enumerate(technical_steps) if key == start_key)
    visible_steps = technical_steps[start_index:]

    if fulfillment in {"failed", "removed"}:
        completed_until = "submitted" if getattr(req, "arr_processed_at", None) else None
        for key, label in visible_steps:
            if completed_until is None:
                break
            steps.append({
                "key": key,
                "label": label,
                "state": "completed",
                "occurred_at": getattr(req, "arr_processed_at", None) if key == "submitted" else None,
            })
            if key == completed_until:
                break
        steps.append({
            "key": fulfillment,
            "label": "Traitement en erreur" if fulfillment == "failed" else "Retire de *ARR",
            "state": "error",
            "occurred_at": getattr(req, "fulfillment_updated_at", None),
        })
        return steps

    current_index = next(
        (i for i, (key, _) in enumerate(visible_steps) if key == fulfillment),
        -1,
    )
    for index, (key, label) in enumerate(visible_steps):
        occurred_at = None
        if key == "submitted":
            occurred_at = getattr(req, "arr_processed_at", None)
        elif key == "completed":
            occurred_at = getattr(req, "available_at", None)
        elif key == fulfillment:
            occurred_at = getattr(req, "fulfillment_updated_at", None)
        steps.append({
            "key": key,
            "label": label,
            "state": (
                "completed"
                if current_index >= 0 and index < current_index
                else "current"
                if index == current_index
                else "upcoming"
            ),
            "occurred_at": occurred_at,
        })
    return steps


def plex_library_projection() -> dict[str, Any]:
    return {
        "origin_kind": "plex",
        "origin_label": "Deja present dans Plex",
        "operational_status": "completed",
        "operational_status_label": "Disponible dans Plex",
        "waiting_reason": None,
        "workflow_timeline": [{
            "key": "completed",
            "label": "Deja present dans Plex",
            "state": "completed",
            "occurred_at": None,
        }],
    }
