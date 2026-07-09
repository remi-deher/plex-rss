from __future__ import annotations

from dataclasses import dataclass, field
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
        default_subject="[Plexarr] Nouvelle demande : {{ title }}",
    ),
    "available": NotificationEvent(
        key="available",
        label="Disponible sur Plex",
        group="Disponibilité",
        description="Disponibilité classique sans détail VO/VF fusionné.",
        color=0x1DB954,
        badge_class="bg-success",
        mail_flags=("available_mail_sent",),
        template_field="email_available_template",
        subject_field="email_available_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex !",
    ),
    "available_vf": NotificationEvent(
        key="available_vf",
        label="Disponible en VF",
        group="Disponibilité films",
        description="Premier mail de disponibilité quand le média est déjà en VF.",
        color=0x1DB954,
        badge_class="bg-success",
        mail_flags=("available_mail_sent",),
        template_field="email_available_vf_template",
        subject_field="email_available_vf_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex en VF !",
        preview_context={"media_type": "movie", "media_type_label": "Film", "media_type_label_cap": "Le film"},
    ),
    "available_vo_tracking": NotificationEvent(
        key="available_vo_tracking",
        label="Disponible en VO",
        group="Suivi VO/VF",
        description="Premier mail de disponibilité VO quand Plexarr continue à suivre l'arrivée de la VF.",
        color=0x0D6EFD,
        badge_class="bg-info",
        mail_flags=("available_mail_sent", "vo_only_mail_sent"),
        template_field="email_available_vo_tracking_template",
        subject_field="email_available_vo_tracking_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex en VO !",
        preview_context={
            "media_type": "movie",
            "media_type_label": "Film",
            "media_type_label_cap": "Le film",
            "language": "VO",
            "language_lower": "vo",
            "language_reason": "VO film complet",
        },
    ),
    "vo_only": NotificationEvent(
        key="vo_only",
        label="Jalon VO",
        group="Suivi VO/VF",
        description="Jalon VO pour les séries ou suivi VO indépendant.",
        color=0x0D6EFD,
        badge_class="bg-info",
        mail_flags=("vo_only_mail_sent",),
        preview_context={"language": "VO", "language_lower": "vo", "language_reason": "VO saison 1 démarrée"},
    ),
    "vf_available": NotificationEvent(
        key="vf_available",
        label="VF ajoutée plus tard",
        group="Suivi VO/VF",
        description="Upgrade VF après une première disponibilité VO.",
        color=0x1DB954,
        badge_class="bg-success",
        mail_flags=("vf_available_mail_sent",),
        template_field="email_vf_upgrade_template",
        subject_field="email_vf_upgrade_subject",
        default_subject="[Plexarr] {{ title }} est désormais disponible sur Plex en VF !",
        preview_context={
            "media_type": "movie",
            "media_type_label": "Film",
            "media_type_label_cap": "Le film",
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF film complet",
        },
    ),
    "vf_upgrade": NotificationEvent(
        key="vf_upgrade",
        label="VF ajoutée plus tard",
        group="Templates",
        description="Template utilisé par l'événement VF ajoutée plus tard.",
        color=0x1DB954,
        badge_class="bg-success",
        template_field="email_vf_upgrade_template",
        subject_field="email_vf_upgrade_subject",
        default_subject="[Plexarr] {{ title }} est désormais disponible sur Plex en VF !",
        preview_context={
            "media_type": "movie",
            "media_type_label": "Film",
            "media_type_label_cap": "Le film",
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF film complet",
        },
    ),
    "episode_track": NotificationEvent(
        key="episode_track",
        label="Jalon série",
        group="Jalons séries",
        description="Nouvel épisode, début de saison, saison complète ou série complète.",
        color=0x0D6EFD,
        badge_class="bg-info",
    ),
    "partially_available": NotificationEvent(
        key="partially_available",
        label="Disponibilité partielle",
        group="Jalons séries",
        description="Série en cours de diffusion avec seulement une partie des épisodes disponible.",
        color=0xE5A00D,
        badge_class="bg-warning text-dark",
        mail_flags=("partial_available_mail_sent",),
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
        default_subject="[Plexarr] Échec de transmission : {{ title }}",
    ),
    "failure": NotificationEvent(
        key="failure",
        label="Échec de transmission",
        group="Templates",
        description="Template utilisé pour les échecs de transmission.",
        color=0xDC3545,
        badge_class="bg-danger",
        template_field="email_failure_template",
        subject_field="email_failure_subject",
        default_subject="[Plexarr] Échec de transmission : {{ title }}",
    ),
    "language_episode": NotificationEvent(
        key="language_episode",
        label="Épisode",
        group="Jalons séries",
        description="Notification pour un nouvel épisode suivi.",
        color=0x0D6EFD,
        badge_class="bg-info",
        template_field="email_language_episode_template",
        subject_field="email_language_episode_subject",
        default_subject="[Plexarr] {{ title }} : nouvel épisode{% if language %} en {{ language }}{% endif %} sur Plex !",
        media_scope=("show",),
        preview_context={
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF S01E02",
            "language_milestone_type": "episode",
        },
    ),
    "language_season_start": NotificationEvent(
        key="language_season_start",
        label="Début saison",
        group="Jalons séries",
        description="Notification quand une saison suivie démarre.",
        color=0x0D6EFD,
        badge_class="bg-info",
        template_field="email_language_season_start_template",
        subject_field="email_language_season_start_subject",
        default_subject="[Plexarr] {{ title }} : saison démarrée{% if language %} en {{ language }}{% endif %} sur Plex !",
        media_scope=("show",),
        preview_context={
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF saison 1 démarrée",
            "language_milestone_type": "season_start",
        },
    ),
    "language_season_complete": NotificationEvent(
        key="language_season_complete",
        label="Saison complète",
        group="Jalons séries",
        description="Notification quand une saison suivie est complète.",
        color=0x1DB954,
        badge_class="bg-success",
        template_field="email_language_season_complete_template",
        subject_field="email_language_season_complete_subject",
        default_subject="[Plexarr] {{ title }} : saison complète{% if language %} en {{ language }}{% endif %} sur Plex !",
        media_scope=("show",),
        preview_context={
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF saison 1 complète",
            "language_milestone_type": "season_complete",
        },
    ),
    "language_series_complete": NotificationEvent(
        key="language_series_complete",
        label="Série complète",
        group="Jalons séries",
        description="Notification quand la série suivie est complète.",
        color=0x1DB954,
        badge_class="bg-success",
        template_field="email_language_series_complete_template",
        subject_field="email_language_series_complete_subject",
        default_subject="[Plexarr] {{ title }} est entièrement disponible{% if language %} en {{ language }}{% endif %} sur Plex !",
        media_scope=("show",),
        preview_context={
            "language": "VF",
            "language_lower": "vf",
            "language_reason": "VF série complète",
            "language_milestone_type": "series_complete",
        },
    ),
}

UNKNOWN_EVENT = NotificationEvent(
    key="unknown",
    label="Événement inconnu",
    group="Autre",
    description="Ancien événement ou événement non catalogué.",
)


def get_event(key: str) -> NotificationEvent:
    return EVENTS.get(key) or UNKNOWN_EVENT


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
