from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import PollHistory
from app.routers.api import require_auth


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client

def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)

def test_get_poll_history():
    history = PollHistory(
        id=1,
        job="watchlist",
        started_at=datetime(2026, 6, 17, 12, 0, 0),
        duration_ms=150,
        items_processed=10,
        new_requests=2,
        newly_available=0,
        errors=0
    )
    db = MagicMock()
    # Mocking chain: db.query().filter().order_by().limit().all()
    q = db.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = [history]

    client = _client_with_db(db)
    try:
        resp = client.get("/api/poll-history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["job"] == "watchlist"
        assert data[0]["duration_ms"] == 150
        assert data[0]["items_processed"] == 10
    finally:
        _cleanup()
