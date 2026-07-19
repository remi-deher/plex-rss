# Plan complet d'optimisation (Vitesse et Stack Technique)

L'application souffre actuellement de plusieurs goulots d'étranglement structurels liés à sa stack technique d'origine. Même avec des optimisations ponctuelles (threadpool, cache asynchrone), la base actuelle touchera rapidement ses limites.

Voici un plan complet et progressif pour métamorphoser la vitesse et la fluidité de l'application.

## 1. Changement du moteur de base de données (SQLite -> PostgreSQL)
**Problème actuel :** L'application utilise SQLite avec le mode WAL désactivé (`journal_mode=DELETE` dans `app/database.py`). C'est **extrêmement lent** pour la concurrence, car chaque écriture bloque totalement la base pour toutes les autres requêtes (lectures comprises). 
**Solution proposée :** 
- Basculer sur **PostgreSQL**. `psycopg2` est déjà dans vos dépendances (`requirements.txt`), la transition serait donc très naturelle.
- PostgreSQL gère parfaitement la concurrence, ce qui supprimera tous les ralentissements liés aux accès simultanés de l'interface et des tâches en arrière-plan.

## 2. Passage à SQLAlchemy Async (`asyncpg` / `ext.asyncio`)
**Problème actuel :** FastAPI est un framework asynchrone ultra-rapide, mais SQLAlchemy est utilisé de manière **synchrone**. Cela force l'utilisation massive de `run_in_threadpool` ou provoque le gel de l'Event Loop (comme vu précédemment).
**Solution proposée :**
- Utiliser l'extension asynchrone de SQLAlchemy avec le driver `asyncpg` (PostgreSQL) ou `aiosqlite` (SQLite si on le garde).
- Cela permet d'utiliser `await db.execute(...)`. Les requêtes DB ne bloqueront plus *jamais* le serveur, permettant à FastAPI de traiter des milliers de requêtes par seconde sans sourciller.

## 3. Migration du Frontend vers une SPA (Vue.js / React / Svelte)
**Problème actuel :** Le frontend utilise des templates Jinja (SSR). À chaque fois que l'utilisateur clique sur un onglet dans le menu, le backend doit requêter la base, générer tout le code HTML, et le renvoyer. Le navigateur doit tout redessiner.
**Solution proposée :**
- Transformer l'interface en **Single Page Application (SPA)**, par exemple avec Vue.js ou React. 
- L'interface ne se chargera qu'une seule fois. La navigation sera **instantanée**.
- Le backend deviendra une pure API REST (FastAPI) qui ne renverra que du JSON léger au lieu de générer de l'HTML lourd.

## 4. Ajout d'une couche de Cache distribué (Redis)
**Problème actuel :** Le cache pour TMDB ou la santé des services est stocké dans des variables en mémoire (`_health_cache` etc.). Cela disparaît à chaque redémarrage et n'est pas optimisé pour un gros volume.
**Solution proposée :**
- Intégrer **Redis**.
- Les réponses de TMDB, les requêtes fréquentes à Sonarr/Radarr, et les statuts systèmes seront stockés dans Redis (qui est en RAM et extrêmement rapide). Cela réduira massivement les appels réseau externes.

## 5. Découplage des tâches de fond (Celery ou ARQ)
**Problème actuel :** Les tâches lourdes (synchronisation Plex, vérification des statuts *arr) tournent dans le même processus que l'API via `APScheduler`. Cela consomme la RAM et le CPU du serveur web.
**Solution proposée :**
- Extraire les tâches planifiées dans des "Workers" séparés via **Celery** (ou **ARQ** pour du tout asynchrone avec Redis).
- Le serveur web (FastAPI) sera 100% dédié à répondre instantanément à l'utilisateur, tandis que le Worker fera le travail lourd en arrière-plan.

## 6. Temps réel (WebSockets ou Server-Sent Events)
**Problème actuel :** L'interface Javascript fait du "polling" (elle requête le serveur toutes les X secondes via `setInterval` pour voir si un statut a changé).
**Solution proposée :**
- Implémenter des **WebSockets** ou du **SSE** (Server-Sent Events) nativement via FastAPI.
- Dès qu'un film est "Disponible" (via le webhook Radarr), le backend "pousse" instantanément l'information à l'interface de l'utilisateur sans qu'il n'ait besoin de recharger.

---

> [!IMPORTANT]
> **Décision requise**
> Ces changements sont lourds mais définitifs pour avoir une application "Enterprise-grade" (comme Jellyseerr).
> 
> Souhaitez-vous que l'on commence par l'une de ces étapes ? (Je vous conseille de commencer par le **Point 2 : Passage en SQLAlchemy Async** ou le **Point 1 : Bascule vers PostgreSQL** qui auront un impact immédiat sur le backend sans tout casser).
