#!/bin/sh
# Corrige la propriété du volume /app/data avant de démarrer l'app.
#
# Le conteneur tourne en utilisateur non-root (app) pour limiter l'impact
# d'une éventuelle évasion, mais ./data est un bind mount venant de l'hôte :
# sur une installation existante, il peut être détenu par root (créé par une
# ancienne version de l'image qui tournait en root). On corrige donc la
# propriété ici (en root, seul moment où l'entrypoint tourne en root) avant
# de passer la main à l'utilisateur applicatif via su-exec.
set -e

mkdir -p /app/data
chown -R app:app /app/data

exec su-exec app "$@"
