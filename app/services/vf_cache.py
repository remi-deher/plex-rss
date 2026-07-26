"""Cache VF par episode : invalidation partagee.

Module feuille (il n'importe que les modeles et SQLAlchemy), pour que routers et services
puissent l'appeler sans risque d'import circulaire -- c'est ce risque qui avait conduit a
recopier `_delete_vf_episode_cache` a l'identique dans quatre modules
(routers/webhook.py, routers/requests_api.py, routers/misc_api.py,
services/arr_tracker.py).
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import VfEpisodeStatus


async def delete_request_episode_cache(db: AsyncSession, request_id: int) -> None:
    """Purge le cache VF par episode d'une demande supprimee (evite les lignes orphelines).

    Sans commit : a la charge de l'appelant, qui supprime en general la demande dans la
    meme transaction.
    """
    await db.execute(
        delete(VfEpisodeStatus).where(
            VfEpisodeStatus.source_type == "request",
            VfEpisodeStatus.source_id == request_id,
        )
    )
