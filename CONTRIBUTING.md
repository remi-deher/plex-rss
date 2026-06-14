# Contributing to Plex RSS Monitor

Merci de l'intérêt que vous portez au projet. Ce guide couvre tout ce dont vous avez besoin pour proposer une contribution.

---

## Table des matières

1. [Prérequis](#prérequis)
2. [Installation de l'environnement de développement](#installation-de-lenvironnement-de-développement)
3. [Lancer l'application en local](#lancer-lapplication-en-local)
4. [Tests](#tests)
5. [Lint et formatage](#lint-et-formatage)
6. [Migrations de base de données](#migrations-de-base-de-données)
7. [Soumettre une Pull Request](#soumettre-une-pull-request)
8. [Architecture du projet](#architecture-du-projet)
9. [Questions fréquentes](#questions-fréquentes)

---

## Prérequis

- Python 3.12+
- Docker + Docker Compose (pour tester l'image complète)
- Git

---

## Installation de l'environnement de développement

```bash
git clone https://github.com/remi-deher/plex-rss.git
cd plex-rss

python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install pytest pytest-asyncio
```

Initialisez la base de données :

```bash
alembic upgrade head
```

---

## Lancer l'application en local

```bash
uvicorn app.main:app --reload
```

L'application est accessible sur **http://localhost:8000**.

Pour tester avec Docker (comportement identique à la production) :

```bash
docker compose up --build -d
docker logs plex-rss -f
```

> Après chaque modification du code, relancez `docker compose up --build -d` pour reconstruire l'image.

---

## Tests

La suite de tests utilise **pytest** + **pytest-asyncio**. Tous les tests sont dans `tests/`.

```bash
# Lancer tous les tests
python -m pytest -v

# Lancer un fichier spécifique
python -m pytest tests/test_scheduler.py -v

# Lancer un test précis
python -m pytest tests/test_scheduler.py::test_poll_new_item_creates_request_and_notifies -v
```

### Conventions

- Chaque fichier de service a son fichier de test miroir : `app/services/sonarr.py` → `tests/test_sonarr.py`.
- Les tests unitaires mockent toujours les appels réseau (`httpx`, `aiosmtplib`) et ne touchent jamais de services externes réels.
- Les tests qui accèdent à la base de données utilisent une DB SQLite **in-memory** avec `StaticPool` pour l'isolation entre les tests.
- Les endpoints FastAPI sont testés via `TestClient` avec `dependency_overrides` pour bypasser l'authentification et injecter la DB de test.

### Structure des tests

| Fichier | Ce qu'il teste |
|---|---|
| `test_sonarr.py` | Client API Sonarr v3 |
| `test_radarr.py` | Client API Radarr v3/v5 |
| `test_overseerr.py` | Client API Overseerr |
| `test_plex_api.py` | Client API Plex officielle |
| `test_notification_queue.py` | Worker de notifications async |
| `test_scheduler.py` | `poll_watchlists` et `check_arr_statuses` |
| `test_watchlist.py` | Routage API vs RSS, fallback |
| `test_email_service.py` | Construction et envoi des emails |
| `test_api_settings.py` | Endpoints `/api/settings` et `/api/test/*` |
| `test_api_requests.py` | Endpoints `/api/requests` |
| `test_api_health_metrics.py` | Endpoints `/api/health` et `/api/metrics` |
| `test_metrics.py` | Compteurs in-memory (`app/metrics.py`) |

---

## Lint et formatage

Le projet utilise **ruff** pour le lint et le formatage (configuration dans `ruff.toml`).

```bash
# Vérifier sans modifier
python -m ruff check .
python -m ruff format --check .

# Corriger automatiquement
python -m ruff check --fix .
python -m ruff format .
```

Règles activées : `E`, `F`, `W` (erreurs, avertissements PEP8), `I` (tri des imports).

Les imports doivent être ordonnés : **stdlib → third-party → local**.

Les deux CI (lint + tests) doivent passer avant tout merge.

---

## Migrations de base de données

Le schéma évolue via **Alembic**. Chaque modification de `app/models.py` nécessite une migration.

```bash
# Générer une migration automatique
alembic revision --autogenerate -m "description_courte"

# Appliquer les migrations
alembic upgrade head

# Revenir en arrière d'une version
alembic downgrade -1
```

Les migrations sont dans `alembic/versions/`. Vérifiez toujours le fichier généré avant de le committer — Alembic peut manquer des cas complexes (contraintes, renommages).

---

## Soumettre une Pull Request

1. **Forkez** le dépôt et créez une branche depuis `main` :
   ```bash
   git checkout -b feat/ma-fonctionnalite
   ```

2. **Développez** votre fonctionnalité ou correctif.

3. **Ajoutez des tests** couvrant les nouveaux comportements. Les PRs sans tests seront demandées en révision.

4. **Vérifiez** que lint et tests passent localement :
   ```bash
   python -m ruff check .
   python -m pytest -v
   ```

5. **Commitez** avec un message clair :
   ```
   feat: ajouter support Jellyfin
   fix: corriger le fallback RSS quand plex_token est None
   ```

6. **Ouvrez une Pull Request** vers `main` avec une description expliquant le *pourquoi* du changement.

### Ce qui bloque le merge

- Lint ruff en échec
- Au moins un test en échec
- Scan de sécurité Trivy avec des CVE critiques ou élevées non justifiées

---

## Architecture du projet

```
app/
├── main.py                  # Point d'entrée FastAPI, lifespan (scheduler + worker)
├── models.py                # Modèles SQLAlchemy : Settings, PlexUser, MediaRequest
├── database.py              # Engine SQLite, SessionLocal, get_db
├── scheduler.py             # poll_watchlists() + check_arr_statuses() (APScheduler)
├── notification_queue.py    # Worker asyncio.Queue pour les emails / Discord / Telegram
├── metrics.py               # Compteurs in-memory (latences, taux d'erreur)
├── log_buffer.py            # Handler logging circulaire (500 entrées, vue /logs)
├── routers/
│   ├── api.py               # API REST JSON (/api/*)
│   ├── auth.py              # Login, logout, setup wizard
│   ├── pages.py             # Pages HTML rendues côté serveur (Jinja2)
│   ├── webhook.py           # Webhooks entrants Sonarr / Radarr / Plex
│   ├── importexport.py      # Import / Export JSON
│   └── email_templates.py   # Éditeur de templates email custom
└── services/
    ├── watchlist.py         # Agrégateur API + RSS avec fallback
    ├── plex_api.py          # Client API Plex officielle (watchlists, SSO OAuth)
    ├── plex_rss.py          # Parseur flux RSS Plex
    ├── sonarr.py            # Client Sonarr v3
    ├── radarr.py            # Client Radarr v3/v5
    ├── overseerr.py         # Client Overseerr / Jellyseerr
    ├── email_service.py     # Envoi SMTP via aiosmtplib, templates Jinja2
    ├── notifications.py     # Discord webhook + Telegram bot
    └── auth.py              # Bcrypt hash, vérification de session
```

### Flux de données principal

```
Plex API / RSS
      │
      ▼
 fetch_watchlist()          ← watchlist.py (routage + fallback)
      │
      ▼
 poll_watchlists()          ← scheduler.py (toutes les N minutes)
      │
      ├─► _submit_to_arr()  → Sonarr / Radarr / Overseerr
      │
      └─► enqueue()         → notification_queue.py
                                    │
                                    ├─► email_service.py (SMTP)
                                    ├─► notifications.py (Discord)
                                    └─► notifications.py (Telegram)

check_arr_statuses()        ← scheduler.py (toutes les 15 min)
      │
      └─► is_*_available()  → Sonarr / Radarr / Overseerr
              │
              └─► enqueue("available") si disponible
```

---

## Questions fréquentes

**Puis-je ajouter un nouveau service *arr ?**
Oui. Créez `app/services/monservice.py` avec `check_connection`, `request_media` (ou `add_*`), et `is_*_available`. Branchez-le dans `scheduler.py` et `api.py`. Ajoutez les colonnes correspondantes dans `models.py` avec une migration Alembic.

**Comment déboguer le scheduler ?**
Les logs du scheduler sont accessibles dans l'UI sous **Logs**, ou via `docker logs plex-rss -f`. Le niveau DEBUG peut être activé en modifiant `logging.basicConfig` dans `main.py`.

**Les tests modifient-ils ma base de données locale ?**
Non. Tous les tests utilisent une base SQLite in-memory créée et détruite pour chaque test. Votre `data/plex_rss.db` n'est jamais touchée.

**Comment tester un webhook localement ?**
Avec [ngrok](https://ngrok.com/) ou [localtunnel](https://theboroer.github.io/localtunnel-www/) pour exposer `localhost:8000` sur internet, puis configurez l'URL dans Sonarr/Radarr/Plex.
