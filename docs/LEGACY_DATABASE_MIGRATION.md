# Migration automatique d'une ancienne base Plex-RSS

Plex-RSS peut reprendre une installation SQLite existante lors du passage a PostgreSQL. La migration conserve les identifiants, les demandes, les historiques, les journaux, la bibliotheque, les statuts VFF et les caches compatibles.

## Migration automatique au premier demarrage

Avec Docker Compose, placez l'ancienne base a cet emplacement avant le premier demarrage de la version PostgreSQL :

```text
data/plex_rss.db
```

Le service API applique d'abord les migrations Alembic, puis importe automatiquement SQLite uniquement si PostgreSQL ne contient encore aucune donnee applicative. Le fichier SQLite n'est jamais modifie ou supprime. Apres succes, un marqueur est ecrit dans `data/.legacy_sqlite_migration.json` pour empecher une seconde execution.

Variables disponibles :

```dotenv
AUTO_MIGRATE_LEGACY_SQLITE=1
LEGACY_SQLITE_PATH=/app/data/plex_rss.db
LEGACY_IMPORT_MAX_BYTES=268435456
```

Si PostgreSQL contient deja des donnees, l'import automatique est ignore. Cette protection evite tout ecrasement lors d'un redemarrage normal.

## Migration manuelle depuis l'interface

1. Ouvrez `Reglages > Avance > Migration d'une ancienne base SQLite`.
2. Selectionnez le fichier `.db`, `.sqlite` ou `.sqlite3`.
3. Cliquez sur **Inspecter** et controlez les nombres de lignes affiches.
4. Saisissez `REMPLACER`, puis lancez la migration.

L'import manuel remplace les donnees PostgreSQL existantes. Avant le remplacement, Plex-RSS cree obligatoirement une sauvegarde validee avec `pg_dump` et `pg_restore --list` dans `data/backups/`. La copie et sa verification sont executees dans une transaction PostgreSQL unique : une erreur annule l'ensemble de l'import.

Les jobs ARQ detectent le verrou de migration et ne demarrent pas pendant l'operation.

## Ligne de commande

Validation sans modification :

```bash
python scripts/migrate_sqlite_to_postgres.py --source data/plex_rss.db --dry-run
```

Import vers une cible vide contenant seulement la ligne de reglages initiale :

```bash
python scripts/migrate_sqlite_to_postgres.py --source data/plex_rss.db --replace-seed
```

Remplacement explicite d'une cible occupee :

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --source data/plex_rss.db \
  --replace-target \
  --confirm-replace REPLACE
```

La commande utilise `DATABASE_URL` comme cible par defaut. Une sauvegarde manuelle reste recommandee avant l'option `--replace-target`; l'interface Web la rend obligatoire automatiquement.

## Export JSON et backup complet

L'export JSON reste adapte a une fusion selective entre installations. Il ne reimporte pas certains historiques sans cle de fusion fiable. Pour une reprise exacte, utilisez la migration SQLite complete.

Le bouton **Telecharger un backup complet** produit un fichier `.db` sous SQLite et un dump PostgreSQL au format custom sous PostgreSQL. Ces fichiers contiennent des secrets et doivent etre proteges.
