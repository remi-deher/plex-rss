<p align="center">
  <img src="docs/assets/banner.svg" alt="Plexarr — hub self-hosted de demandes, d'acquisition et de disponibilité pour Plex et *arr" width="100%">
</p>

<p align="center">
  <a href="https://github.com/remi-deher/plex-rss/actions/workflows/tests.yml"><img alt="Unit Tests" src="https://github.com/remi-deher/plex-rss/actions/workflows/tests.yml/badge.svg"></a>
  <a href="https://github.com/remi-deher/plex-rss/actions/workflows/e2e.yml"><img alt="Responsive E2E" src="https://github.com/remi-deher/plex-rss/actions/workflows/e2e.yml/badge.svg"></a>
  <a href="https://github.com/remi-deher/plex-rss/actions/workflows/docker-publish.yml"><img alt="Docker" src="https://github.com/remi-deher/plex-rss/actions/workflows/docker-publish.yml/badge.svg"></a>
  <a href="https://hub.docker.com/r/mrcryllix/plex-rss"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/mrcryllix/plex-rss?logo=docker&color=e5a00d"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/remi-deher/plex-rss"></a>
</p>

<p align="center"><a href="README.md">🇬🇧 English</a> · <strong>🇫🇷 Français</strong></p>

<p align="center">
  <strong>Plexarr transforme « quelqu'un veut un film » en « il tourne dans la bonne langue », sans que tu touches à un tableur.</strong>
</p>

> [!NOTE]
> Le projet s'appelait auparavant *Plex RSS Monitor*. Le dépôt et l'image conservent le nom technique `plex-rss`, mais l'application s'appelle désormais **Plexarr**.

---

## Pourquoi Plexarr

Overseerr et Jellyseerr sont excellents à l'entrée : ils laissent les gens demander un média et le transmettent à Sonarr/Radarr. Plexarr part de la même porte d'entrée, mais reste impliqué sur tout le trajet — il surveille le téléchargement, détecte les imports bloqués, confirme que le titre est *réellement* dans Plex, et — là où il gagne son nom — vérifie que la piste audio demandée (VF, VO, partielle) est vraiment présente avant de notifier qui que ce soit.

| | Plexarr | Gestionnaire de demandes classique |
|---|---|---|
| Sources de demandes | Watchlist Plex (API + RSS), interface, API, Overseerr/Jellyseerr | Interface, API |
| Suivi après approbation | Téléchargement → import → disponibilité Plex → analyse des pistes audio | Envoie à Sonarr/Radarr, s'arrête généralement là |
| Détection d'import bloqué | Oui — signale « téléchargé mais jamais importé » après deux contrôles consécutifs | Non |
| Suivi de langue/doublage | Par saison, par épisode : VO, VF, VF secondaire, couverture partielle | Non |
| Notifications | Regroupées par jalon (un message pour toute une saison, pas un par épisode) | Par événement, peut inonder |
| Déploiement | Docker Compose : API + worker + PostgreSQL + Redis | Variable |

Si tu utilises déjà Overseerr/Jellyseerr pour l'interface de demande et que tu veux juste le suivi acquisition → disponibilité, l'entrée propre de Plexarr (API/interface/watchlist) permet aussi de l'utiliser seul — l'intégration Seerr est optionnelle, pas obligatoire.

## Captures d'écran

<table>
<tr>
<td width="50%"><img src="docs/assets/screenshot-discover.png" alt="Page Découvrir : carrousel à la une et rangée de tendances"></td>
<td width="50%"><img src="docs/assets/screenshot-calendar.png" alt="Page Calendrier : vue mensuelle des sorties et disponibilités"></td>
</tr>
<tr>
<td>Découvrir — parcourir et demander en un clic.</td>
<td>Calendrier — sorties et disponibilités en un coup d'œil.</td>
</tr>
</table>

> [!NOTE]
> Ces captures utilisent des données de démonstration générées pour l'occasion, capturées sur la vraie interface (aucune bibliothèque Plex ni instance personnelle réelle n'est montrée).

## Ce que fait Plexarr

### Demandes et orchestration
- Entrées depuis la **Watchlist Plex API**, un flux **RSS Plex**, l'API Plexarr, l'interface Découvrir ou **Overseerr/Jellyseerr**.
- Routage direct vers plusieurs instances **Sonarr** et **Radarr**.
- Approbation facultative, co-demandeurs et historique de la provenance.
- Recherche de releases via Prowlarr et ajout direct à un client compatible.
- Prise en charge des séries complètes, de quelques saisons ou d'un épisode unique.

### Téléchargements et imports
- File unifiée Sonarr/Radarr et clients directs.
- Progression, temps restant, état opérationnel et raison d'attente.
- Détection d'un téléchargement terminé mais bloqué à l'import.
- Confirmation après deux contrôles consécutifs pour limiter les faux blocages.
- Association et import manuels depuis l'interface.

### Disponibilité Plex et langues
- Séparation claire entre demande, transmission \*arr, téléchargement, import et disponibilité Plex.
- Synchronisation des médias déjà présents dans Plex, pas seulement des nouvelles demandes.
- Couverture par saison et épisode, pas juste « la série existe ».
- Analyse VO, VF, VF secondaire et disponibilité partielle.
- Gestion des films, séries complètes, saisons complètes et épisodes isolés.

### Notifications
- Email SMTP, Discord, Telegram, ntfy et Gotify.
- Modèles personnalisables avec aperçu et simulation par utilisateur.
- Jalons regroupés pour éviter un email par épisode lors de l'ajout d'une série complète.
- Événements séparés pour demande, disponibilité, amélioration VF, correction et échec.
- Historique par média et par utilisateur, avec canal, destinataire et résultat.
- Bascule globale permettant de bloquer les envois sans interrompre l'analyse.

### Interface responsive
- Sidebar repliable sur ordinateur et tablette, navigation mobile avec safe areas.
- Dashboard et activité sur 30 jours par demandes, disponibilités ou notifications.
- Bibliothèque avec filtres compacts.
- Calendrier Agenda/Mois et téléchargements regroupés par action requise.
- Fiches média avec timeline, couverture, prochaines sorties, demandes et notifications.
- Paramètres avec vue d'ensemble et recherche.
- Centre d'exploitation, maintenance, journaux et incidents.
- Gestion des utilisateurs, permissions, notifications et activité.

## Le parcours d'une demande

```mermaid
flowchart LR
    A["Watchlist Plex<br/>API / RSS"] --> D["Demande Plexarr"]
    B["Découvrir<br/>Ajout manuel"] --> D
    C["API / Seerr"] --> D
    D --> E{"Approbation<br/>requise ?"}
    E -->|Oui| F["Validation admin"]
    E -->|Non| G["Sonarr / Radarr"]
    F --> G
    G --> H["Client de téléchargement"]
    H --> I{"Import réussi ?"}
    I -->|Non| J["Intervention requise"]
    J --> I
    I -->|Oui| K["Plex détecte le média"]
    K --> L["Analyse VO / VF<br/>et couverture"]
    L --> M["Notification regroupée"]
```

Le point d'entrée est conservé pendant tout le parcours. Une demande API ou Watchlist portant sur une série implique toutes les saisons hors saison 0, tandis qu'une demande manuelle peut cibler seulement certaines saisons ou un épisode.

## Architecture

```mermaid
flowchart TB
    UI["Vue 3 responsive"] --> API["FastAPI"]
    API --> PG[("PostgreSQL 15")]
    API --> REDIS[("Redis 7")]
    REDIS --> WORKER["Worker ARQ"]
    WORKER --> PLEX["Plex"]
    WORKER --> ARR["Sonarr / Radarr"]
    WORKER --> CLIENTS["Clients de téléchargement"]
    WORKER --> CHANNELS["Email / Discord / Telegram<br/>ntfy / Gotify"]
    PLEX -->|Webhooks / synchronisation| API
    ARR -->|Webhooks / état de file| API
```

| Composant | Rôle |
|---|---|
| `plex-rss` | API FastAPI, interface Vue, webhooks et flux d'événements temps réel |
| `worker` | Jobs ARQ, polling, analyse, notifications et traitements longs |
| `db` | PostgreSQL 15, source de vérité |
| `redis` | File ARQ, heartbeat, cache et signaux temps réel (via Redis Streams) |
| `backup` / `restore` | Outils PostgreSQL activés par le profil Compose `operations` |

### La stack, précisément

| Couche | Choix | Pourquoi |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic | Gestion async typée des requêtes ; les migrations sont obligatoires, pas optionnelles, pour un système qui ne doit jamais perdre une demande silencieusement. |
| Traitement asynchrone | ARQ sur Redis | Un worker dédié sort le polling/l'analyse/les notifications du chemin de requête — l'API reste réactive même pendant une grosse synchronisation. |
| Frontend | Vue 3 (Composition API), Vite, vue-router | SPA servie par le montage statique de FastAPI ; pas de déploiement frontend séparé. |
| Temps réel | Server-Sent Events (`/api/events`) adossé à Redis Streams | SSE + broker de messages garde les clients synchronisés sans polling, et `Last-Event-ID` permet à un onglet qui se reconnecte de reprendre au lieu de rater des signaux — les événements ne portent aucune donnée métier, le client recharge via le REST classique, donc les permissions ne sont jamais contournées. |
| Données | PostgreSQL 15 | Deux tables centrales portent l'essentiel du domaine : `media_requests` (cycle de vie de la demande : statut, fulfillment_status, rattachement \*arr, granularité VF) et `library_items` (ce qui est réellement confirmé présent dans Plex, avec son propre état VF/VO) — rapprochées à l'affichage plutôt que fusionnées, pour ne jamais confondre « demandé » et « présent ». |
| Secrets | `cryptography.Fernet`, clé dans `PLEXARR_ENCRYPTION_KEY` | Les tokens Plex/\*arr/notifications sont chiffrés au repos ; la clé vit volontairement en dehors du dump de la base. |
| Intégrations | `plexapi`, REST + webhooks Sonarr/Radarr, Prowlarr | Les webhooks réduisent la latence de détection à presque zéro ; le polling reste actif en filet de sécurité pour qu'un webhook manqué ne bloque jamais une demande définitivement. |
| Authentification | SSO OAuth Plex, WebAuthn (passkeys), cookies de session | Aucune base de mots de passe à fuiter ; les passkeys sont un durcissement optionnel par-dessus le SSO Plex. |
| Packaging | Build Docker multi-étapes `python:3.12-alpine` | La même image fait tourner l'API et le worker — seule la commande du conteneur change. |

## Installation Docker

### Prérequis

- Docker Engine 24+ ou Docker Desktop récent.
- Docker Compose v2.
- Un répertoire persistant pour `data/` et `backups/`.

### 1. Récupérer la configuration

```bash
git clone https://github.com/remi-deher/plex-rss.git
cd plex-rss
cp .env.example .env
```

Sous PowerShell :

```powershell
Copy-Item .env.example .env
```

### 2. Générer les secrets

Définissez dans `.env` un mot de passe PostgreSQL long, puis générez la clé de chiffrement :

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```dotenv
TZ=Europe/Paris
POSTGRES_DB=plexrss
POSTGRES_PASSWORD=remplacer-par-un-secret-long
PLEXARR_ENCRYPTION_KEY=coller-la-cle-fernet
ARQ_MAX_JOBS=4
ARQ_JOB_TIMEOUT=3600
BACKUP_RETENTION_DAYS=14
```

> [!CAUTION]
> Conservez `PLEXARR_ENCRYPTION_KEY`. La perdre empêche de déchiffrer les secrets déjà enregistrés. Ne publiez jamais votre fichier `.env`.

### 3. Démarrer

Le fichier du dépôt construit l'image locale :

```bash
docker compose up -d --build
docker compose ps
```

L'application est ensuite disponible sur [http://localhost:8000](http://localhost:8000).

Pour utiliser uniquement l'image publiée, remplacez `build: .` par :

```yaml
image: mrcryllix/plex-rss:latest
```

dans les services `plex-rss` et `worker`.

> [!TIP]
> `latest` suit `main` et change à chaque merge : pratique pour un usage personnel, plus risqué en production car une régression est livrée dès le prochain `docker compose pull`. Pour un déploiement stable, préférez épingler une version taguée (`vX.Y.Z`, construite depuis un tag Git) et ne montez de version qu'après avoir lu le [changelog](CHANGELOG.md). Les images sont publiées à la fois sur Docker Hub (`mrcryllix/plex-rss`) et GitHub Container Registry (`ghcr.io/remi-deher/plex-rss`), seule l'architecture `linux/amd64` est construite pour le moment.

### Déploiement minimal complet

```yaml
services:
  plex-rss:
    image: mrcryllix/plex-rss:latest
    ports: ["8000:8000"]
    volumes: ["./data:/app/data"]
    env_file: [.env]
    environment:
      DATABASE_URL: postgresql://plexrss:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-plexrss}
      REDIS_URL: redis://redis:6379/0
      ENABLE_ARQ: "1"
      ENABLE_LEGACY_SCHEDULER: "0"
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    restart: unless-stopped

  worker:
    image: mrcryllix/plex-rss:latest
    command: ["arq", "app.jobs.WorkerSettings"]
    volumes: ["./data:/app/data"]
    env_file: [.env]
    environment:
      DATABASE_URL: postgresql://plexrss:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-plexrss}
      REDIS_URL: redis://redis:6379/0
      ENABLE_ARQ: "1"
    depends_on:
      plex-rss: { condition: service_healthy }
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: plexrss
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-plexrss}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U plexrss -d ${POSTGRES_DB:-plexrss}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes: ["redisdata:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
```

## Premier démarrage

1. Ouvrez l'application et créez le compte propriétaire.
2. Dans **Paramètres → Vue d'ensemble**, vérifiez les sections incomplètes.
3. Configurez Plex, puis Sonarr/Radarr et leurs dossiers racines.
4. Synchronisez les utilisateurs Plex.
5. Configurez au moins un canal de notification.
6. Lancez les tests de connexion depuis l'interface.
7. Ajoutez les webhooks pour réduire le délai de détection.

## Configuration des intégrations

### Webhooks

Utilisez une URL Plexarr accessible depuis les conteneurs ou serveurs sources :

| Source | URL | Événements utiles |
|---|---|---|
| Sonarr | `https://plexarr.example.com/webhook/sonarr` | Download / Import / Upgrade |
| Radarr | `https://plexarr.example.com/webhook/radarr` | Download / Import / Upgrade |
| Plex | `https://plexarr.example.com/webhook/plex` | `library.new`, événements média |

Le polling reste actif comme mécanisme de rattrapage. Le webhook Plex nécessite un abonnement Plex Pass.

### Reverse proxy

Le proxy doit transmettre `Host`, `X-Forwarded-For` et `X-Forwarded-Proto`, autoriser les webhooks et ne pas mettre en cache `/api/events`, qui utilise SSE.

### Stockage et permissions

- `pgdata` contient la base PostgreSQL.
- `redisdata` conserve Redis en mode AOF.
- `./data` conserve la clé de session et les éventuelles données de migration SQLite.
- `./backups` reçoit les dumps PostgreSQL.

## Exploitation

### Vérifications rapides

```bash
docker compose ps
docker compose logs --tail=100 plex-rss
docker compose logs --tail=100 worker
docker compose exec worker arq --check app.jobs.WorkerSettings
docker compose exec redis redis-cli ping
docker compose exec db pg_isready -U plexrss -d plexrss
```

| Endpoint | Usage |
|---|---|
| `/api/health` | Santé de Plex, des instances \*arr et de l'infrastructure |
| `/api/metrics/prometheus` | Métriques Prometheus, Redis, worker et files |
| `/api/events` | Flux SSE authentifié pour le rafraîchissement temps réel |

Dans l'interface, consultez **Exploitation → Vue d'ensemble** avant les logs : les imports bloqués, conflits et actions recommandées y sont regroupés.

### États attendus

```text
plex-rss   healthy
worker     healthy
db         healthy
redis      healthy
```

Si le worker est indisponible, l'interface peut rester accessible mais le polling, les analyses et les notifications différées ne progresseront plus.

## Dépannage

### `plex-rss` reste "unhealthy", le worker ne démarre jamais

Le worker dépend de `plex-rss: { condition: service_healthy }` : tant que l'API n'est pas saine, il ne tente même pas de démarrer. Commencez toujours par les logs de l'API :

```bash
docker compose logs --tail=200 plex-rss
```

La cause la plus fréquente est une migration Alembic qui échoue au démarrage (les migrations s'appliquent avant que l'API n'écoute).

### La migration échoue avec `DuplicateTable` / "already exists" à chaque nouvelle tentative

Signe qu'une tentative de migration précédente a été interrompue (redémarrage concurrent, arrêt brutal) après avoir partiellement appliqué un changement de schéma, mais sans que `alembic_version` n'ait avancé — chaque redémarrage rejoue donc la même migration et échoue de la même façon puisque l'objet existe déjà.

1. Identifiez l'objet en doublon dans le message d'erreur (index, colonne, contrainte…).
2. Connectez-vous à PostgreSQL et vérifiez l'état réel :
   ```bash
   docker compose exec db psql -U plexrss -d plexrss -c "\d nom_de_la_table"
   docker compose exec db psql -U plexrss -d plexrss -c "SELECT version_num FROM alembic_version;"
   ```
3. Si l'objet listé dans l'erreur existe déjà mais que `alembic_version` n'a pas avancé jusqu'à la révision qui le crée, supprimez uniquement cet objet en doublon (`DROP INDEX ...`, jamais `DROP TABLE`) pour laisser la migration le recréer proprement au prochain démarrage.
4. Relancez `docker compose up -d plex-rss` : la boucle de retry du conteneur doit alors passer la migration et repasser "healthy".

Les migrations ajoutées depuis juillet 2026 utilisent `CREATE INDEX IF NOT EXISTS` / `DROP INDEX IF EXISTS` pour rester rejouables sans intervention manuelle ; ce scénario ne devrait plus se reproduire pour les futures migrations d'index.

### Le worker est "healthy" mais rien ne se traite

Vérifiez que `ENABLE_ARQ=1` est bien défini sur les deux services et que Redis répond (`docker compose exec redis redis-cli ping`). Un worker qui ne peut pas joindre Redis au démarrage peut rester marqué sain par son propre healthcheck tout en ne consommant aucune tâche.

## Sauvegarde et restauration

Créer et vérifier un dump :

```bash
docker compose --profile operations run --rm backup
```

Restaurer un dump nécessite d'arrêter les services qui écrivent :

```bash
docker compose stop plex-rss worker
RESTORE_FILE=plexarr-YYYYMMDDTHHMMSSZ.dump CONFIRM_RESTORE=YES \
  docker compose --profile operations run --rm restore
docker compose up -d plex-rss worker
```

Testez régulièrement une restauration. Un fichier de sauvegarde qui n'a jamais été restauré ne constitue pas une sauvegarde vérifiée.

## Mise à jour

### Image publiée

```bash
docker compose --profile operations run --rm backup
docker compose pull
docker compose up -d
docker compose ps
```

### Construction locale

```bash
git pull --ff-only
docker compose --profile operations run --rm backup
docker compose up -d --build
```

Les migrations Alembic sont appliquées au démarrage de l'API. Consultez les logs avant de considérer la mise à jour terminée.

### Migration d'une ancienne base SQLite

Le compose conserve `AUTO_MIGRATE_LEGACY_SQLITE=1` et `LEGACY_SQLITE_PATH=/app/data/plex_rss.db`. L'import n'a lieu que si PostgreSQL est vide. Conservez une copie du fichier SQLite avant le premier démarrage et consultez [la documentation de migration](docs/LEGACY_DATABASE_MIGRATION.md).

## Développement

### Backend

```bash
python -m venv .venv
# Linux/macOS : source .venv/bin/activate
# PowerShell   : .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
npm ci
npm run dev
npm run build
npm run test:e2e
```

### Tests et qualité

```bash
python -m pytest -q -p no:xonsh -p no:xonsh.pytest.plugin
python -m ruff check .
```

Les contributions sont décrites dans [CONTRIBUTING.md](CONTRIBUTING.md). Pour l'exploitation détaillée, consultez [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Sécurité

- Ne publiez jamais `.env`, les tokens Plex/\*arr ou les clés de notification.
- Placez Plexarr derrière HTTPS pour un accès distant.
- Limitez l'exposition directe de PostgreSQL et Redis : aucun port hôte n'est nécessaire.
- Sauvegardez `PLEXARR_ENCRYPTION_KEY` séparément des dumps PostgreSQL.
- Consultez les alertes Dependabot, CodeQL et Trivy avant une mise à jour majeure.
- Conformité RGPD : un modèle de registre des traitements est fourni dans [docs/RGPD_REGISTRE.md](docs/RGPD_REGISTRE.md). Renseignez le contact du responsable de traitement dans **Réglages → RGPD** (il alimente la page publique `/privacy`).

## Licence

[MIT](LICENSE) — Copyright © 2026 Rémi DEHER.
