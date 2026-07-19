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

## Docker Compose

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

Create `docker-compose.yml`:

```yaml
services:
  plex-rss:
    image: mrcryllix/plex-rss:latest
    container_name: plex-rss
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    env_file: .env
    environment:
      DATABASE_URL: postgresql://plexrss:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-plexrss}
      REDIS_URL: redis://redis:6379/0
      ENABLE_ARQ: "1"
      ENABLE_LEGACY_SCHEDULER: "0"
      PLEXARR_ENCRYPTION_KEY: ${PLEXARR_ENCRYPTION_KEY}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/favicon.ico')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    restart: unless-stopped

  worker:
    image: mrcryllix/plex-rss:latest
    container_name: plex-rss-worker
    command: ["arq", "app.jobs.WorkerSettings"]
    volumes:
      - ./data:/app/data
    env_file: .env
    environment:
      DATABASE_URL: postgresql://plexrss:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-plexrss}
      REDIS_URL: redis://redis:6379/0
      ENABLE_ARQ: "1"
      PLEXARR_ENCRYPTION_KEY: ${PLEXARR_ENCRYPTION_KEY}
      ARQ_MAX_JOBS: ${ARQ_MAX_JOBS:-4}
      ARQ_JOB_TIMEOUT: ${ARQ_JOB_TIMEOUT:-3600}
    depends_on:
      plex-rss:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "arq", "--check", "app.jobs.WorkerSettings"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    container_name: plex-rss-db
    environment:
      POSTGRES_USER: plexrss
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-plexrss}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U plexrss -d ${POSTGRES_DB:-plexrss}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: plex-rss-redis
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
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

## Documentation

Full French documentation, backup/restore commands, migration instructions and development setup are available in the [GitHub README](https://github.com/remi-deher/plex-rss#readme).

---

## Français

Plexarr est un hub auto-hébergé de demandes et de disponibilité pour Plex. Il récupère les demandes depuis les watchlists Plex, l’API, Seerr ou son interface, les transmet à Sonarr/Radarr, surveille les téléchargements et imports, confirme la présence dans Plex, analyse les versions VO/VF et regroupe les notifications.

Le déploiement complet nécessite l’API, un worker ARQ utilisant la même image, PostgreSQL et Redis. Utilisez le fichier Compose ci-dessus, ouvrez `http://localhost:8000`, puis suivez l’assistant de première configuration.

Consultez le [README GitHub](https://github.com/remi-deher/plex-rss#readme) pour la documentation complète en français, les sauvegardes, les restaurations et la migration depuis SQLite.
