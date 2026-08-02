from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_vite_assets_are_immutable_and_gzipped():
    asset = next(
        path for path in Path("app/static/vue/assets").glob("*.js") if path.stat().st_size > 1000
    )
    response = TestClient(app).get(
        f"/vue/assets/{asset.name}", headers={"Accept-Encoding": "gzip"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["content-encoding"] == "gzip"


def test_vite_index_is_revalidated():
    response = TestClient(app).get("/vue/index.html")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
