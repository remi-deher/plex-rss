"""Effacement des données personnelles d'une personne concernée (Art. 17 RGPD).

Les données d'un utilisateur sont dispersées dans plusieurs tables reliées par
`plex_user_id` / `recipient` en texte, **sans clé étrangère ni cascade** : supprimer
la seule ligne `PlexUser` laisserait derrière elle son email (journaux de
notification), ses demandes et ses signalements. `erase_user_data` centralise la purge
de toutes ces traces pour que « supprimer un utilisateur » corresponde réellement à la
promesse d'effacement affichée sur la page /privacy.

Les tentatives de connexion (`LoginAttempt`, avec adresse IP) ne sont volontairement
pas traitées ici : elles ne sont pas rattachables de façon fiable à une personne
(clé = IP + username de formulaire), et relèvent de la purge par rétention temporelle
(voir services/notification_orchestrator._purge_notification_logs).
"""

import json
import logging

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import EncryptedText
from ..models import (
    MediaIssue,
    MediaRequest,
    NotificationLog,
    NotificationMilestone,
    PasskeyCredential,
    PlexUser,
)
from ..utils import now_utc

logger = logging.getLogger(__name__)


def _row_without_secrets(obj) -> dict:
    """Sérialise une ligne ORM en dict, en excluant les colonnes chiffrées
    (EncryptedText) : un export de droit d'accès ne doit jamais révéler de secret
    (totp_secret, tokens...). Détection automatique, pas de liste codée en dur."""
    return {
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if not isinstance(c.type, EncryptedText)
    }


async def _scrub_co_requester(db: AsyncSession, plex_user_id: str) -> int:
    """Retire la personne des `extra_requesters` (co-demandeur) des demandes d'autrui.

    Le pré-filtre LIKE est un simple param bindé (pas de concaténation SQL) ; le vrai
    filtrage exact se fait ensuite en Python, donc un faux positif LIKE est sans effet.
    """
    rows = (
        await db.execute(
            sqlalchemy.select(MediaRequest).where(
                MediaRequest.extra_requesters.like(f"%{plex_user_id}%")
            )
        )
    ).scalars().all()
    scrubbed = 0
    for req in rows:
        try:
            extras = json.loads(req.extra_requesters or "[]")
        except (ValueError, TypeError):
            continue
        filtered = [e for e in extras if e.get("plex_user_id") != plex_user_id]
        if len(filtered) != len(extras):
            req.extra_requesters = json.dumps(filtered, ensure_ascii=False)
            scrubbed += 1
    return scrubbed


async def erase_user_data(db: AsyncSession, user: PlexUser) -> dict[str, int]:
    """Efface toutes les données personnelles rattachées à `user`, hors la ligne PlexUser.

    Ne fait PAS `db.delete(user)` ni `db.commit()` : l'appelant supprime la ligne
    utilisateur et valide la transaction, pour que l'effacement des traces et la
    suppression du compte forment une seule opération atomique.
    """
    plex_user_id = user.plex_user_id
    emails = {e for e in (user.plex_email, user.notification_email) if e}
    counts: dict[str, int] = {}

    # Passkeys : la FK ondelete=CASCADE n'est pas garantie sous SQLite (PRAGMA
    # foreign_keys off par défaut), on supprime donc explicitement.
    result = await db.execute(
        sqlalchemy.delete(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
    )
    counts["passkeys"] = int(result.rowcount or 0)

    result = await db.execute(
        sqlalchemy.delete(MediaRequest).where(MediaRequest.plex_user_id == plex_user_id)
    )
    counts["requests"] = int(result.rowcount or 0)

    counts["co_requester_scrubbed"] = await _scrub_co_requester(db, plex_user_id)

    result = await db.execute(
        sqlalchemy.delete(NotificationMilestone).where(
            NotificationMilestone.plex_user_id == plex_user_id
        )
    )
    counts["milestones"] = int(result.rowcount or 0)

    if emails:
        result = await db.execute(
            sqlalchemy.delete(NotificationLog).where(NotificationLog.recipient.in_(emails))
        )
        counts["notification_logs"] = int(result.rowcount or 0)
    else:
        counts["notification_logs"] = 0

    result = await db.execute(
        sqlalchemy.delete(MediaIssue).where(MediaIssue.reporter_plex_user_id == plex_user_id)
    )
    counts["media_issues"] = int(result.rowcount or 0)

    logger.info("Effacement RGPD user_id=%s : %s", user.id, counts)
    return counts


async def export_user_data(db: AsyncSession, user: PlexUser) -> dict:
    """Construit l'export des données d'une seule personne concernée (Art. 15 & 20).

    Sous-ensemble ciblé (contrairement à /api/export qui exporte toute l'instance) :
    profil, demandes, journaux de notification (par email destinataire), jalons,
    signalements et passkeys — sans aucun secret. Format JSON réutilisable.
    """
    plex_user_id = user.plex_user_id
    emails = {e for e in (user.plex_email, user.notification_email) if e}

    requests = (
        await db.execute(sqlalchemy.select(MediaRequest).where(MediaRequest.plex_user_id == plex_user_id))
    ).scalars().all()
    milestones = (
        await db.execute(
            sqlalchemy.select(NotificationMilestone).where(NotificationMilestone.plex_user_id == plex_user_id)
        )
    ).scalars().all()
    issues = (
        await db.execute(sqlalchemy.select(MediaIssue).where(MediaIssue.reporter_plex_user_id == plex_user_id))
    ).scalars().all()
    passkeys = (
        await db.execute(sqlalchemy.select(PasskeyCredential).where(PasskeyCredential.user_id == user.id))
    ).scalars().all()
    if emails:
        logs = (
            await db.execute(sqlalchemy.select(NotificationLog).where(NotificationLog.recipient.in_(emails)))
        ).scalars().all()
    else:
        logs = []

    return {
        "export_type": "data_subject_access_request",
        "generated_at": now_utc().isoformat(),
        "subject": _row_without_secrets(user),
        "requests": [_row_without_secrets(r) for r in requests],
        "notification_logs": [_row_without_secrets(row) for row in logs],
        "notification_milestones": [_row_without_secrets(m) for m in milestones],
        "media_issues": [_row_without_secrets(i) for i in issues],
        # Passkeys : seulement le nom et la date, jamais la clé publique ni le compteur.
        "passkeys": [{"name": p.name, "created_at": p.created_at} for p in passkeys],
    }
