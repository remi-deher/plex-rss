# Passation - Plex-RSS après migration SQLAlchemy async

## État au 13 juillet 2026

La migration de l'application vers SQLAlchemy async est terminée côté code applicatif.
Ne réintroduire ni moteur synchrone, ni `SessionLocal`, ni `db.query()`.

La stack DB active est désormais :

- `AsyncSessionLocal` et `AsyncSession` ;
- `sqlite+aiosqlite` pour SQLite ;
- `postgresql+asyncpg` pour PostgreSQL ;
- `await db.execute(select(...))` avec `scalars().first()` ou `scalars().all()` ;
- transactions via `await db.flush()`, `await db.commit()`, `await db.rollback()` et `await db.delete()`.

## Travail réalisé

Les routeurs, dépendances FastAPI, tâches planifiées et services suivants utilisent tous une session async :

- authentification, utilisateurs, paramètres, import/export, métriques et webhooks ;
- `watchlist_poller.py` ;
- `arr_tracker.py` ;
- `seer_sync.py` ;
- `plex_sync.py` ;
- `vff_scanner.py` ;
- `availability_service.py` ;
- `download_history.py` ;
- `tmdb.py` ;
- `notification_orchestrator.py` ;
- `notification_queue.py`.

Le moteur et le seeding synchrones ont été supprimés de `app/database.py`. Les migrations Alembic restent lancées dans un thread, car leur subprocessus est bloquant, puis le seeding est effectué avec `AsyncSessionLocal`.

Les appels réseau Plex bloquants restent volontairement entourés par `asyncio.to_thread`. APScheduler est encore démarré dans le cycle de vie FastAPI : son extraction vers un worker séparé est la prochaine phase, pas une partie de la migration DB.

## Vérifications effectuées

Ces contrôles passent :

```powershell
python -m compileall -q app scripts tests
python -c "import app.main; print('import ok')"
rg -n "db\.query\(|\bSessionLocal\(|from sqlalchemy\.orm import Session|db: Session|sessionmaker\(|create_engine\(" app --glob '*.py'
```

La suite complète passe avec `pytest-asyncio` :

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p pytest_asyncio.plugin -q
```

Résultat vérifié le 13 juillet 2026 : **624 tests réussis**, avec un seul avertissement
de dépréciation provenant de l'intégration `httpx` de Starlette.

## Migration des tests terminée

La suite historique a été adaptée à la nouvelle architecture. `tests/async_support.py`
fournit un adaptateur `TestSession` limité aux tests : il expose le protocole attendu par
le code async tout en permettant aux tests `TestClient` de préparer et d'inspecter leur
base SQLite en mémoire de façon synchrone. Cet adaptateur ne doit jamais être importé par
le code applicatif.

Les changements couvrent notamment :

1. La surcharge de `get_db_async` dans les tests FastAPI.
2. Le patch de `AsyncSessionLocal` dans les services et tâches qui ouvrent leur session.
3. L'utilisation de `AsyncMock` pour les fonctions attendues et les frontières réseau.
4. La conversion des tests de dépendances, services et scripts en `async def` avec `await`.
5. L'isolation du cache mémoire entre les tests.
6. La migration des tests de notifications, webhooks, maintenance, synchronisation et torrents.

Commande recommandée :

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p pytest_asyncio.plugin -q
```

Ne pas ajouter d'alias `SessionLocal` uniquement pour faire repasser les anciens tests : cela masquerait une régression vers le modèle synchrone.

## Prochaine phase fonctionnelle

Après migration des tests et validation complète :

1. Ajouter Redis.
2. Déplacer les jobs APScheduler vers ARQ, recommandé pour rester entièrement async, ou Celery.
3. Retirer le démarrage du scheduler du `lifespan` FastAPI.
4. Stocker l'état et le résultat des jobs dans Redis ou une table dédiée.
5. Exposer les changements à la SPA Vue via SSE ou WebSocket.
6. Ajouter le cache stale-while-revalidate pour les données de santé afin que les anciennes valeurs restent affichées pendant le rafraîchissement.

## Garde-fous

- Une `AsyncSession` ne doit jamais être partagée entre plusieurs tâches concurrentes.
- Chaque worker ou job doit ouvrir et fermer sa propre session.
- Les bibliothèques réseau synchrones doivent rester dans `asyncio.to_thread` ou être remplacées par un client async.
- Toujours compiler après une modification massive pour détecter les doubles `async` et signatures dupliquées.
- Ne commencer l'extraction des workers qu'après migration et stabilisation de la suite de tests.
