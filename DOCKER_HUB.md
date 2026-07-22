# Plexarr

[![Docker Pulls](https://img.shields.io/docker/pulls/mrcryllix/plex-rss?logo=docker&color=e5a00d)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![GitHub](https://img.shields.io/badge/GitHub-remi--deher%2Fplex--rss-181717?logo=github)](https://github.com/remi-deher/plex-rss)
[![License](https://img.shields.io/github/license/remi-deher/plex-rss)](https://github.com/remi-deher/plex-rss/blob/main/LICENSE)

Self-hosted request, acquisition and availability hub for **Plex**, **Sonarr** and **Radarr**.

Plexarr receives requests from Plex watchlists, RSS, its API, Seerr or its responsive web interface. It follows downloads and imports, confirms availability in Plex, tracks VO/VF coverage and sends grouped notifications through email, Discord, Telegram, ntfy or Gotify.

> The application is named **Plexarr**. The historical Docker image name remains `mrcryllix/plex-rss`.

## Highlights

- Plex API and RSS watchlist ingestion with fallback.
- Multiple Sonarr/Radarr instances and optional approval.
- Complete-series, selected-season and single-episode workflows.
- Import-block detection and manual matching tools.
- Plex library synchronization and VO/VF analysis.
- Grouped milestone notifications without one email per season.
- Responsive desktop, tablet and mobile UI.
- PostgreSQL, Redis and an independent ARQ worker.
- Health endpoint, Prometheus metrics, backups and verified restore tooling.

## Architecture

```text
Plex watchlist / API / Seerr / UI
                 |
                 v
        Plexarr API + Vue UI ---- PostgreSQL
                 |
               Redis
                 |
             ARQ worker
       /         |          \
   Plex     Sonarr/Radarr   Notifications
                    |
             Download clients
```

## Required services

The same image is used for both the web/API service and the ARQ worker. A production deployment requires:

- `mrcryllix/plex-rss:latest` for the API;
- `mrcryllix/plex-rss:latest` with the ARQ command for the worker;
- PostgreSQL 15;
- Redis 7 with persistence.

## Image tags

| Tag | Meaning |
|---|---|
| `latest` | Last successful build from `main`. Moves on every merge — fine for personal instances, riskier for production since a bad merge ships immediately. |
| `vX.Y.Z` | Built from a Git tag (`git tag vX.Y.Z`), immutable. Pin to one of these for a production deployment so an update is a deliberate `docker compose pull` after you've read the [changelog](https://github.com/remi-deher/plex-rss/blob/main/CHANGELOG.md), not an automatic drift. |

Images are published to both Docker Hub (`mrcryllix/plex-rss`) and GitHub Container Registry (`ghcr.io/remi-deher/plex-rss`) for the same tags. Only `linux/amd64` is built at the moment — no `arm64` image yet.

## Docker Compose

The full, up-to-date Compose file — including the `backup`/`restore` profile, environment variables and volume layout — lives in the [GitHub README](https://github.com/remi-deher/plex-rss#installation-docker). Rather than duplicate it here (and risk it drifting out of sync), the short version below covers just enough to get running; follow the README link for anything beyond the basics.

Create `.env`:

```dotenv
TZ=Europe/Paris
POSTGRES_DB=plexrss
POSTGRES_PASSWORD=replace-with-a-long-random-password
PLEXARR_ENCRYPTION_KEY=replace-with-a-fernet-key
ARQ_MAX_JOBS=4
ARQ_JOB_TIMEOUT=3600
```

Generate the encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Grab `docker-compose.yml` from the repo (it targets the published image out of the box once you swap `build: .` for `image: mrcryllix/plex-rss:latest`, or pin it to a `vX.Y.Z` tag per the table above):

```bash
curl -O https://raw.githubusercontent.com/remi-deher/plex-rss/main/docker-compose.yml
```

Start the stack:

```bash
docker compose up -d
docker compose ps
```

Open `http://localhost:8000` and follow the first-run wizard.

## First-run checklist

1. Create the owner account.
2. Configure Plex and test the connection.
3. Add Sonarr/Radarr instances, quality profiles and root folders.
4. Synchronize Plex users.
5. Configure and test at least one notification channel.
6. Add Sonarr/Radarr/Plex webhooks for faster detection.

## Update

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 plex-rss worker
```

Database migrations run when the API container starts.

## Important data

- PostgreSQL data: named volume `pgdata`.
- Redis AOF data: named volume `redisdata`.
- Application data and legacy migration files: `./data`.
- Encryption key: `PLEXARR_ENCRYPTION_KEY` in `.env`.

Back up both PostgreSQL and the encryption key. Losing the encryption key prevents Plexarr from decrypting stored integration secrets.

## Health checks

```bash
docker compose exec worker arq --check app.jobs.WorkerSettings
docker compose exec redis redis-cli ping
docker compose exec db pg_isready -U plexrss -d plexrss
```

- Health: `GET /api/health`
- Prometheus metrics: `GET /api/metrics/prometheus`

## Troubleshooting

- **`plex-rss` stuck "unhealthy" after an update, worker never starts**: almost always a failed Alembic migration on container start. Check `docker compose logs plex-rss` for the migration error before anything else — the worker's `depends_on: service_healthy` means it won't even attempt to start while the API container is unhealthy.
- **Migration fails with "already exists" / `DuplicateTable` on a retry**: a previous start was interrupted mid-migration, leaving a partially-applied schema change without the migration being marked complete in `alembic_version`. See the full [GitHub README troubleshooting section](https://github.com/remi-deher/plex-rss#dépannage) for the recovery steps.
- **Worker healthy but nothing processes**: confirm `ENABLE_ARQ=1` on both services and that `redis-cli ping` succeeds — a worker container with no queue connection reports healthy on its own check but silently drops jobs.

## Documentation

Full French documentation, backup/restore commands, migration instructions and development setup are available in the [GitHub README](https://github.com/remi-deher/plex-rss#readme).

---

## Français

Plexarr est un hub auto-hébergé de demandes et de disponibilité pour Plex. Il récupère les demandes depuis les watchlists Plex, l’API, Seerr ou son interface, les transmet à Sonarr/Radarr, surveille les téléchargements et imports, confirme la présence dans Plex, analyse les versions VO/VF et regroupe les notifications.

Le déploiement complet nécessite l’API, un worker ARQ utilisant la même image, PostgreSQL et Redis. Utilisez le fichier Compose ci-dessus, ouvrez `http://localhost:8000`, puis suivez l’assistant de première configuration.

Consultez le [README GitHub](https://github.com/remi-deher/plex-rss#readme) pour la documentation complète en français, les sauvegardes, les restaurations et la migration depuis SQLite.
