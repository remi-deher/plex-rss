## [2.0.0] - 2026-06-15

### Ajouté
- Intégration Seer (Overseerr/Jellyseerr) : sync utilisateurs et demandes
- Utilisateurs Seer-only avec ID synthétique `seer:{id}`, liaison manuelle/auto (email, plexUsername)
- Déduplication tvdb/tmdb : fallback tvdb_id pour réconcilier RSS (TVDB) et Seer (TMDB)
- Conservation de la date la plus ancienne lors de la sync Seer
- Tab Conflits : détection tmdb_conflicts, orphelines, pending >30j, résolution manuelle/auto, ignore persistant
- Page Maintenance : 8 actions avec logs temps réel et historique du dernier run
- Action "Enrichir & Fusionner" : résolution tmdb via Seer Search + merge des doublons
- Lien direct vers Seer depuis la page des demandes
- 272 tests unitaires

### Corrigé
- Dates affichant la date du jour au lieu de la vraie date Seer
- Doublons RSS/Seer sur séries avec titres traduits
- Conflit tmdb_id entre Plex RSS et Seer pour la même série (tvdb identique)

## [1.0.0] - 2026-06-14

### Ajouté
- Configuration initiale de l'application FastAPI
- Authentification sécurisée et assistant de configuration (wizard)
- Synchronisation avec les utilisateurs Plex et listes d'attente
- Intégration de Sonarr et Radarr avec import/export des données historiques
