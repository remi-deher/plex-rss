import json
import os
import sqlite3
import tempfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy
from starlette.background import BackgroundTask

from ..crypto import EncryptedText
from ..database import DATABASE_URL, get_db_async
from ..dependencies import require_admin
from ..models import (
    AdminActionLog,
    ArrInstance,
    DownloadClient,
    DownloadHistory,
    LibraryItem,
    MediaIssue,
    MediaRequest,
    NotificationLog,
    NotificationMilestone,
    PasskeyCredential,
    PlexUser,
    PollHistory,
    SearchCache,
    Settings,
    VfEpisodeStatus,
)
from ..utils import now_utc

router = APIRouter(prefix="/api", tags=["import-export"], dependencies=[Depends(require_admin)])

EXPORT_VERSION = 2

# Champs non chiffrés mais toujours liés à l'authentification admin : jamais exportés ni
# importables via ce mécanisme, en plus des colonnes EncryptedText détectées automatiquement.
_ALWAYS_EXCLUDED = {
    "auth_username",
    "auth_password_hash",
}

# Tables incluses dans l'export pour référence/consultation, mais jamais réimportées : soit
# des journaux/historiques sans clé de fusion sûre entre deux installations différentes (les
# id autoincrement sont locaux à chaque base), soit des données régénérées automatiquement par
# les jobs planifiés (cache VF, sync bibliothèque).
_REFERENCE_ONLY_MODELS = {
    "notification_logs": NotificationLog,
    "admin_action_logs": AdminActionLog,
    "notification_milestones": NotificationMilestone,
    "poll_history": PollHistory,
    "download_history": DownloadHistory,
    "media_issues": MediaIssue,
    "library_items": LibraryItem,
    "vf_episode_status": VfEpisodeStatus,
    "search_cache": SearchCache,
}


def _secret_columns(model) -> set[str]:
    """Colonnes EncryptedText d'un modèle : détection automatique des champs sensibles,
    pour ne plus dépendre d'une liste codée en dur qui prend du retard à chaque nouveau
    secret ajouté au modèle."""
    return {c.name for c in model.__table__.columns if isinstance(c.type, EncryptedText)}


def _row(obj, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


def _sqlite_path() -> str:
    if not DATABASE_URL.startswith("sqlite"):
        raise HTTPException(400, "Backup binaire disponible uniquement pour SQLite")
    return DATABASE_URL.replace("sqlite:///", "", 1)


def _coerce_value(model, key: str, value):
    """Convertit une valeur JSON (str/int/bool/None) vers le type Python attendu par la
    colonne SQLAlchemy correspondante, tolérant les représentations texte (formulaires JSON
    exportés par une version antérieure de l'app, ou édités à la main)."""
    column = model.__table__.columns.get(key)
    if column is None or value is None:
        return value
    try:
        py_type = column.type.python_type
    except NotImplementedError:
        return value
    if py_type is bool and isinstance(value, str):
        return value.lower() in ("true", "1", "on", "yes")
    if py_type is int and not isinstance(value, bool):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    if py_type is float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if py_type is datetime and isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _apply_fields(obj, model, data: dict, skip: frozenset[str] = frozenset({"id"})) -> None:
    for k, v in data.items():
        if k in skip or not hasattr(obj, k):
            continue
        if k == "smtp_password" and not v:
            continue  # ne jamais écraser un mot de passe existant par une valeur vide
        setattr(obj, k, _coerce_value(model, k, v))


@router.get("/export")
async def export_data(include_secrets: bool = False, db: AsyncSession = Depends(get_db_async)):
    s = (await db.execute(select(Settings))).scalars().first()
    users = (await db.execute(select(PlexUser))).scalars().all()
    requests = (await db.execute(select(MediaRequest))).scalars().all()
    arr_instances = (await db.execute(select(ArrInstance))).scalars().all()
    download_clients = (await db.execute(select(DownloadClient))).scalars().all()
    passkeys = (await db.execute(select(PasskeyCredential))).scalars().all()
    users_by_id = {u.id: u.plex_user_id for u in users}

    def secret_exclude(model) -> set[str]:
        return set() if include_secrets else _secret_columns(model)

    settings_row = _row(s, exclude={"id", *_ALWAYS_EXCLUDED, *secret_exclude(Settings)}) if s else {}
    payload = {
        "version": EXPORT_VERSION,
        "exported_at": now_utc().isoformat(),
        "settings": settings_row,
        "users": [_row(u, exclude=secret_exclude(PlexUser)) for u in users],
        "requests": [_row(r) for r in requests],
        "arr_instances": [_row(i, exclude={"id", *secret_exclude(ArrInstance)}) for i in arr_instances],
        "download_clients": [_row(c, exclude={"id", *secret_exclude(DownloadClient)}) for c in download_clients],
        "passkey_credentials": [
            {
                **_row(p, exclude={"id", "user_id", *secret_exclude(PasskeyCredential)}),
                "plex_user_id": users_by_id.get(p.user_id),
            }
            for p in passkeys
        ],
        # Référence seulement — non réimportées (voir _REFERENCE_ONLY_MODELS).
        **{key: [_row(o) for o in (await db.execute(select(model))).scalars().all()] for key, model in _REFERENCE_ONLY_MODELS.items()},
    }

    content = json.dumps(payload, indent=2, default=str)
    suffix = "-avec-identifiants" if include_secrets else ""
    filename = f"plex-rss-export{suffix}-{now_utc().strftime('%Y%m%d-%H%M%S')}.json"
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/backup/db")
def backup_database():
    """Backup binaire complet via l'API native sqlite3.Connection.backup() : cohérent même
    en mode WAL (lit l'état logique via le protocole SQLite, pas besoin de copier les
    fichiers -wal/-shm séparément). Contient tout, y compris les secrets en clair si aucune
    clé de chiffrement (PLEXARR_ENCRYPTION_KEY) n'est configurée — à traiter comme sensible."""
    src_path = _sqlite_path()
    if not os.path.exists(src_path):
        raise HTTPException(404, "Fichier de base introuvable")

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(500, f"Échec du backup : {e}")

    filename = f"plex-rss-backup-{now_utc().strftime('%Y%m%d-%H%M%S')}.db"
    return FileResponse(
        tmp_path,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_async),
):
    content = await file.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Fichier JSON invalide")

    if payload.get("version") not in (1, 2):
        raise HTTPException(400, f"Version d'export non supportée : {payload.get('version')}")

    stats = {
        "settings": False,
        "users_upserted": 0,
        "requests_upserted": 0,
        "arr_instances_upserted": 0,
        "download_clients_upserted": 0,
        "passkeys_upserted": 0,
    }
    errors: list[dict] = []

    def _item_label(data: dict, *keys: str) -> str:
        return " / ".join(str(data.get(k)) for k in keys if data.get(k)) or "?"

    async def _run(table: str, label: str, fn) -> bool:
        """Isole chaque item dans un savepoint : une erreur n'annule que cet item (pas tout
        l'import), et est reportée dans `errors` avec assez de contexte pour la corriger."""
        try:
            async with db.begin_nested():
                await fn()
            return True
        except Exception as e:
            errors.append({"table": table, "item": label, "error": str(e)})
            return False

    # Settings — merge sur la ligne unique
    if payload.get("settings"):

        async def _do_settings():
            s = (await db.execute(select(Settings))).scalars().first()
            if not s:
                s = Settings(id=1)
                db.add(s)
            _apply_fields(s, Settings, {k: v for k, v in payload["settings"].items() if k not in _ALWAYS_EXCLUDED})

        stats["settings"] = await _run("settings", "settings", _do_settings)

    # Users — upsert par plex_user_id
    for u_data in payload.get("users", []):
        uid = u_data.get("plex_user_id")
        if not uid:
            continue

        async def _do_user(u_data=u_data, uid=uid):
            user = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == uid))).scalars().first()
            if not user:
                user = PlexUser()
                db.add(user)
            _apply_fields(user, PlexUser, u_data)

        if await _run("users", _item_label(u_data, "plex_user_id", "display_name"), _do_user):
            stats["users_upserted"] += 1

    # Requests — upsert par (plex_user_id + title + media_type)
    for r_data in payload.get("requests", []):

        async def _do_request(r_data=r_data):
            existing = (
                db.query(MediaRequest)
                .filter(
                    MediaRequest.plex_user_id == r_data.get("plex_user_id"),
                    MediaRequest.title == r_data.get("title"),
                    MediaRequest.media_type == r_data.get("media_type"),
                )
                .first()
            )
            if not existing:
                existing = MediaRequest()
                db.add(existing)
            _apply_fields(existing, MediaRequest, r_data)

        if await _run("requests", _item_label(r_data, "title", "media_type"), _do_request):
            stats["requests_upserted"] += 1

    # Arr instances — upsert par (name, arr_type)
    for a_data in payload.get("arr_instances", []):
        name, arr_type = a_data.get("name"), a_data.get("arr_type")
        if not name or not arr_type:
            continue

        async def _do_arr(a_data=a_data, name=name, arr_type=arr_type):
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.name == name, ArrInstance.arr_type == arr_type))).scalars().first()
            if not inst:
                inst = ArrInstance()
                db.add(inst)
            _apply_fields(inst, ArrInstance, a_data)

        if await _run("arr_instances", _item_label(a_data, "name", "arr_type"), _do_arr):
            stats["arr_instances_upserted"] += 1

    # Download clients — upsert par (name, client_type)
    for c_data in payload.get("download_clients", []):
        name, client_type = c_data.get("name"), c_data.get("client_type")
        if not name or not client_type:
            continue

        async def _do_client(c_data=c_data, name=name, client_type=client_type):
            client = (
                db.query(DownloadClient)
                .filter(DownloadClient.name == name, DownloadClient.client_type == client_type)
                .first()
            )
            if not client:
                client = DownloadClient()
                db.add(client)
            _apply_fields(client, DownloadClient, c_data)

        if await _run("download_clients", _item_label(c_data, "name", "client_type"), _do_client):
            stats["download_clients_upserted"] += 1

    # Passkeys — upsert par credential_id, rattaché à l'utilisateur via plex_user_id
    # (user_id est un id local non portable entre deux bases différentes)
    if payload.get("passkey_credentials"):
        await db.flush()
        user_by_plex_id = {u.plex_user_id: u.id for u in (await db.execute(select(PlexUser))).scalars().all()}
    for p_data in payload.get("passkey_credentials", []):
        credential_id = p_data.get("credential_id")
        target_user_id = user_by_plex_id.get(p_data.get("plex_user_id")) if credential_id else None
        if not credential_id or not target_user_id:
            continue

        async def _do_passkey(p_data=p_data, credential_id=credential_id, target_user_id=target_user_id):
            cred = (await db.execute(select(PasskeyCredential).filter(PasskeyCredential.credential_id == credential_id))).scalars().first()
            if not cred:
                cred = PasskeyCredential(credential_id=credential_id, user_id=target_user_id)
                db.add(cred)
            else:
                cred.user_id = target_user_id
            _apply_fields(cred, PasskeyCredential, {k: v for k, v in p_data.items() if k != "plex_user_id"})

        if await _run("passkey_credentials", _item_label(p_data, "credential_id", "name"), _do_passkey):
            stats["passkeys_upserted"] += 1

    await db.commit()
    return {"status": "ok", "stats": stats, "errors": errors}
