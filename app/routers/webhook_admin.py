"""Diagnostic et configuration des webhooks Sonarr/Radarr/Plex (reserve aux admins).

Separe de webhook.py, qui ne fait plus que recevoir les evenements : ces endpoints
parlent a Sonarr/Radarr pour inspecter et ecrire leurs connecteurs, une responsabilite
sans rapport avec le traitement d'un evenement entrant.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..dependencies import require_admin
from ..models import ArrInstance, Settings
from ..services import radarr, sonarr
from ..utils import now_utc_naive, safe_error_message
from .webhook import _resolve_arr_connection
from .webhook_state import last_webhook_test as _last_webhook_test

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


@router.get("/status", dependencies=[Depends(require_admin)])
def webhook_status():
    """Retourne le statut des derniers tests reçus pour chaque webhook."""

    def _fmt(dt: datetime | None) -> dict:
        if dt is None:
            return {"received": False, "at": None, "ago_seconds": None}
        ago = (datetime.now(timezone.utc) - dt).total_seconds()
        return {"received": True, "at": dt.isoformat(), "ago_seconds": int(ago)}

    return {
        "sonarr": _fmt(_last_webhook_test["sonarr"]),
        "radarr": _fmt(_last_webhook_test["radarr"]),
        "plex": _fmt(_last_webhook_test["plex"]),
    }

async def _check_live_plex() -> dict:
    """Vérifie l'état du webhook Plex à partir du dernier événement réellement reçu.

    Contrairement à Sonarr/Radarr, Plex n'expose pas d'API fiable pour déclencher un envoi
    de test à distance (l'ancien endpoint `/:/webhooks` renvoie une 404 sur les versions
    récentes) ni pour lister les webhooks enregistrés — impossible de confirmer
    l'enregistrement sans risquer un faux diagnostic. On se limite donc au signal fiable
    dont on dispose déjà : le dernier événement réel reçu par `/webhook/plex` (mis à jour
    à chaque webhook Plex traité, y compris le ping de connectivité envoyé par Plex à
    l'enregistrement de l'URL).
    """
    db: AsyncSession = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
    finally:
        await db.close()
    if not settings or not settings.plex_url or not settings.plex_token:
        return {
            "instance": "Plex",
            "configured": False,
            "success": False,
            "message": "Plex non configuré (URL ou token manquant)",
        }

    last = _last_webhook_test.get("plex")
    if last:
        ago = int((datetime.now(timezone.utc) - last).total_seconds())
        return {
            "instance": "Plex",
            "configured": True,
            "success": True,
            "message": f"Dernier événement Plex reçu il y a {ago}s — le webhook fonctionne.",
        }
    return {
        "instance": "Plex",
        "configured": False,
        "success": False,
        "message": (
            "Aucun événement Plex reçu pour l'instant. Vérifie que l'URL ci-dessus est bien "
            "collée dans Plex → Paramètres → Webhooks, puis lis un média ou ajoute-en un à la "
            "bibliothèque pour déclencher un vrai événement (Plex ne permet pas de test à "
            "distance, contrairement à Sonarr/Radarr)."
        ),
    }

@router.post("/check-live/{service}", dependencies=[Depends(require_admin)])
async def check_live_webhook(service: str, instance_id: int | None = None):
    """Déclenche depuis Sonarr/Radarr un test réel du connecteur Webhook pointant vers cette app.

    Contrairement à /webhook/status (qui attend passivement un événement Test), cet endpoint
    interroge l'API Sonarr/Radarr pour retrouver le connecteur Webhook configuré (Settings →
    Connect) et lui fait déclencher lui-même un envoi de test, confirmant en direct que la
    notification temps réel fonctionnera bien à la disponibilité d'un média. Pour Plex — qui
    n'expose aucune API fiable de déclenchement à distance ni de lister ses webhooks —
    rapporte à la place le dernier événement réel reçu (voir `_check_live_plex`).
    """
    if service == "plex":
        return {"results": [await _check_live_plex()]}
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr', 'radarr' ou 'plex'")

    client = sonarr if service == "sonarr" else radarr
    webhook_path = f"/webhook/{service}"

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {
                "results": [
                    {"instance": None, "configured": False, "success": False, "message": "Aucune instance configurée"}
                ]
            }

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id, "url": inst.url}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": f"Connexion à {service.capitalize()} impossible : {e}",
                    }
                )
                results.append(entry)
                continue

            match = client.find_webhook_notification(notifications, webhook_path)
            if not match:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": (
                            f"Aucun connecteur Webhook pointant vers {webhook_path} trouvé dans "
                            f"{service.capitalize()} → Connexions"
                        ),
                    }
                )
                results.append(entry)
                continue

            ok, msg = await client.test_notification(inst.url, inst.api_key, match)
            entry.update({"configured": True, "success": ok, "message": msg})
            if ok:
                _last_webhook_test[service] = datetime.now(timezone.utc)
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()

_WEBHOOK_EVENT_FLAGS: dict[str, dict[str, bool]] = {
    # Evenements requis pour que webhook.py traite correctement les notifications (voir
    # sonarr_webhook/radarr_webhook ci-dessus : eventType in ("Download", "Import") pour la
    # disponibilite/scan VF, "SeriesDelete"/"EpisodeFileDelete" ou "MovieDelete"/
    # "MovieFileDelete" pour le nettoyage des demandes supprimees).
    "sonarr": {
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onImportComplete": True,
        "onRename": False,
        "onSeriesAdd": False,
        "onSeriesDelete": True,
        "onEpisodeFileDelete": True,
        "onEpisodeFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
    },
    "radarr": {
        # Pas de "onImportComplete" ici : contrairement a Sonarr (imports multi-episodes
        # partiels), Radarr n'expose pas cette notion — verifie en direct sur une instance
        # reelle, son schema renvoie `supportsOnImportComplete: null` et le champ revient
        # systematiquement a `null` apres ecriture. L'inclure ici faisait boucler
        # "Configurer automatiquement" en boucle sur "corrige" a chaque clic, la comparaison
        # (null != True) semblant toujours en desaccord alors que rien n'est reellement a
        # corriger.
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onRename": False,
        "onMovieAdded": False,
        "onMovieDelete": True,
        "onMovieFileDelete": True,
        "onMovieFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
    },
}

class ConfigureWebhookRequest(BaseModel):
    webhook_url: str

@router.post("/configure/{service}", dependencies=[Depends(require_admin)])
async def configure_webhook(service: str, body: ConfigureWebhookRequest, instance_id: int | None = None):
    """Crée ou corrige automatiquement le connecteur Webhook Sonarr/Radarr pointant vers cette app.

    Si un connecteur webhook existe déjà (retrouvé via l'URL /webhook/{service}) mais avec des
    événements manquants (cas réel rencontré : "On Download" désactivé, empêchant toute
    notification lors d'un import automatique classique), il est corrigé en place. Sinon un
    nouveau connecteur est créé à partir du schéma Sonarr/Radarr, avec uniquement les
    événements dont webhook.py a besoin pour fonctionner.
    """
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr' ou 'radarr'")

    client = sonarr if service == "sonarr" else radarr
    webhook_path = f"/webhook/{service}"
    desired_flags = _WEBHOOK_EVENT_FLAGS[service]

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {"results": [{"instance": None, "success": False, "message": "Aucune instance configurée"}]}

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update({"success": False, "message": f"Connexion à {service.capitalize()} impossible : {e}"})
                results.append(entry)
                continue

            try:
                existing = client.find_webhook_notification(notifications, webhook_path)
                if existing:
                    changed = False
                    for key, val in desired_flags.items():
                        if existing.get(key) != val:
                            existing[key] = val
                            changed = True
                    for field in existing.get("fields", []):
                        if field.get("name") == "url" and field.get("value") != body.webhook_url:
                            field["value"] = body.webhook_url
                            changed = True
                    if changed:
                        await client.update_notification(inst.url, inst.api_key, existing)
                        entry.update({"success": True, "message": "Connecteur existant corrigé (événements manquants activés)."})
                    else:
                        entry.update({"success": True, "message": "Déjà correctement configuré."})
                else:
                    schema = await client.get_webhook_schema(inst.url, inst.api_key)
                    if not schema:
                        entry.update({"success": False, "message": "Schéma du connecteur Webhook introuvable."})
                        results.append(entry)
                        continue
                    payload = client.build_webhook_payload(schema, body.webhook_url, desired_flags)
                    await client.create_notification(inst.url, inst.api_key, payload)
                    entry.update({"success": True, "message": "Connecteur webhook créé."})
            except Exception as e:
                entry.update({"success": False, "message": str(e)})
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()

@router.get("/plex-connector-status/{service}", dependencies=[Depends(require_admin)])
async def plex_connector_status(service: str, instance_id: int | None = None):
    """Vérifie si Sonarr/Radarr a déjà un connecteur natif "Plex Media Server" actif.

    Si oui, notre propre refresh de section Plex (déclenché à chaque webhook Download/
    Import, voir `trigger_plex_library_refresh`) est redondant : l'*arr notifie déjà Plex
    directement avec un scan ciblé sur le dossier importé, plus précis que le nôtre.
    """
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr' ou 'radarr'")

    client = sonarr if service == "sonarr" else radarr

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {
                "results": [
                    {"instance": None, "configured": False, "success": False, "message": "Aucune instance configurée"}
                ]
            }

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": f"Connexion à {service.capitalize()} impossible : {e}",
                    }
                )
                results.append(entry)
                continue

            match = client.find_plex_notification(notifications)
            if match:
                entry.update(
                    {
                        "configured": True,
                        "success": True,
                        "message": (
                            f"Connecteur natif 'Plex Media Server' actif dans {service.capitalize()} — "
                            "notre propre refresh de section est automatiquement désactivé pour cette instance."
                        ),
                    }
                )
            else:
                entry.update(
                    {
                        "configured": False,
                        "success": True,
                        "message": (
                            f"Aucun connecteur natif Plex trouvé dans {service.capitalize()} → Connexions — "
                            "notre refresh de section Plex prend le relais à chaque import."
                        ),
                    }
                )
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()
