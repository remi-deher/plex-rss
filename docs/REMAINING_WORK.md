# Plex-RSS - Travail restant

## Objectif du document

Cette feuille de route décrit l'état réel du projet après la migration SQLAlchemy async
et la migration de la suite de tests. Elle doit être suivie dans l'ordre proposé afin de
limiter les régressions et de garder un point de retour fonctionnel entre les chantiers.

État vérifié le 13 juillet 2026 :

- backend FastAPI et accès SQLAlchemy migrés en asynchrone ;
- SQLite via `aiosqlite` et PostgreSQL via `asyncpg` supportés ;
- suite applicative verte : **612 tests réussis** dans la dernière exécution locale ;
- Redis optionnel disponible via `app/cache.py` ;
- PostgreSQL et Redis déclarés dans `docker-compose.yml` ;
- SPA Vue servie à la racine avec mises à jour SSE ;
- tâches planifiées extraites dans un worker ARQ séparé ;
- APScheduler désactivé par défaut et conservé uniquement pour le retour arrière explicite.

## Avancement des priorités 1 à 3

- **Priorité 1 livrée** : migrations Alembic compatibles PostgreSQL, importeur SQLite vers
  PostgreSQL et procédure de retour arrière. Validation réelle effectuée sur 5 135 lignes.
- **Priorité 2 livrée** : l'interface authentifiée Vue est servie à la racine et couvre
  dashboard, découverte, demandes, bibliothèque, calendrier, téléchargements, utilisateurs,
  notifications, maintenance, paramètres, migration des données et sécurité du profil.
  `/app/...` redirige vers la route racine équivalente ; Jinja reste limité au login/setup.
- **Priorité 3 livrée** : recherche de releases Vue, tri VF/MULTI avant les résultats anglais,
  grab protégé contre les doubles clics et ouverture du suivi dans un nouvel onglet.

## Avancement des priorités 5 à 7

- **Priorité 5 livrée** : worker ARQ, verrous Redis, états persistés, cron jobs, notifications
  et maintenance mis en file, healthcheck Compose et drapeau de retour arrière APScheduler.
- **Priorité 6 livrée** : SSE authentifié, Redis Streams/PubSub, reprise `Last-Event-ID`, heartbeat,
  filtrage par permissions et rafraîchissement ciblé des vues Vue avec polling lent de secours.
- **Priorité 7 livrée** : CI Python/Vue/PostgreSQL/Redis, dépendances de développement, métriques
  Redis/worker/jobs, secrets documentés et sauvegarde/restauration PostgreSQL testée.

## Priorité 0 - Sécuriser le point de départ

### À faire

1. Relire le diff complet de la migration async.
2. Créer un commit dédié contenant le backend async, les tests migrés et les documents de passation.
3. Construire puis démarrer l'image Docker avec PostgreSQL et Redis.
4. Exécuter un test fonctionnel minimal contre cette stack.

### Validation

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -p pytest_asyncio.plugin -q
python -m compileall -q app scripts tests
docker compose build
docker compose up -d
docker compose ps
```

Le démarrage est accepté si FastAPI, PostgreSQL et Redis sont sains, si les migrations
Alembic s'appliquent sur une base vide et si `/api/health` répond.

## Priorité 1 - Finaliser le passage réel à PostgreSQL

Le code et Compose savent utiliser PostgreSQL, mais il reste à valider le parcours de
migration d'une installation existante utilisant SQLite.

### À faire

1. Définir une procédure sauvegardée SQLite vers PostgreSQL.
2. Fournir un script d'import ou documenter un outil fiable pour transférer toutes les tables.
3. Vérifier les séquences PostgreSQL après import des identifiants existants.
4. Comparer les nombres de lignes et les relations importantes avant et après migration.
5. Tester les migrations Alembic sur une base PostgreSQL vide et sur une base importée.
6. Documenter le retour arrière vers la sauvegarde SQLite.
7. Retirer les identifiants PostgreSQL en clair de la configuration d'exemple ou les déplacer
   dans un fichier `.env` non versionné.

### Critères de fin

- aucune perte de demandes, utilisateurs, réglages, historiques ou notifications ;
- redémarrage idempotent ;
- les 624 tests restent verts ;
- un test d'intégration PostgreSQL est exécuté en CI ou dans Compose.

## Priorité 2 - Consolider la SPA Vue

La SPA existe sous `frontend/` et est servie directement sous `/`. Le routeur de pages Jinja
n'est plus monté dans l'application authentifiée. Les écrans publics de login et de premier
démarrage restent rendus côté serveur.

### Vues à migrer

1. Bibliothèque et détail média.
2. Demandes, calendrier et prochaines sorties.
3. Recherche de releases, résultats et actions de grab.
4. Utilisateurs et workflow d'approbation.
5. Notifications, modèles d'email et journaux.
6. Paramètres, connexions, VFF, conflits et maintenance.
7. Sécurité du compte, authentification et passkeys.

### Socle frontend à compléter

1. Ajouter une gestion uniforme des erreurs, notifications et états vides.
2. Ajouter l'annulation des recherches précédentes avec `AbortController`.
3. Centraliser l'état de session et les permissions admin/utilisateur.
4. Ajouter les routes protégées et une page 404 dans Vue Router.
5. Écrire des tests de composants et des tests de parcours navigateur.
6. Vérifier les vues desktop et mobile avec des captures Playwright.
7. Supprimer les templates et scripts Jinja métier devenus inactifs après une période de validation.

### Critères de fin

- aucune navigation métier ne recharge une page complète ;
- toutes les actions Jinja importantes existent dans Vue ;
- les permissions restent identiques côté API et interface ;
- le build `npm run build` est produit dans l'image Docker ;
- les anciens templates ne sont retirés qu'après validation de parité.

## Priorité 3 - Finaliser Auto-Grab et le classement des résultats

Le comportement est déjà présent dans `app/static/js/library.js` pour l'interface Jinja :
les résultats non français sont placés en bas et certaines actions ouvrent un nouvel onglet.
Il reste à uniformiser ce contrat et à le porter dans Vue.

### À faire

1. Définir un champ API stable tel que `is_french` et un ordre déterministe côté backend.
2. Afficher systématiquement les résultats VF/MULTI avant les résultats anglais ou non VF.
3. Conserver une séparation visuelle explicite entre les deux groupes.
4. Pour un lien torrent direct, ouvrir immédiatement un nouvel onglet depuis le clic utilisateur,
   puis déclencher l'envoi au client de téléchargement sans remplacer la page courante.
5. Pour un grab Sonarr/Radarr, attendre la confirmation API puis ouvrir `/downloads`
   dans un nouvel onglet.
6. Désactiver le bouton pendant l'opération et afficher le succès ou l'erreur.
7. Ajouter des tests API sur le tri et des tests navigateur sur le nouvel onglet.

### Critères de fin

- aucun grab ne détourne l'onglet courant ;
- un double clic ne crée pas deux téléchargements ;
- les résultats anglais restent toujours après les résultats VF/MULTI ;
- le comportement est identique dans Vue et dans l'interface Jinja tant qu'elle existe.

## Priorité 4 - Cache de santé stale-while-revalidate

Le composant Vue conserve déjà les anciennes données dans `localStorage`, mais le backend
utilise un cache TTL simple. Après expiration, un appel attend encore tous les contrôles réseau.

### À faire

1. Stocker séparément la dernière valeur connue, sa date et l'état du rafraîchissement.
2. Retourner immédiatement la dernière valeur même si elle est expirée.
3. Déclencher un seul rafraîchissement en arrière-plan par clé.
4. Remplacer atomiquement la valeur après succès.
5. Conserver l'ancienne valeur et exposer l'erreur de rafraîchissement en cas d'échec.
6. Ajouter `stale`, `refreshing` et éventuellement `refresh_error` au payload.
7. Empêcher plusieurs processus de lancer le même contrôle via un verrou Redis court.
8. Tester le cache mémoire, Redis indisponible, l'expiration et les appels concurrents.

### Critères de fin

- `/api/health` répond rapidement même pendant les contrôles externes ;
- les cartes ne disparaissent jamais pendant un rafraîchissement ;
- un échec Sonarr, Radarr, Plex ou Redis ne vide pas les dernières données connues.

## Priorité 5 - Extraire les tâches de fond vers ARQ

**État : livré et validé sur la stack Docker.**

ARQ est recommandé pour rester cohérent avec le code async et réutiliser Redis. Celery ne
devrait être choisi que si un besoin opérationnel précis justifie sa complexité supplémentaire.

### À faire

1. Ajouter ARQ et une configuration de worker dédiée.
2. Créer des fonctions de job fines qui ouvrent chacune leur propre `AsyncSession`.
3. Déplacer progressivement les jobs APScheduler :
   - polling des watchlists ;
   - suivi Sonarr/Radarr et torrents ;
   - synchronisation Plex et Seer ;
   - scans VFF ;
   - purge des notifications et digest.
4. Ajouter les tâches périodiques via les cron jobs ARQ.
5. Stocker l'identifiant, le statut, la progression et la dernière erreur des jobs.
6. Rendre les jobs idempotents et empêcher deux exécutions concurrentes du même job.
7. Ajouter le service `worker` dans Compose avec une commande et un healthcheck dédiés.
8. Retirer `start_scheduler()` du lifespan FastAPI après migration de tous les jobs.
9. Conserver APScheduler seulement pendant la transition, derrière un drapeau explicite.

### Critères de fin

- FastAPI ne lance plus de tâche planifiée lourde ;
- l'arrêt ou le redémarrage de l'API n'interrompt pas le worker ;
- une panne Redis produit une erreur visible sans perdre silencieusement un job ;
- les actions manuelles de maintenance mettent en file le même job que la planification.

## Priorité 6 - Temps réel avec SSE

**État : livré et validé avec un flux authentifié réel.**

SSE est suffisant pour les mises à jour serveur vers navigateur et plus simple à exploiter
que WebSocket. WebSocket ne devient nécessaire que si le client doit envoyer un flux continu.

### À faire

1. Ajouter un flux SSE authentifié par utilisateur.
2. Publier les événements depuis les webhooks et les workers via Redis Pub/Sub.
3. Définir des événements versionnés : `request.updated`, `download.updated`, `health.updated`,
   `job.updated` et `notification.updated`.
4. Mettre à jour les stores Vue sans recharger les pages.
5. Prévoir reconnexion, heartbeat, reprise après coupure et filtrage par permissions.
6. Garder un rafraîchissement périodique lent comme solution de secours.

### Critères de fin

- une disponibilité Plex ou Radarr apparaît sans rechargement ;
- la progression d'un job ou téléchargement est actualisée en direct ;
- aucune donnée d'un autre utilisateur n'est envoyée par le flux.

## Priorité 7 - Industrialisation

**État : livré. Une restauration réelle a été validée dans une base PostgreSQL temporaire.**

1. Ajouter une CI couvrant Python, Vue et PostgreSQL.
2. Ajouter lint et formatage sans réécrire massivement les fichiers existants.
3. Traiter l'avertissement de dépréciation `TestClient`/`httpx` de Starlette.
4. Ajouter des sauvegardes PostgreSQL et une politique de restauration testée.
5. Ajouter des métriques Redis, worker, files d'attente et durée des jobs.
6. Remplacer les secrets d'exemple par des variables d'environnement documentées.
7. Tester les mises à jour Docker depuis une version existante.

## Ordre d'exécution recommandé

```text
Commit async
  -> validation PostgreSQL/Redis
  -> parité SPA Vue
  -> Auto-Grab Vue
  -> santé stale-while-revalidate
  -> workers ARQ
  -> SSE
  -> CI, sauvegardes et observabilité
```

Chaque priorité doit se terminer par un commit autonome, la suite Python complète, le build
Vue et, dès que disponible, le test d'intégration PostgreSQL. Ne pas lancer simultanément la
suppression des templates Jinja et l'extraction des workers : ces deux changements ont des
surfaces de régression très différentes et doivent rester isolés.
