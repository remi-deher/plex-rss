# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/), et ce projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

> Ce fichier est généré automatiquement par [git-cliff](https://git-cliff.org/) lors de chaque release.

## [v1] - 2026-06-15

### ✨ Nouveautés

- Surveillance des watchlists Plex via API officielle et flux RSS
- Transmission automatique vers Sonarr, Radarr et Overseerr
- Polling configurable (défaut : 5 minutes)
- Détection de disponibilité via webhooks Sonarr, Radarr et Plex
- Notifications Email (SMTP), Discord et Telegram
- Interface web Bootstrap 5 dark (dashboard, demandes, utilisateurs, logs, paramètres)
- Authentification bcrypt + session cookie, wizard de premier démarrage
- Import / Export JSON
- Éditeur de templates email Jinja2
- Endpoint `/api/health` structuré avec latences par service
- Endpoint `/api/metrics` avec compteurs runtime
- Suite de tests (155 tests, pytest + pytest-asyncio)
- Publication Docker Hub (`mrcryllix/plex-rss`) et GHCR (`ghcr.io/remi-deher/plex-rss`)
