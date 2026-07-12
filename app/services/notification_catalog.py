from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class NotificationEvent:
    key: str
    label: str
    group: str
    description: str
    color: int = 0x888888
    badge_class: str = "bg-secondary"
    mail_flags: tuple[str, ...] = ()
    template_field: str | None = None
    subject_field: str | None = None
    default_subject: str | None = None
    media_scope: tuple[str, ...] = ("movie", "show")
    preview_context: dict[str, Any] = field(default_factory=dict)


# Catalogue réduit à 3 évènements réels (le digest quotidien est un mécanisme séparé, hors
# file de notification par demande — voir notification_orchestrator._send_digest). L'ancien
# catalogue avait 12 entrées (available/available_vf/available_vo_tracking/vo_only/
# vf_available/episode_track/partially_available/language_*) qui décrivaient toutes des
# variantes d'un seul évènement réel : "la disponibilité a changé". Elles sont désormais
# fusionnées dans "available", avec un contexte structuré (scope/language/is_upgrade/
# season_number/episode_number) porté par la queue au lieu d'un texte libre reparsé.
EVENTS: dict[str, NotificationEvent] = {
    "request": NotificationEvent(
        key="request",
        label="Nouvelle demande",
        group="Demandes",
        description="Confirmation envoyée quand une demande est enregistrée.",
        color=0xE5A00D,
        badge_class="bg-primary",
        mail_flags=("request_mail_sent",),
        template_field="email_request_template",
        subject_field="email_request_subject",
        default_subject="[Plexarr] Nouvelle demande : {titre}",
    ),
    "available": NotificationEvent(
        key="available",
        label="Disponibilité",
        group="Disponibilité",
        description=(
            "Un média (ou un épisode/une saison suivie) est disponible sur Plex — VO, VF, "
            "amélioration VO→VF, ou jalon de série, selon le contexte."
        ),
        color=0x1DB954,
        badge_class="bg-success",
        mail_flags=("available_mail_sent",),
        template_field="email_available_template",
        subject_field="email_available_subject",
        default_subject="[Plexarr] Disponible : {titre} {langue}",
        preview_context={
            "scope": "episode",
            "language": "vf",
            "is_upgrade": False,
            "season_number": 2,
            "episode_number": 1,
        },
    ),
    "failed": NotificationEvent(
        key="failed",
        label="Échec de transmission",
        group="Demandes",
        description="La demande n'a pas pu être transmise à Sonarr ou Radarr.",
        color=0xDC3545,
        badge_class="bg-danger",
        template_field="email_failure_template",
        subject_field="email_failure_subject",
        default_subject="[Plexarr] Échec de transmission : {titre}",
        preview_context={"reason": "Le serveur Sonarr (ou Radarr) est inaccessible ou a renvoyé une erreur 500."},
    ),
}

UNKNOWN_EVENT = NotificationEvent(
    key="unknown",
    label="Événement inconnu",
    group="Autre",
    description="Ancien événement ou événement non catalogué.",
)

# Anciennes clés persistées dans NotificationLog.event avant la fusion du catalogue
# (voir commentaire au-dessus d'EVENTS) — ne correspondent plus à un évènement
# réellement enqueué aujourd'hui, mais restent en base pour l'historique. Un simple
# libellé lisible, dérivé de "available", au lieu de tomber sur UNKNOWN_EVENT.
LEGACY_EVENT_LABELS: dict[str, str] = {
    "episode_track": "Suivi épisode (sans distinction de langue)",
    "vo_only": "Disponible en VO",
    "vf_available": "VF disponible (mise à jour)",
    "available_vf": "Disponible en VF",
    "available_vo_tracking": "Disponible en VO, VF suivie",
    "partially_available": "Disponibilité partielle",
    "language_vo": "Disponible en VO",
    "language_vf": "Disponible en VF",
}


def get_event(key: str) -> NotificationEvent:
    if key in EVENTS:
        return EVENTS[key]
    legacy_label = LEGACY_EVENT_LABELS.get(key)
    if legacy_label:
        base = EVENTS["available"]
        return replace(
            base,
            key=key,
            label=legacy_label,
            description=f"Ancien évènement (fusionné depuis dans « {base.label} »).",
        )
    return UNKNOWN_EVENT


def event_label(key: str) -> str:
    return get_event(key).label


def event_badge_class(key: str) -> str:
    return get_event(key).badge_class


def event_color(key: str) -> int:
    return get_event(key).color


def event_mail_flags(key: str) -> tuple[str, ...]:
    return get_event(key).mail_flags


def template_fields() -> list[str]:
    fields: list[str] = []
    for event in EVENTS.values():
        for field_name in (event.template_field, event.subject_field):
            if field_name and field_name not in fields:
                fields.append(field_name)
    return fields
