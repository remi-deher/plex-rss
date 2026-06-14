# Plex RSS Monitor

[![Docker Pulls](https://img.shields.io/docker/pulls/mrcryllix/plex-rss?style=flat&color=e5a00d&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![Docker Image Size](https://img.shields.io/docker/image-size/mrcryllix/plex-rss/latest?style=flat&color=1f1f1f&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![GitHub](https://img.shields.io/badge/GitHub-remi--deher%2Fplex--rss-181717?style=flat&logo=github)](https://github.com/remi-deher/plex-rss)
[![License](https://img.shields.io/github/license/remi-deher/plex-rss?color=198754&style=flat)](https://github.com/remi-deher/plex-rss/blob/main/LICENSE)

---

## 🇬🇧 English

Self-hosted web application that monitors your friends' Plex watchlists and automatically forwards requests to **Sonarr** (TV shows) and **Radarr** (movies), with notifications via email, Discord, and Telegram.

### Features

- **Secure authentication** — username/password login with session cookies and a first-run setup wizard
- **Automatic watchlist polling** — Plex official API or RSS feed, configurable interval (default 5 min)
- **Sonarr & Radarr integration** — direct submission via their v3 API; Radarr v5 `minimumAvailability` supported
- **Overseerr support** — use Overseerr as an alternative routing backend instead of direct Sonarr/Radarr
- **Availability tracking** — periodic polling + inbound webhooks (Sonarr, Radarr, Plex)
- **Plex webhook** — instant availability detection on `library.new` / `media.scrobble` events (requires Plex Pass)
- **Notifications** — email (SMTP, per-user addresses, admin copy), Discord webhook, Telegram bot
- **Notification queue** — async worker, non-blocking scheduler
- **Multi-user** — per-user Plex filtering, enable/disable, individual notification email
- **Admin notifications** — configurable admin email copy with per-user toggle
- **Web UI** — responsive dark-theme dashboard, request list, user management, live logs, settings
- **Import / Export** — full JSON backup and restore

### Quick Start

```yaml
services:
  plex-rss:
    image: mrcryllix/plex-rss:latest
    container_name: plex-rss
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Europe/Paris
    restart: unless-stopped
```

Open **http://localhost:8000** — the setup wizard will guide you through creating an admin account.

### First-Run Setup

1. Open the app; the wizard prompts you to create an admin account.
2. Go to **Settings → Connexions** to configure Plex (URL + token or RSS feed), Sonarr, Radarr (or Overseerr).
3. Go to **Users → Sync from RSS** to auto-discover Plex user accounts.
4. Polling starts automatically. Optionally configure Sonarr/Radarr/Plex webhooks for instant detection.

### Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI |
| Auth | Bcrypt + Starlette sessions |
| Database | SQLite + SQLAlchemy + Alembic |
| Scheduler | APScheduler (AsyncIOScheduler) |
| HTTP client | httpx (async) |
| Email | aiosmtplib |
| Templates | Jinja2 + Bootstrap 5 dark |

---

## 🇫🇷 Français

Application web auto-hébergée qui surveille les watchlists Plex de vos amis et transmet automatiquement les demandes à **Sonarr** (séries) et **Radarr** (films), avec notifications par email, Discord et Telegram.

### Fonctionnalités

- **Authentification sécurisée** — connexion par identifiant/mot de passe avec cookies de session et assistant de configuration au premier lancement
- **Polling automatique des watchlists** — API officielle Plex ou flux RSS, intervalle configurable (5 min par défaut)
- **Intégration Sonarr & Radarr** — transmission directe via leur API v3 ; support du champ `minimumAvailability` de Radarr v5
- **Support Overseerr** — utilisation d'Overseerr comme backend de routage alternatif à Sonarr/Radarr
- **Suivi de disponibilité** — polling périodique + webhooks entrants (Sonarr, Radarr, Plex)
- **Webhook Plex** — détection instantanée de disponibilité sur les événements `library.new` / `media.scrobble` (nécessite Plex Pass)
- **Notifications** — email (SMTP, adresses par utilisateur, copie admin), webhook Discord, bot Telegram
- **File de notifications** — worker asyncio non-bloquant pour le scheduler
- **Multi-utilisateurs** — filtrage par utilisateur Plex, activation/désactivation, email de notification individuel
- **Notifications admin** — copie admin configurable avec toggle par utilisateur
- **Interface web** — dashboard dark responsive, liste des demandes, gestion utilisateurs, logs en direct, paramètres
- **Import / Export** — sauvegarde et restauration complète en JSON

### Démarrage rapide

```yaml
services:
  plex-rss:
    image: mrcryllix/plex-rss:latest
    container_name: plex-rss
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Europe/Paris
    restart: unless-stopped
```

Ouvrez **http://localhost:8000** — l'assistant de configuration vous guide pour créer le compte administrateur.

### Premier démarrage

1. Ouvrez l'application ; l'assistant vous invite à créer un compte administrateur.
2. Allez dans **Paramètres → Connexions** pour configurer Plex (URL + token ou flux RSS), Sonarr, Radarr (ou Overseerr).
3. Allez dans **Utilisateurs → Synchroniser depuis le RSS** pour détecter automatiquement les comptes utilisateurs Plex.
4. Le polling démarre automatiquement. Configurez optionnellement les webhooks Sonarr/Radarr/Plex pour une détection instantanée.

### Stack technique

| Couche | Technologie |
|---|---|
| Framework web | FastAPI |
| Authentification | Bcrypt + sessions Starlette |
| Base de données | SQLite + SQLAlchemy + Alembic |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Client HTTP | httpx (async) |
| Email | aiosmtplib |
| Templates | Jinja2 + Bootstrap 5 dark |

---

**GitHub** : [remi-deher/plex-rss](https://github.com/remi-deher/plex-rss) — Issues, contributions and feature requests welcome.
