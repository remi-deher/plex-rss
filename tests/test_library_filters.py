"""Filtrage serveur de la page Bibliothèque (/api/library et /api/requests-list).

Ces filtres étaient appliqués en JavaScript sur la page déjà chargée. Comme
`/api/library` est paginé (200 médias par appel), « VF uniquement » ne filtrait en
réalité que le premier lot et masquait silencieusement tout le reste de la bibliothèque.
Chaque test ci-dessous vérifie que le filtre porte bien sur *toute* la table, en plaçant
le média attendu au-delà de la première page.
"""

from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import LibraryItem, MediaRequest, RequestStatus


def _client(db):
    app.dependency_overrides[get_db_async] = lambda: db
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


def _cleanup():
    app.dependency_overrides.pop(get_db_async, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)


def _titles(response):
    return [item["title"] for item in response.json()]


# ---------------------------------------------------------------------------
# /api/library
# ---------------------------------------------------------------------------


def test_library_vf_filter_reaches_beyond_the_first_page(async_db):
    """Le cœur de la régression : un seul média VF, noyé après 250 médias VO."""
    async_db.add_all(
        [LibraryItem(title=f"VO {index:03d}", media_type="movie", has_vf=False) for index in range(250)]
    )
    async_db.add(LibraryItem(title="Le seul VF", media_type="movie", has_vf=True))
    async_db.commit()
    client = _client(async_db)
    try:
        # Première page seulement, exactement ce que charge la vue au montage.
        response = client.get("/api/library?vf=vf&limit=200&offset=0")
        assert response.status_code == 200
        assert _titles(response) == ["Le seul VF"]
    finally:
        _cleanup()


def test_library_vf_filter_distinguishes_vo_and_unchecked(async_db):
    async_db.add_all(
        [
            LibraryItem(title="En VF", media_type="movie", has_vf=True),
            LibraryItem(title="En VO", media_type="movie", has_vf=False),
            LibraryItem(title="Non verifie", media_type="movie", has_vf=None),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert _titles(client.get("/api/library?vf=vf")) == ["En VF"]
        assert _titles(client.get("/api/library?vf=vo")) == ["En VO"]
        assert _titles(client.get("/api/library?vf=unchecked")) == ["Non verifie"]
        # Valeur inconnue : filtre ignoré plutôt que résultat vide trompeur.
        assert len(_titles(client.get("/api/library?vf=nimportequoi"))) == 3
    finally:
        _cleanup()


def test_library_accepts_several_media_types(async_db):
    """La vue n'envoyait le type que lorsqu'un seul était coché ; sélectionner Films *et*
    Séries retombait donc sur un filtrage client, faux au-delà d'une page."""
    async_db.add_all(
        [
            LibraryItem(title="Un film", media_type="movie"),
            LibraryItem(title="Une serie", media_type="show"),
            LibraryItem(title="Un autre film", media_type="movie"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert sorted(_titles(client.get("/api/library?media_types=movie,show"))) == [
            "Un autre film",
            "Un film",
            "Une serie",
        ]
        assert _titles(client.get("/api/library?media_types=show")) == ["Une serie"]
        # Le paramètre singulier historique reste accepté.
        assert _titles(client.get("/api/library?media_type=show")) == ["Une serie"]
    finally:
        _cleanup()


def test_library_filters_by_requester_through_the_linked_requests(async_db):
    """Un média Plex n'a pas de demandeur en propre : il l'hérite des demandes qui
    pointent dessus."""
    async_db.add_all(
        [
            LibraryItem(title="Demande par alice", media_type="movie"),
            LibraryItem(title="Demande par bob", media_type="movie"),
            LibraryItem(title="Jamais demande", media_type="movie"),
        ]
    )
    async_db.commit()
    async_db.add_all(
        [
            MediaRequest(title="Demande par alice", media_type="movie", plex_user_id="alice", library_item_id=1),
            MediaRequest(title="Demande par bob", media_type="movie", plex_user_id="bob", library_item_id=2),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert _titles(client.get("/api/library?requesters=alice")) == ["Demande par alice"]
        assert sorted(_titles(client.get("/api/library?requesters=alice,bob"))) == [
            "Demande par alice",
            "Demande par bob",
        ]
    finally:
        _cleanup()


def test_library_filters_combine(async_db):
    async_db.add_all(
        [
            LibraryItem(title="Serie VF", media_type="show", has_vf=True),
            LibraryItem(title="Serie VO", media_type="show", has_vf=False),
            LibraryItem(title="Film VF", media_type="movie", has_vf=True),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert _titles(client.get("/api/library?media_types=show&vf=vf")) == ["Serie VF"]
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# /api/requests-list
# ---------------------------------------------------------------------------


def _request_titles(response):
    return [item["title"] for item in response.json()["items"]]


def test_requests_list_accepts_several_sources_and_requesters(async_db):
    async_db.add_all(
        [
            MediaRequest(title="Via Seer", media_type="movie", source="seer", plex_user_id="alice"),
            MediaRequest(title="Via watchlist", media_type="movie", source="watchlist", plex_user_id="bob"),
            MediaRequest(title="Via formulaire", media_type="movie", source="form", plex_user_id="carol"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert sorted(_request_titles(client.get("/api/requests-list?sources=seer,watchlist"))) == [
            "Via Seer",
            "Via watchlist",
        ]
        assert sorted(_request_titles(client.get("/api/requests-list?requesters=alice,carol"))) == [
            "Via Seer",
            "Via formulaire",
        ]
    finally:
        _cleanup()


def test_requests_list_vf_filter(async_db):
    async_db.add_all(
        [
            MediaRequest(title="VF", media_type="movie", has_vf=True, plex_user_id="alice"),
            MediaRequest(title="VO", media_type="movie", has_vf=False, plex_user_id="alice"),
            MediaRequest(title="Inconnu", media_type="movie", has_vf=None, plex_user_id="alice"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert _request_titles(client.get("/api/requests-list?vf=vf")) == ["VF"]
        assert _request_titles(client.get("/api/requests-list?vf=vo")) == ["VO"]
        assert _request_titles(client.get("/api/requests-list?vf=unchecked")) == ["Inconnu"]
    finally:
        _cleanup()


def test_strict_partial_excludes_shows_that_are_up_to_date(async_db):
    """Une série garde le statut « partiellement disponible » tant qu'elle n'a pas fini de
    diffuser, même quand elle est à jour sur tout ce qui est sorti. Ce raffinement était
    appliqué côté client."""
    async_db.add_all(
        [
            MediaRequest(
                title="Vraiment en retard", media_type="show", plex_user_id="alice",
                status=RequestStatus.partially_available,
                episodes_aired_count=10, episodes_available_count=4,
            ),
            MediaRequest(
                title="A jour", media_type="show", plex_user_id="alice",
                status=RequestStatus.partially_available,
                episodes_aired_count=10, episodes_available_count=10,
            ),
            MediaRequest(
                title="Sans compteurs", media_type="show", plex_user_id="alice",
                status=RequestStatus.partially_available,
                episodes_aired_count=None, episodes_available_count=None,
            ),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        strict = client.get("/api/requests-list?statuses=partially_available&strict_partial=true")
        assert _request_titles(strict) == ["Vraiment en retard"]

        # Sans le drapeau (cas « Dans Plex »), une série à jour reste visible : au moins un
        # épisode est regardable.
        loose = client.get("/api/requests-list?statuses=partially_available")
        assert sorted(_request_titles(loose)) == ["A jour", "Sans compteurs", "Vraiment en retard"]
    finally:
        _cleanup()


def test_strict_partial_keeps_the_other_selected_statuses(async_db):
    """Le raffinement ne doit s'appliquer qu'aux séries partielles, pas amputer les autres
    statuts cochés en même temps."""
    async_db.add_all(
        [
            MediaRequest(
                title="Partielle a jour", media_type="show", plex_user_id="alice",
                status=RequestStatus.partially_available,
                episodes_aired_count=5, episodes_available_count=5,
            ),
            MediaRequest(title="En attente", media_type="movie", status=RequestStatus.pending, plex_user_id="alice"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(
            "/api/requests-list?statuses=partially_available,pending&strict_partial=true"
        )
        assert _request_titles(response) == ["En attente"]
    finally:
        _cleanup()


def test_total_reflects_the_filters(async_db):
    """`total` alimente la pagination : il doit compter les lignes filtrées, pas la table."""
    async_db.add_all(
        [
            MediaRequest(title="VF", media_type="movie", has_vf=True, plex_user_id="alice"),
            MediaRequest(title="VO 1", media_type="movie", has_vf=False, plex_user_id="alice"),
            MediaRequest(title="VO 2", media_type="movie", has_vf=False, plex_user_id="alice"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        assert client.get("/api/requests-list?vf=vo").json()["total"] == 2
        assert client.get("/api/requests-list").json()["total"] == 3
    finally:
        _cleanup()


def test_facets_stay_complete_despite_the_filters(async_db):
    """Les listes déroulantes de filtres se remplissent depuis `facets` : elles doivent
    rester exhaustives, sinon sélectionner une source ferait disparaître les autres
    choix possibles."""
    async_db.add_all(
        [
            MediaRequest(title="A", media_type="movie", source="seer", plex_user_id="alice"),
            MediaRequest(title="B", media_type="show", source="watchlist", plex_user_id="bob"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        facets = client.get("/api/requests-list?sources=seer").json()["facets"]
        assert facets["sources"] == ["seer", "watchlist"]
        assert sorted(entry["id"] for entry in facets["requesters"]) == ["alice", "bob"]
    finally:
        _cleanup()


def test_requests_list_music_media_type_returns_no_requests(async_db):
    """Lorsqu'on filtre sur la musique (artist), aucune demande (movie/show) ne doit être retournée."""
    async_db.add_all(
        [
            MediaRequest(title="Film en attente", media_type="movie", plex_user_id="alice"),
            MediaRequest(title="Série en attente", media_type="show", plex_user_id="bob"),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get("/api/requests-list?media_types=artist")
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["items"] == []
    finally:
        _cleanup()

