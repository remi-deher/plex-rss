"""
Tests d'intégration pour les pages HTML (app/routers/pages.py et auth.py).

Ces tests vérifient que chaque page :
- Retourne HTTP 200 (pas 500)
- Renvoie bien du HTML (content-type text/html)
- Contient un marqueur attendu dans le corps

Ils auraient attrapé le bug TemplateResponse (TypeError: unhashable type: 'dict')
introduit par la migration Starlette ≥ 0.36 qui a changé la signature de l'appel.

Les pages protégées ont leur dépendance require_auth bypassée via dependency_overrides.
Les pages publiques (login, setup) sont testées telles quelles.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.routers import email_templates as email_templates_router
from app.routers import pages as pages_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    """Client avec auth bypassée et DB in-memory."""
    app.dependency_overrides[pages_router.require_auth] = lambda: None
    app.dependency_overrides[email_templates_router.require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    yield c
    app.dependency_overrides.pop(pages_router.require_auth, None)
    app.dependency_overrides.pop(email_templates_router.require_auth, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client_no_auth(db):
    """Client sans bypass d'auth (pour tester les redirections)."""
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    yield c
    app.dependency_overrides.pop(get_db, None)


def _seed(db):
    """Peuple la DB avec des données minimales pour que les pages ne crashent pas."""
    db.add(
        Settings(
            smtp_host="smtp.example.com",
            plex_url="http://plex.local",
            sonarr_url="http://sonarr.local",
            radarr_url="http://radarr.local",
            auth_username="admin",
            auth_password_hash="hash",
        )
    )
    db.add(PlexUser(plex_user_id="alice", display_name="Alice", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="Alice",
            title="Inception",
            media_type="movie",
            status=RequestStatus.sent_to_arr,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Pages protégées — rendu HTML (régression TemplateResponse)
# ---------------------------------------------------------------------------


def test_dashboard_returns_200_html(client, db):
    """GET / → 200, HTML, contient 'Dashboard'."""
    _seed(db)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Dashboard" in resp.text


def test_requests_page_returns_200_html(client, db):
    """GET /requests → 200, HTML, contient la liste des demandes."""
    _seed(db)
    resp = client.get("/requests")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Inception" in resp.text


def test_users_page_returns_200_html(client, db):
    """GET /users → 200, HTML, contient les utilisateurs."""
    _seed(db)
    resp = client.get("/users")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Alice" in resp.text


def test_logs_page_returns_200_html(client, db):
    """GET /logs → 200, HTML."""
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_settings_page_returns_200_html(client, db):
    """GET /settings → 200, HTML."""
    _seed(db)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_email_templates_page_returns_200_html(client, db):
    """GET /settings/email-templates → 200, HTML."""
    _seed(db)
    resp = client.get("/settings/email-templates")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Pages publiques (login / setup)
# ---------------------------------------------------------------------------


def test_login_page_returns_200_when_account_exists(client_no_auth, db):
    """GET /login → 200 si un compte existe."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()
    resp = client_no_auth.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Connexion" in resp.text


def test_setup_page_returns_200_when_no_account(client_no_auth, db):
    """GET /setup → 200 si aucun compte n'existe encore."""
    resp = client_no_auth.get("/setup")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Configuration" in resp.text


def test_login_redirects_to_setup_when_no_account(client_no_auth, db):
    """GET /login redirige vers /setup si aucun compte."""
    resp = client_no_auth.get("/login")
    assert resp.status_code == 302
    assert "/setup" in resp.headers["location"]


def test_setup_redirects_to_home_when_account_exists(client_no_auth, db):
    """GET /setup redirige vers / si un compte existe déjà."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()
    resp = client_no_auth.get("/setup")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


# ---------------------------------------------------------------------------
# Redirections d'authentification
# ---------------------------------------------------------------------------


def test_dashboard_redirects_unauthenticated(client_no_auth, db):
    """GET / sans session → 302 vers /login."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()
    resp = client_no_auth.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


def test_requests_page_redirects_unauthenticated(client_no_auth, db):
    """GET /requests sans session → 302 vers /login."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()
    resp = client_no_auth.get("/requests")
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Contenu minimal des pages
# ---------------------------------------------------------------------------


def test_dashboard_contains_plex_rss_monitor(client, db):
    """Le dashboard contient le nom de l'application."""
    _seed(db)
    resp = client.get("/")
    assert "Plex RSS Monitor" in resp.text


def test_requests_page_empty_db_still_renders(client, db):
    """La page demandes se rend même sans données (DB vide)."""
    resp = client.get("/requests")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_users_page_empty_db_still_renders(client, db):
    """La page utilisateurs se rend même sans données (DB vide)."""
    resp = client.get("/users")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Régression : variable `page` (conflit nav vs. pagination)
# ---------------------------------------------------------------------------


def test_requests_page_pagination_no_500(client, db):
    """Régression : le template ne crashe plus sur `page - 1` (TypeError str - int).

    Avant le fix, {% set page = "requests" %} dans le nav écrasait la variable
    entière `page` du contexte backend. Le renommage en `current_page` corrige ça.
    """
    _seed(db)
    resp = client.get("/requests?page=2")
    # Page 2 vide mais pas 500
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_requests_page_first_page(client, db):
    """La page 1 de /requests se rend sans erreur."""
    _seed(db)
    resp = client.get("/requests?page=1")
    assert resp.status_code == 200
    assert "Inception" in resp.text


# ---------------------------------------------------------------------------
# Affichage co-demandeurs (filtre Jinja `fromjson`)
# ---------------------------------------------------------------------------


def _seed_with_co_requesters(db):
    import json
    db.add(
        Settings(
            sonarr_url="http://sonarr.local",
            radarr_url="http://radarr.local",
            auth_username="admin",
            auth_password_hash="hash",
        )
    )
    db.add(PlexUser(plex_user_id="alice", display_name="Alice", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="Alice",
            title="Dune",
            media_type="movie",
            tmdb_id="438631",
            status=RequestStatus.sent_to_arr,
            extra_requesters=json.dumps([{"plex_user_id": "bob", "display_name": "Bob"}]),
        )
    )
    db.commit()


def test_requests_page_shows_co_requester(client, db):
    """La page demandes affiche les co-demandeurs depuis extra_requesters."""
    _seed_with_co_requesters(db)
    resp = client.get("/requests")
    assert resp.status_code == 200
    assert "Bob" in resp.text


# ---------------------------------------------------------------------------
# Page utilisateurs : disposition carte + custom_name
# ---------------------------------------------------------------------------


def test_users_page_shows_custom_name(client, db):
    """La page utilisateurs affiche le custom_name quand il est défini."""
    db.add(
        Settings(
            sonarr_url="http://sonarr.local",
            radarr_url="http://radarr.local",
            auth_username="admin",
            auth_password_hash="hash",
        )
    )
    db.add(PlexUser(plex_user_id="alice", display_name="alice_plex", custom_name="Alice IRL", enabled=True))
    db.commit()

    resp = client.get("/users")
    assert resp.status_code == 200
    assert "Alice IRL" in resp.text


def test_users_page_shows_display_name_when_no_custom(client, db):
    """Sans custom_name, la page affiche le display_name Plex."""
    db.add(
        Settings(
            sonarr_url="http://sonarr.local",
            radarr_url="http://radarr.local",
            auth_username="admin",
            auth_password_hash="hash",
        )
    )
    db.add(PlexUser(plex_user_id="bob", display_name="Bob Plex", custom_name=None, enabled=True))
    db.commit()

    resp = client.get("/users")
    assert resp.status_code == 200
    assert "Bob Plex" in resp.text


def test_users_page_shows_rss_only_badge_when_no_seer(client, db):
    """Un utilisateur sans seer_user_id affiche un indicateur 'RSS' (RSS uniquement)."""
    db.add(
        Settings(
            sonarr_url="http://sonarr.local",
            radarr_url="http://radarr.local",
            auth_username="admin",
            auth_password_hash="hash",
        )
    )
    db.add(PlexUser(plex_user_id="charlie", display_name="Charlie", seer_user_id=None, enabled=True))
    db.commit()

    resp = client.get("/users")
    assert resp.status_code == 200
    # Le template doit rendre un badge RSS ou le bloc "Lier automatiquement"
    assert "RSS" in resp.text or "Lier" in resp.text


# ---------------------------------------------------------------------------
# Filtres de la page /requests (user, search, sort)
# ---------------------------------------------------------------------------


def test_requests_page_filter_by_user(client, db):
    """GET /requests?user=alice → uniquement les demandes d'Alice."""
    _seed(db)
    db.add(PlexUser(plex_user_id="bob", display_name="Bob", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="bob",
            plex_user="Bob",
            title="Dune",
            media_type="movie",
            status=RequestStatus.sent_to_arr,
        )
    )
    db.commit()
    resp = client.get("/requests?user=alice")
    assert resp.status_code == 200
    assert "Inception" in resp.text
    assert "Dune" not in resp.text


def test_requests_page_filter_by_search(client, db):
    """GET /requests?search=Dune → filtre par titre."""
    _seed(db)
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="Alice",
            title="Dune",
            media_type="movie",
            status=RequestStatus.sent_to_arr,
        )
    )
    db.commit()
    resp = client.get("/requests?search=Dune")
    assert resp.status_code == 200
    assert "Dune" in resp.text
    assert "Inception" not in resp.text


def test_requests_page_sort_asc(client, db):
    """GET /requests?sort=title&order=asc → 200 sans erreur."""
    _seed(db)
    resp = client.get("/requests?sort=title&order=asc")
    assert resp.status_code == 200
