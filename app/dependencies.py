import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import Settings


def get_settings_or_404(db: Session = Depends(get_db)) -> Settings:
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(status_code=404, detail="Paramètres non initialisés")
    return s


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dépendance API : session cookie OU header X-Api-Key."""
    if request.session.get("authenticated"):
        return
    token = request.headers.get("X-Api-Key")
    if token:
        s = db.query(Settings).first()
        if s and s.api_token and hmac.compare_digest(s.api_token, token):
            return
    raise HTTPException(status_code=401, detail="Non authentifié")
