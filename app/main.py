"""
Point d'entrée de l'application FastAPI.

Responsabilités :
- Initialisation de la base de données (migrations Alembic + seed)
- Démarrage et arrêt du scheduler APScheduler
- Montage de tous les routers (pages HTML, API REST, webhook, import/export, templates email)
"""

import asyncio
import json
import logging
import os
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager

import itsdangerous
from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous.exc import BadSignature
from sqlalchemy.orm import Session as SqlSession
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .database import get_db, init_db
from .dependencies import require_admin
from .log_buffer import install as install_log_buffer
from .notification_queue import start_worker as start_notif_worker
from .notification_queue import stop_worker as stop_notif_worker
from .routers import (
    api_v1,
    arr_api,
    auth,
    calendar_api,
    discover_api,
    email_templates,
    importexport,
    library_api,
    maintenance,
    metrics_api,
    misc_api,
    notifications_api,
    pages,
    requests_api,
    security_api,
    settings_api,
    users_api,
    vff_api,
    webhook,
)
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
            # Priorité à l'intervalle en secondes (polling sous la minute) ; repli sur les minutes.
            if _s and _s.poll_interval_seconds:
                _seconds = _s.poll_interval_seconds
            elif _s and _s.poll_interval_minutes:
                _seconds = _s.poll_interval_minutes * 60
            else:
                _seconds = 300
        finally:
            _db.close()

        start_scheduler(poll_seconds=_seconds)
        start_notif_worker()
        logging.info("Scheduler OK. App ready.")
    except Exception:
        logging.exception("STARTUP FAILED")
        raise
    yield
    logging.info("Shutting down: stopping notification worker...")
    await stop_notif_worker()
    logging.info("Shutting down: stopping scheduler (waits for any running job to finish)...")
    scheduler.shutdown()
    logging.info("Shutdown complete.")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


def _sync_session_role(plex_user_id: str | None, username: str | None) -> dict | None:
    """Corps synchrone de la résolution de rôle (exécuté hors event loop via to_thread)."""
    from .database import SessionLocal
    from .models import PlexUser, Settings

    db = SessionLocal()
    try:
        if plex_user_id:
            u = db.query(PlexUser).filter(PlexUser.plex_user_id == plex_user_id).first()
            if u:
                return {"role": u.role or "user", "is_owner": u.role == "admin", "user_id": u.id}
        else:
            u = db.query(PlexUser).filter(PlexUser.plex_user_id == username).first()
            if u:
                return {"role": u.role or "user", "is_owner": u.role == "admin", "user_id": u.id}
            s = db.query(Settings).first()
            if s and s.auth_username and username == s.auth_username:
                return {"role": "admin", "is_owner": True}
        return None
    finally:
        db.close()


class SessionSyncMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.session.get("authenticated"):
            try:
                result = await asyncio.to_thread(
                    _sync_session_role, request.session.get("plex_user_id"), request.session.get("username")
                )
                if result:
                    request.session.update(result)
            except Exception:
                pass
        return await call_next(request)


def _request_is_https(scope: Scope) -> bool:
    """Détecte si la requête d'origine était en HTTPS.

    Couvre deux cas : TLS terminé directement par uvicorn (scope["scheme"]),
    et TLS terminé en amont par un reverse-proxy (Traefik/Caddy/nginx) qui
    transmet l'info via l'en-tête X-Forwarded-Proto.
    """
    if scope.get("scheme") == "https":
        return True
    headers = dict(scope.get("headers") or [])
    proto = headers.get(b"x-forwarded-proto", b"").decode("latin-1").split(",")[0].strip().lower()
    return proto == "https"


class DynamicSecureSessionMiddleware:
    """Équivalent de starlette.middleware.sessions.SessionMiddleware, mais le flag
    `Secure` du cookie de session est déterminé par requête plutôt que figé au
    démarrage. Cela permet un déploiement plug-and-play : le cookie reste
    utilisable en HTTP direct (installation locale sans TLS) tout en devenant
    `Secure` automatiquement dès que l'app est servie en HTTPS, y compris
    derrière un reverse-proxy qui termine le TLS.
    """

    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int = 14 * 24 * 60 * 60,
        path: str = "/",
        same_site: str = "strict",
    ) -> None:
        self.app = app
        self.signer = itsdangerous.TimestampSigner(secret_key)
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.path = path
        self.base_flags = f"httponly; samesite={same_site}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection_cookies = Request(scope).cookies
        initial_session_was_empty = True

        if self.session_cookie in connection_cookies:
            data = connection_cookies[self.session_cookie].encode("utf-8")
            try:
                data = self.signer.unsign(data, max_age=self.max_age)
                scope["session"] = Session(json.loads(b64decode(data)))
                initial_session_was_empty = False
            except BadSignature:
                scope["session"] = Session()
        else:
            scope["session"] = Session()

        security_flags = self.base_flags + ("; secure" if _request_is_https(scope) else "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: Session = scope["session"]
                headers = MutableHeaders(scope=message)
                if session.accessed:
                    headers.add_vary_header("Cookie")
                if session.modified and session:
                    data = b64encode(json.dumps(session).encode("utf-8"))
                    data = self.signer.sign(data)
                    header_value = "{session_cookie}={data}; path={path}; {max_age}{security_flags}".format(
                        session_cookie=self.session_cookie,
                        data=data.decode("utf-8"),
                        path=self.path,
                        max_age=f"Max-Age={self.max_age}; " if self.max_age else "",
                        security_flags=security_flags,
                    )
                    headers.append("Set-Cookie", header_value)
                elif session.modified and not initial_session_was_empty:
                    header_value = "{session_cookie}={data}; path={path}; {expires}{security_flags}".format(
                        session_cookie=self.session_cookie,
                        data="null",
                        path=self.path,
                        expires="expires=Thu, 01 Jan 1970 00:00:00 GMT; ",
                        security_flags=security_flags,
                    )
                    headers.append("Set-Cookie", header_value)
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="Plexarr", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/api/docs", include_in_schema=False)
async def get_documentation(request: Request, db: SqlSession = Depends(get_db)):
    require_admin(request, db)
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Plexarr API Docs")


@app.get("/api/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(request: Request, db: SqlSession = Depends(get_db)):
    require_admin(request, db)
    return get_openapi(title="Plexarr", version="1.0.0", routes=app.routes)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionSyncMiddleware)
# Middleware de session (doit être ajouté avant les routers)
app.add_middleware(DynamicSecureSessionMiddleware, secret_key=get_secret_key())

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(RedirectException)
async def redirect_exception_handler(request, exc: RedirectException):
    return RedirectResponse(exc.path, status_code=302)


app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(settings_api.router)
app.include_router(arr_api.router)
app.include_router(users_api.router)
app.include_router(security_api.router)
app.include_router(requests_api.router)
app.include_router(calendar_api.router)
app.include_router(library_api.router)
app.include_router(discover_api.router)
app.include_router(vff_api.router)
app.include_router(metrics_api.router)
app.include_router(notifications_api.router)
app.include_router(misc_api.router)
app.include_router(api_v1.router)
app.include_router(webhook.router)
app.include_router(importexport.router)
app.include_router(email_templates.router)
app.include_router(maintenance.router)
