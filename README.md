# Plex RSS Monitor

[![Docker Pulls](https://img.shields.io/docker/pulls/mrcryllix/plex-rss?style=flat&color=e5a00d&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![Docker Image Size](https://img.shields.io/docker/image-size/mrcryllix/plex-rss/latest?style=flat&color=1f1f1f&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![License](https://img.shields.io/github/license/remi-deher/plex-rss?color=198754&style=flat)](LICENSE)

Application web auto-hébergée qui surveille les watchlists Plex de vos amis et transmet automatiquement les demandes à **Sonarr** (séries) et **Radarr** (films) — ou à **Overseerr** — avec notifications par email, Discord et Telegram.

> [!TIP]
> L'image Docker officielle est disponible sur Docker Hub : [mrcryllix/plex-rss](https://hub.docker.com/r/mrcryllix/plex-rss)

---

## Fonctionnalités

### Intégrations *arr
- **Sonarr & Radarr** — transmission directe via leur API v3 ; support du champ `minimumAvailability` de **Radarr v5**
- **Overseerr** — mode alternatif : les demandes sont routées vers Overseerr plutôt que directement vers Sonarr/Radarr

### Watchlist Plex
- **Polling automatique** — API officielle Plex ou flux RSS, intervalle configurable (défaut 5 min)
- **Authentification Plex SSO** — connexion OAuth pour récupérer le token admin sans le saisir manuellement
- **Source prioritaire + fallback** — bascule automatique entre API et RSS si l'une est indisponible

### Détection de disponibilité
- **Polling périodique** — vérification toutes les 15 min via Sonarr / Radarr / Overseerr
- **Webhooks entrants Sonarr & Radarr** — détection instantanée sur `OnDownload` / `OnImport`
- **Webhook Plex** *(Plex Pass requis)* — détection instantanée sur `library.new` et `media.scrobble` ; correspondance prioritaire par TMDB/TVDB/IMDB ID

### Notifications
- **File de notifications asynchrone** — worker asyncio non-bloquant, les envois n'impactent pas le scheduler
- **Email SMTP** — templates Jinja2 HTML personnalisables, plusieurs adresses par utilisateur (virgule-séparées)
- **Copie admin** — email admin configurable avec toggle par utilisateur Plex
- **Discord** — webhook ; **Telegram** — bot token + chat ID
- Trois événements : nouvelle demande · disponible · échec de transmission

### Interface web
- **Dashboard** — cartes stats cliquables (filtre par statut), affiches en arrière-plan, santé auto-rafraîchie
- **Demandes** — vue grille et tableau, modal enrichi, bouton Retry inline (sans rechargement)
- **Utilisateurs** — gestion des comptes Plex, emails multiples, toggle admin, toggle actif/inactif
- **Logs** — vue en temps réel avec filtre par niveau, recherche textuelle, filtre temporel
- **Paramètres** — navigation par onglets (Connexions / Notifications / Avancé), bouton Enregistrer sticky, badges de connexion persistants, avertissements de configuration incomplète, chargement automatique des profils/dossiers Sonarr/Radarr
- **Import / Export** JSON pour sauvegarde et restauration complète

### Sécurité & Gestion
- **Authentification** — bcrypt + session cookie, wizard de premier démarrage
- **Clé secrète** — générée aléatoirement au premier lancement, persistée dans `data/.secret_key`
- **Multi-utilisateurs** — filtrage par ID Plex, activation/désactivation individuelle

---

## Démarrage rapide

### Prérequis

- Docker et Docker Compose

### `docker-compose.yml`

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

```bash
docker compose up -d
```

L'application est accessible sur **http://localhost:8000**.

### Premier démarrage

1. L'assistant de configuration détecte l'absence de compte et vous guide pour créer le compte administrateur.
2. **Paramètres → Connexions** : configurez Plex (URL + token ou RSS), puis Sonarr + Radarr (ou Overseerr).
3. **Utilisateurs → Synchroniser** : détecte automatiquement les comptes utilisateurs Plex.
4. Le polling démarre automatiquement.
5. *(Optionnel)* **Paramètres → Avancé → Webhooks** : copiez les URLs dans Sonarr / Radarr / Plex pour une détection instantanée.

---

## Configuration

Toute la configuration se fait via l'interface web (aucun fichier `.env` requis).

### Connexions

| Paramètre | Description |
|---|---|
| Plex URL | URL locale de votre serveur Plex |
| Plex Token | Token d'authentification (ou via SSO) |
| Plex RSS URL | URL du flux RSS watchlist admin (Plex Pass) |
| Source prioritaire | `api` ou `rss` avec fallback automatique |
| Intervalle de polling | En minutes (défaut : 5) |
| Sonarr / Radarr | URL, clé API, profil de qualité, dossier racine |
| Radarr minimumAvailability | `announced` / `inCinemas` / `released` / `tba` (v5) |
| Overseerr | URL + clé API (mode alternatif à Sonarr/Radarr) |

### Notifications

| Paramètre | Description |
|---|---|
| SMTP | Hôte, port, identifiants, STARTTLS |
| Email admin | Adresse(s) recevant une copie (virgule-séparées) |
| Discord | URL du webhook |
| Telegram | Token du bot + Chat ID |

### Événements de notification

| Événement | Email | Discord | Telegram |
|---|:---:|:---:|:---:|
| Nouvelle demande | ✓ | ✓ | ✓ |
| Contenu disponible | ✓ | ✓ | ✓ |
| Échec de transmission | ✓ | ✓ | ✓ |

### Webhooks entrants

Configurez ces URLs dans les interfaces respectives pour une détection instantanée (sans attendre le polling) :

| Source | URL | Événement |
|---|---|---|
| Sonarr | `http://<host>:8000/webhook/sonarr` | OnDownload / OnImport |
| Radarr | `http://<host>:8000/webhook/radarr` | OnDownload / OnImport |
| Plex | `http://<host>:8000/webhook/plex` | library.new · media.scrobble |

> [!NOTE]
> Le webhook Plex nécessite **Plex Pass**. La correspondance se fait en priorité par TMDB/TVDB/IMDB ID, puis par titre.

---

## Architecture

```
plex-rss/
├── app/
│   ├── main.py                  # Point d'entrée FastAPI + lifespan
│   ├── models.py                # Modèles SQLAlchemy (Settings, PlexUser, MediaRequest)
│   ├── database.py              # Moteur SQLite, session
│   ├── scheduler.py             # Jobs APScheduler (poll_watchlists, check_arr_statuses)
│   ├── notification_queue.py    # Worker asyncio pour les notifications
│   ├── log_buffer.py            # Handler logging en mémoire (500 entrées)
│   ├── routers/
│   │   ├── auth.py              # Authentification (login, setup, logout)
│   │   ├── api.py               # API REST JSON
│   │   ├── pages.py             # Pages HTML (Jinja2)
│   │   ├── webhook.py           # Webhooks entrants (Sonarr, Radarr, Plex)
│   │   ├── importexport.py      # Import / Export JSON
│   │   └── email_templates.py   # Éditeur de templates email
│   ├── services/
│   │   ├── auth.py              # Bcrypt + clés de session
│   │   ├── watchlist.py         # Agrégateur API + RSS
│   │   ├── plex_api.py          # Client API Plex officielle + SSO OAuth
│   │   ├── plex_rss.py          # Parseur flux RSS Plex
│   │   ├── sonarr.py            # Client API Sonarr v3
│   │   ├── radarr.py            # Client API Radarr v3/v5
│   │   ├── overseerr.py         # Client API Overseerr / Jellyseerr
│   │   ├── email_service.py     # Envoi SMTP (aiosmtplib)
│   │   └── notifications.py     # Discord & Telegram
│   └── templates/               # HTML Bootstrap 5 dark
│       ├── base.html
│       ├── dashboard.html
│       ├── requests.html
│       ├── users.html
│       ├── logs.html
│       ├── settings.html
│       ├── login.html
│       └── setup.html
├── alembic/                     # Migrations SQLite (0001 → 0007)
├── data/                        # Base SQLite + clé secrète (volume, non versionné)
├── .github/workflows/
│   └── dockerhub-description.yml
├── Dockerfile
├── docker-compose.yml
├── DOCKER_HUB.md
└── requirements.txt
```

---

## Développement

### Lancement local sans Docker

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Rebuild Docker après modification

```bash
docker compose up --build -d
docker logs plex-rss -f
```

### Ajouter une migration Alembic

```bash
alembic revision --autogenerate -m "description_du_changement"
alembic upgrade head
```

---

## Stack technique

| Composant | Technologie |
|---|---|
| Framework web | FastAPI |
| Sécurité / Session | Bcrypt, Starlette SessionMiddleware |
| Base de données | SQLite + SQLAlchemy + Alembic |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Notifications async | asyncio.Queue worker |
| Client HTTP | httpx (async) |
| Parseur RSS | feedparser |
| Email | aiosmtplib |
| Templates | Jinja2 + Bootstrap 5 dark |
| Conteneurisation | Docker + Docker Compose |

---

## Licence

[MIT](LICENSE) — Copyright (c) 2026 DEHER Rémi
