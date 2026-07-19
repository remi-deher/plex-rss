# Migration SQLite vers PostgreSQL

## Prérequis

- conserver une copie intacte de `data/plex_rss.db` ;
- utiliser une base PostgreSQL dédiée et vide ;
- arrêter l'application pendant la copie pour empêcher toute nouvelle écriture ;
- avoir appliqué toutes les migrations Alembic sur PostgreSQL.

## Procédure Docker

1. Sauvegarder SQLite :

```powershell
Copy-Item -LiteralPath .\data\plex_rss.db -Destination .\data\plex_rss.before-postgres.db
```

2. Démarrer uniquement PostgreSQL et Redis, puis appliquer les migrations :

```powershell
docker compose up -d db redis
docker compose run --rm --no-deps --entrypoint python plex-rss -m alembic upgrade head
```

3. Vérifier l'import sans écrire :

```powershell
docker compose run --rm --no-deps --entrypoint python plex-rss `
  scripts/migrate_sqlite_to_postgres.py `
  --source /app/data/plex_rss.db --replace-seed --dry-run
```

4. Exécuter l'import :

```powershell
docker compose run --rm --no-deps --entrypoint python plex-rss `
  scripts/migrate_sqlite_to_postgres.py `
  --source /app/data/plex_rss.db --replace-seed
```

5. Démarrer l'application et contrôler les journaux :

```powershell
docker compose up -d plex-rss
docker compose logs --tail 200 plex-rss
```

Le script refuse une cible contenant des données métier. `--replace-seed` autorise seulement
le remplacement de l'unique ligne `settings` créée automatiquement sur une base fraîche. Les
identifiants sont conservés, les séquences PostgreSQL sont recalées et les nombres de lignes
sont comparés avant validation de la transaction.

## Retour arrière

1. Arrêter `plex-rss`.
2. Restaurer `data/plex_rss.before-postgres.db` sous `data/plex_rss.db`.
3. Remettre temporairement `DATABASE_URL=sqlite:///./data/plex_rss.db`.
4. Redémarrer l'application et vérifier les demandes, utilisateurs et réglages.

Ne supprimer la sauvegarde SQLite qu'après plusieurs cycles de polling et une vérification
des notifications, historiques, liens Plex et routages Sonarr/Radarr sur PostgreSQL.
