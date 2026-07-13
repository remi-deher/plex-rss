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
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous.exc import BadSignature
from sqlalchemy.ext.asyncio import AsyncSession as SqlSession
from sqlalchemy.future import select
import sqlalchemy
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .database import get_db_async as get_db, init_db
from .cache import cache
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
    events_api,
    importexport,
    library_api,
    maintenance,
    metrics_api,
    misc_api,
    notifications_api,
    requests_api,
    security_api,
    settings_api,
    users_api,
    vff_api,
    webhook,
)
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
        await init_db()
        logging.info("DB OK. Starting API services...")

        # Lire l'intervalle de polling depuis la DB avant de lancer le scheduler
        from .database import AsyncSessionLocal
        from .models import Settings as _Settings

        _db = AsyncSessionLocal()
        try:
            _s = (await _db.execute(select(_Settings))).scalars().first()
            # Priorité à l'intervalle en secondes (polling sous la minute) ; repli sur les minutes.
            if _s and _s.poll_interval_seconds:
                _seconds = _s.poll_interval_seconds
            elif _s and _s.poll_interval_minutes:
                _seconds = _s.poll_interval_minutes * 60
            else:
                _seconds = 300
        finally:
            await _db.close()

        legacy_scheduler = os.getenv("ENABLE_LEGACY_SCHEDULER", "0").lower() in {"1", "true", "yes"}
        if legacy_scheduler:
            await start_scheduler(poll_seconds=_seconds)
            await start_notif_worker()
            logging.warning("Legacy APScheduler and notification worker enabled")
        else:
            logging.info("Background work delegated to ARQ")
        app.state.legacy_scheduler = legacy_scheduler
        logging.info("App ready.")
    except Exception:
        logging.exception("STARTUP FAILED")
        raise
    yield
    if getattr(app.state, "legacy_scheduler", False):
        logging.info("Shutting down legacy background services...")
        await stop_notif_worker()
        scheduler.shutdown()
    await cache.close()
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


async def _sync_session_role(plex_user_id: str | None, username: str | None) -> dict | None:
    """Corps synchrone de la résolution de rôle (exécuté hors event loop via to_thread)."""
    from .database import AsyncSessionLocal
    from .models import PlexUser, Settings

    db = AsyncSessionLocal()
    try:
        if plex_user_id:
            u = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == plex_user_id))).scalars().first()
            if u:
                return {"role": u.role or "user", "is_owner": u.role == "admin", "user_id": u.id}
        else:
            u = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == username))).scalars().first()
            if u:
                return {"role": u.role or "user", "is_owner": u.role == "admin", "user_id": u.id}
            s = (await db.execute(select(Settings))).scalars().first()
            if s and s.auth_username and username == s.auth_username:
                return {"role": "admin", "is_owner": True}
        return None
    finally:
        await db.close()


class SessionSyncMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.session.get("authenticated"):
            try:
                result = await _sync_session_role(request.session.get("plex_user_id"), request.session.get("username"))
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


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/api/docs", include_in_schema=False)
async def get_documentation(request: Request, db: SqlSession = Depends(get_db)):
    await require_admin(request, db)
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Plexarr API Docs")


@app.get("/api/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(request: Request, db: SqlSession = Depends(get_db)):
    await require_admin(request, db)
    return get_openapi(title="Plexarr", version="1.0.0", routes=app.routes)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionSyncMiddleware)
# Middleware de session (doit être ajouté avant les routers)
app.add_middleware(DynamicSecureSessionMiddleware, secret_key=get_secret_key())

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/vue", StaticFiles(directory="app/static/vue"), name="vue")


app.include_router(auth.router)
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
app.include_router(events_api.router)

SPA_INDEX = os.path.join("app", "static", "vue", "index.html")
SPA_ROOTS = {
    "dashboard",
    "discover",
    "downloads",
    "requests",
    "library",
    "calendar",
    "users",
    "notifications",
    "settings",
    "maintenance",
    "profile",
    "releases",
}


@app.get("/app", include_in_schema=False)
@app.get("/app/{legacy_path:path}", include_in_schema=False)
async def redirect_legacy_spa(legacy_path: str = ""):
    destination = f"/{legacy_path}" if legacy_path else "/dashboard"
    return RedirectResponse(destination, status_code=308)


@app.get("/templates", include_in_schema=False)
async def redirect_legacy_templates():
    return RedirectResponse("/settings?tab=notifications", status_code=308)


@app.get("/logs", include_in_schema=False)
async def redirect_legacy_logs():
    return RedirectResponse("/notifications", status_code=308)


@app.get("/setup/wizard", include_in_schema=False)
async def redirect_legacy_wizard():
    return RedirectResponse("/settings?tab=connections", status_code=308)


@app.get("/", include_in_schema=False)
@app.get("/{spa_path:path}", include_in_schema=False)
async def serve_spa(request: Request, spa_path: str = ""):
    """Serve Vue history routes at the site root after every backend router."""
    root = spa_path.split("/", 1)[0] if spa_path else ""
    if root and root not in SPA_ROOTS:
        raise HTTPException(404, "Route introuvable")
    if not request.session.get("authenticated"):
        return RedirectResponse(f"/login?next=/{spa_path}" if spa_path else "/login", status_code=302)
    if not os.path.exists(SPA_INDEX):
        raise HTTPException(503, "Build Vue introuvable")
    return FileResponse(SPA_INDEX)
