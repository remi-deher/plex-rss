from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Settings


def get_settings_or_404(db: Session = Depends(get_db)) -> Settings:
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(status_code=404, detail="Paramètres non initialisés")
    return s
