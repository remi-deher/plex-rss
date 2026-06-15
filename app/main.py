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

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .database import init_db
from .log_buffer import install as install_log_buffer
from .notification_queue import start_worker as start_notif_worker
from .notification_queue import stop_worker as stop_notif_worker
from .routers import api, auth, email_templates, importexport, maintenance, pages, webhook
from .routers.pages import RedirectException
from .scheduler import scheduler, start_scheduler
from .services.auth import get_secret_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
install_log_buffer()


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
        start_notif_worker()
        logging.info("Scheduler OK. App ready.")
    except Exception:
        logging.exception("STARTUP FAILED")
        raise
    yield
    stop_notif_worker()
    scheduler.shutdown()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


app = FastAPI(title="Plex RSS Monitor", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)
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
app.include_router(maintenance.router)
