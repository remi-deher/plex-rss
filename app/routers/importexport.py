import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaRequest, PlexUser, Settings


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Non authentifié")


router = APIRouter(prefix="/api", tags=["import-export"], dependencies=[Depends(require_auth)])

EXPORT_VERSION = 1

# Champs d'authentification/secrets : jamais exportés ni importables via ce mécanisme.
# Un import malveillant ne doit pas pouvoir écraser le compte admin ou les jetons actifs.
_SETTINGS_CREDENTIAL_FIELDS = {
    "auth_username",
    "auth_password_hash",
    "api_token",
    "webhook_secret",
}


@router.get("/export")
def export_data(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    users = db.query(PlexUser).all()
    requests = db.query(MediaRequest).all()

    def row(obj, exclude=None):
        exclude = exclude or []
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}

    payload = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": row(s, exclude=["id", *_SETTINGS_CREDENTIAL_FIELDS]) if s else {},
        "users": [row(u) for u in users],
        "requests": [row(r) for r in requests],
    }

    content = json.dumps(payload, indent=2, default=str)
    filename = f"plex-rss-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Fichier JSON invalide")

    if payload.get("version") != EXPORT_VERSION:
        raise HTTPException(400, f"Version d'export non supportée : {payload.get('version')}")

    stats = {"settings": False, "users_upserted": 0, "requests_upserted": 0}

    # Settings — merge (ne pas écraser smtp_password si vide)
    if payload.get("settings"):
        s = db.query(Settings).first()
        if not s:
            s = Settings(id=1)
            db.add(s)
        for k, v in payload["settings"].items():
            if k in _SETTINGS_CREDENTIAL_FIELDS:
                continue
            if hasattr(s, k):
                if k == "smtp_password" and not v:
                    continue
                # Forcer les types appropriés pour la DB
                column = Settings.__table__.columns.get(k)
                if column is not None:
                    if column.type.python_type is bool and isinstance(v, str):
                        v = v.lower() in ("true", "1", "on", "yes")
                    elif column.type.python_type is int and v is not None:
                        try:
                            v = int(v)
                        except (ValueError, TypeError):
                            v = None
                setattr(s, k, v)
        stats["settings"] = True

    # Users — upsert par plex_user_id
    for u_data in payload.get("users", []):
        uid = u_data.get("plex_user_id")
        if not uid:
            continue
        user = db.query(PlexUser).filter(PlexUser.plex_user_id == uid).first()
        if not user:
            user = PlexUser()
            db.add(user)
        for k, v in u_data.items():
            if hasattr(user, k) and k != "id":
                column = PlexUser.__table__.columns.get(k)
                if column is not None:
                    # Convertir les dates en objets datetime
                    if column.type.python_type is datetime and isinstance(v, str) and v:
                        try:
                            v = datetime.fromisoformat(v)
                        except ValueError:
                            pass
                    elif column.type.python_type is bool and isinstance(v, str):
                        v = v.lower() in ("true", "1", "on", "yes")
                setattr(user, k, v)
        stats["users_upserted"] += 1

    # Requests — upsert par (plex_user_id + title + media_type)
    for r_data in payload.get("requests", []):
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
        for k, v in r_data.items():
            if hasattr(existing, k) and k != "id":
                column = MediaRequest.__table__.columns.get(k)
                if column is not None:
                    # Convertir les dates en objets datetime
                    if column.type.python_type is datetime and isinstance(v, str) and v:
                        try:
                            v = datetime.fromisoformat(v)
                        except ValueError:
                            pass
                    elif column.type.python_type is bool and isinstance(v, str):
                        v = v.lower() in ("true", "1", "on", "yes")
                    elif column.type.python_type is int and v is not None:
                        try:
                            v = int(v)
                        except (ValueError, TypeError):
                            v = None
                setattr(existing, k, v)
        stats["requests_upserted"] += 1

    db.commit()
    return {"status": "ok", "stats": stats}
