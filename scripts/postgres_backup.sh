#!/bin/sh
set -eu

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="/backups/plexarr-${timestamp}.dump"
mkdir -p /backups
pg_dump --format=custom --compress=9 --file="$target"
pg_restore --list "$target" >/dev/null
find /backups -type f -name 'plexarr-*.dump' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
printf 'Backup verified: %s\n' "$target"
