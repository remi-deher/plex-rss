"""
Point d'entrée de l'application FastAPI.

Responsabilités :
- Initialisation de la base de données (migrations Alembic + seed)
- Démarrage et arrêt du scheduler APScheduler
- Montage de tous les routers (pages HTML, API REST, webhook, import/export, templates email)
"""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from .database import init_db
from .scheduler import start_scheduler, scheduler
from .routers import pages, api, webhook, importexport, email_templates, auth
from .routers.pages import RedirectException
from .services.auth import get_secret_key
from fastapi.responses import RedirectResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère le cycle de vie de l'application : démarrage et arrêt propre."""
    try:
        os.makedirs("data", exist_ok=True)
        logging.info("Running DB migrations...")
        init_db()
        logging.info("DB OK. Starting scheduler...")

        # Lire l'intervalle de polling depuis la DB avant de lancer le scheduler
        from .database import SessionLocal
        from .models import Settings as _Settings
        _db = SessionLocal()
        try:
            _s = _db.query(_Settings).first()
            _interval = _s.poll_interval_minutes if _s and _s.poll_interval_minutes else 5
        finally:
            _db.close()

        start_scheduler(poll_minutes=_interval)
        logging.info("Scheduler OK. App ready.")
    except Exception:
        logging.exception("STARTUP FAILED")
        raise
    yield
    scheduler.shutdown()


app = FastAPI(title="Plex RSS Monitor", lifespan=lifespan)

# Middleware de session (doit être ajouté avant les routers)
app.add_middleware(SessionMiddleware, secret_key=get_secret_key())


@app.exception_handler(RedirectException)
async def redirect_exception_handler(request, exc: RedirectException):
    return RedirectResponse(exc.path, status_code=302)


app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(api.router)
app.include_router(webhook.router)
app.include_router(importexport.router)
app.include_router(email_templates.router)
