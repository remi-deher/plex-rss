"""Régressions de pagination pour l'historique des téléchargements."""

from datetime import timedelta

import pytest

from app.models import DownloadHistory
from app.routers.downloads_api import downloads_history
from app.utils import now_utc_naive


@pytest.mark.asyncio
async def test_download_history_honors_limit_and_offset(async_db):
    now = now_utc_naive()
    for index in range(5):
        async_db.add(
            DownloadHistory(
                title=f"Média {index}",
                year=2026,
                media_type="movie",
                source="radarr",
                instance_name="Radarr",
                completed_at=now - timedelta(minutes=index),
            )
        )
    async_db.commit()

    first_page = await downloads_history(limit=2, offset=0, db=async_db)
    second_page = await downloads_history(limit=2, offset=2, db=async_db)

    assert [row["title"] for row in first_page] == ["Média 0", "Média 1"]
    assert [row["title"] for row in second_page] == ["Média 2", "Média 3"]
    assert {row["id"] for row in first_page}.isdisjoint(row["id"] for row in second_page)
