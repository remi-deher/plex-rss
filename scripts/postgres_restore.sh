#!/bin/sh
set -eu

if [ "${CONFIRM_RESTORE:-}" != "YES" ]; then
  echo "Restore refused: set CONFIRM_RESTORE=YES"
  exit 2
fi
if [ -z "${RESTORE_FILE:-}" ] || [ ! -f "/backups/$RESTORE_FILE" ]; then
  echo "Restore refused: RESTORE_FILE must name a file in ./backups"
  exit 2
fi
pg_restore --list "/backups/$RESTORE_FILE" >/dev/null
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$PGDATABASE" "/backups/$RESTORE_FILE"
echo "Restore completed: $RESTORE_FILE"
