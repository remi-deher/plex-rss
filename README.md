# Plex RSS Monitor

[![Docker Pulls](https://img.shields.io/docker/pulls/mrcryllix/plex-rss?style=flat-flat&color=e5a00d&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![Docker Image Size](https://img.shields.io/docker/image-size/mrcryllix/plex-rss/latest?style=flat-flat&color=1f1f1f&logo=docker&logoColor=white)](https://hub.docker.com/r/mrcryllix/plex-rss)
[![License](https://img.shields.io/github/license/remi-deher/plex-rss?color=198754&style=flat-flat)](LICENSE)

Application web auto-hébergée qui surveille les watchlists Plex de vos amis et transmet automatiquement les demandes à **Sonarr** (séries) et **Radarr** (films), avec notifications par email, Discord et Telegram.

> [!TIP]
> L'image Docker officielle est disponible sur Docker Hub à l'adresse suivante : [mrcryllix/plex-rss](https://hub.docker.com/r/mrcryllix/plex-rss).

## Fonctionnalités

- **Authentification sécurisée** : Accès protégé par nom d'utilisateur et mot de passe avec session cookie.
- **Wizard de configuration initiale** : Assistant pas-à-pas interactif lors de la première connexion pour configurer le premier compte administrateur.
- **Polling automatique** des watchlists Plex (API officielle ou flux RSS, configurable)
- **Transmission** vers Sonarr et Radarr via leurs API v3
- **Suivi de disponibilité** par polling périodique (pas de webhook requis)
- **Notifications** : email (SMTP + templates Jinja2 personnalisables), Discord, Telegram
- **Interface web** responsive (dark theme) avec dashboard, page demandes, gestion utilisateurs
- **Multi-utilisateurs** : filtrage par utilisateur Plex, désactivation individuelle
- **Import/Export** JSON pour la sauvegarde de configuration


## Architecture

```
plex-rss/
├── app/
│   ├── main.py              # Point d'entrée FastAPI + lifespan + SessionMiddleware
│   ├── models.py            # Modèles SQLAlchemy (Settings, PlexUser, MediaRequest)
│   ├── database.py          # Moteur SQLite, migrations, session
│   ├── scheduler.py         # Jobs APScheduler (poll_watchlists, check_arr_statuses)
│   ├── routers/
│   │   ├── auth.py          # Routes d'authentification (login, setup, logout)
│   │   ├── api.py           # API REST JSON (protégée)
│   │   ├── pages.py         # Pages HTML (Jinja2, protégées)
│   │   ├── webhook.py       # Endpoint webhook entrant
│   │   ├── importexport.py  # Import/Export JSON (protégé)
│   │   └── email_templates.py # Éditeur de templates (protégé)
│   ├── services/
│   │   ├── auth.py          # Service d'authentification bcrypt et clés de session
│   │   ├── watchlist.py     # Agrégateur API + RSS
│   │   ├── plex_api.py      # Client API Plex officielle
│   │   ├── plex_rss.py      # Parseur flux RSS Plex
│   │   ├── sonarr.py        # Client API Sonarr v3
│   │   ├── radarr.py        # Client API Radarr v3
│   │   ├── email_service.py # Envoi SMTP (aiosmtplib)
│   │   └── notifications.py # Discord & Telegram push
│   └── templates/           # Templates HTML Bootstrap 5 dark
│       ├── login.html       # Page de connexion
│       └── setup.html       # Assistant de configuration de compte
├── alembic/                 # Migrations de base de données
├── data/                    # Base SQLite & clé secrète (volume Docker, non versionné)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Démarrage rapide

### Prérequis

- Docker et Docker Compose

### Lancement

1. Clonez le dépôt et rendez-vous dans le dossier :
   ```bash
   git clone https://github.com/<votre-username>/plex-rss.git
   cd plex-rss
   ```
2. Lancez l'application :
   ```bash
   docker compose up -d
   ```

L'application est accessible sur **http://localhost:8000**.

### Exemple de `docker-compose.yml`

Voici un exemple type de configuration pour déployer l'application en production :

```yaml
version: '3.8'

services:
  plex-rss:
    image: plex-rss-plex-rss:latest # Ou construit localement : build: .
    container_name: plex-rss
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Europe/Paris
    restart: unless-stopped
```

## Premier démarrage et Sécurité

1. Lors de votre première connexion sur **http://localhost:8000**, l'application détecte qu'aucun compte n'est configuré et affiche un **assistant de configuration (Wizard)**.
2. Créez votre compte administrateur en définissant un nom d'utilisateur et un mot de passe (au moins 8 caractères, force évaluée en temps réel).
3. Une fois le compte créé, vous serez automatiquement connecté.
4. Allez dans **Paramètres** pour configurer vos services :
   - L'URL RSS Plex (ou le token API Plex)
   - Sonarr : URL + clé API + profil de qualité + dossier racine
   - Radarr : URL + clé API + profil de qualité + dossier racine
5. Allez sur **Utilisateurs** → **Synchroniser depuis le RSS** pour détecter les comptes utilisateurs Plex.
6. Le polling démarre automatiquement (intervalle configurable, 5 min par défaut).

## Sécurité des Sessions

La clé secrète nécessaire au chiffrement des cookies de session est générée aléatoirement lors du premier lancement et stockée dans le fichier `data/.secret_key`. Cela garantit la persistance des sessions connectées même après un redémarrage ou une mise à jour du conteneur Docker, à condition que le dossier `/app/data` soit monté sur un volume persistant.

## Configuration

Toute la configuration se fait via l'interface web (aucun fichier `.env` requis).

| Paramètre | Description |
|---|---|
| Plex RSS URL | URL du flux RSS de la watchlist admin Plex |
| Plex Token | Token d'authentification API Plex (optionnel si RSS configuré) |
| Source prioritaire | `rss` ou `api` (avec fallback automatique) |
| Intervalle de polling | En minutes (défaut : 5) |
| Sonarr / Radarr | URL, clé API, profil de qualité, dossier racine |
| SMTP | Hôte, port, identifiants, TLS/STARTTLS |
| Discord | URL du webhook |
| Telegram | Token du bot + Chat ID |

## Notifications

Trois événements déclenchent des notifications :

| Événement | Email | Discord | Telegram |
|---|:---:|:---:|:---:|
| Nouvelle demande | ✓ | ✓ | ✓ |
| Disponible | ✓ | ✓ | ✓ |
| Échec de transmission | ✓ | ✓ | ✓ |

Les templates email sont personnalisables via **Paramètres → Templates email** (Jinja2 HTML).

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
docker compose build
docker compose up -d
docker logs plex-rss -f
```

### Ajouter une migration Alembic

```bash
alembic revision --autogenerate -m "description_du_changement"
alembic upgrade head
```

## Stack technique

| Composant | Technologie |
|---|---|
| Framework web | FastAPI |
| Sécurité / Session | Bcrypt natif, Starlette Session |
| Base de données | SQLite + SQLAlchemy + Alembic |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Client HTTP | httpx (async) |
| Parseur RSS | feedparser |
| Email | aiosmtplib |
| Templates | Jinja2 + Bootstrap 5 (dark) |
| Conteneurisation | Docker + Docker Compose |

## Licence

[MIT](LICENSE) — Copyright (c) 2026 DEHER Rémi

