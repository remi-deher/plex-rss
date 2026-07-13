# Exploitation Plexarr

## Configuration

1. Copier `.env.example` vers `.env`.
2. Generer un mot de passe PostgreSQL long et unique.
3. Generer `PLEXARR_ENCRYPTION_KEY` avec `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
4. Demarrer avec `docker compose up -d --build`.

L'API et le worker ARQ sont deux services independants. APScheduler est desactive par defaut.
`ENABLE_LEGACY_SCHEDULER=1` ne doit servir qu'au retour arriere temporaire, sans worker ARQ actif.

## Verification

```bash
docker compose ps
docker compose exec worker arq --check app.jobs.WorkerSettings
docker compose exec redis redis-cli ping
docker compose exec db pg_isready -U plexrss -d plexrss
```

Les metriques Prometheus sont exposees sur `/api/metrics/prometheus` et comprennent Redis,
le heartbeat ARQ, la profondeur de file et la derniere duree connue de chaque job.

## Sauvegarde PostgreSQL

```bash
docker compose --profile operations run --rm backup
```

Le dump custom est verifie avec `pg_restore --list` puis conserve dans `./backups`.
Les fichiers plus anciens que `BACKUP_RETENTION_DAYS` sont supprimes.

## Restauration

Arreter l'API et le worker pour garantir une restauration sans ecriture concurrente :

```bash
docker compose stop plex-rss worker
RESTORE_FILE=plexarr-YYYYMMDDTHHMMSSZ.dump CONFIRM_RESTORE=YES docker compose --profile operations run --rm restore
docker compose up -d plex-rss worker
```

Verifier ensuite les migrations, l'API, le worker et un echantillon de demandes. Une restauration
doit etre repetee regulierement sur une base temporaire : un dump non restaure n'est pas un test.

## Mise a jour

1. Executer une sauvegarde.
2. Recuperer la nouvelle version et lire les migrations.
3. Executer `docker compose build`.
4. Executer `docker compose up -d`.
5. Controler `docker compose ps`, les logs API/worker et les metriques.
6. En cas d'echec, revenir a l'image precedente puis restaurer uniquement si une migration a modifie les donnees.

## Temps reel

`/api/events` est un flux SSE authentifie par cookie de session. Redis Streams conserve les 1 000
derniers signaux et permet la reprise via `Last-Event-ID`. Les evenements ne contiennent pas de liste
metier : le navigateur recharge l'endpoint REST soumis aux permissions de l'utilisateur.
