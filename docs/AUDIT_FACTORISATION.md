# Audit de factorisation — Plexarr (27 juillet 2026)

Inspection complète de `app/` (30 800 lignes Python) et `frontend/src/` (13 100 lignes
Vue/JS + 86 Ko CSS). Chaque point est **constaté**, avec fichier/ligne, pas supposé.

> Remplace `docs/REFACTORING_TASKS.md`, devenu obsolète (il décrivait `api.py` à
> 3708 lignes et `settings.html` à 3353 lignes, tous deux disparus depuis) et supprimé.
>
> **Avancement** — chantiers 1 à 14 du tableau de priorisation faits, plus le nettoyage
> des fichiers morts. Les extractions sont vérifiées par les suites backend/frontend,
> le build Vite et, pour les découpages de routeurs, par la parité des 273 routes
> (`scripts/dump_routes.py`).

---

## Partie A — Frontend

### A1. Primitives déjà écrites mais sous-adoptées — ✅ fait

| Primitive | Utilisations avant | Réimplémentations à la main |
|---|---|---|
| `components/DrawerShell.vue` (backdrop + panel + a11y) | **2** | **5** (`ConfirmModal`, `ManualImportModal`, `ArrInstancesCard`, `DownloadClientsCard`, `EmailProvidersCard`) |
| `components/ui/PageHeader.vue` | 14 vues / 16 | — |
| `components/ui/StatusBadge.vue` | **5** | **74** `class="badge"` dans **29 fichiers** |

`ui/ModalShell.vue` (frère de `DrawerShell`, variante centrée) est créé et les 5 modales
sont migrées : ~15 lignes de markup + un branchement `useModalA11y` en double chacune.
`drawer-backdrop` n'est plus écrit que dans les deux coquilles, et `useModalA11y` n'est
plus appelé que par elles, `FilterBar` et le menu mobile de `App.vue`.

> **Correction de l'audit initial.** Remplacer les 74 `class="badge"` par `<StatusBadge>`
> n'est **pas** une factorisation : `.badge` est un chip rectangulaire (rayon 5 px, sans
> point), `.ui-status` une pilule à point de 26 px de haut. La substitution changerait
> l'apparence de 29 fichiers — c'est un choix de design, à trancher séparément.
>
> Ce qui *était* de la duplication, et qui est fait : les **tables de libellés**. Le même
> statut `failed` s'affichait « Echec » dans la liste Bibliothèque, « Échec » dans
> Découvrir et « Erreur » dans l'onglet Demandes. `utils/labels.js` porte désormais
> `requestStatusLabel`, `mediaTypeLabel`/`mediaTypePluralLabel` (7 ternaires
> `media_type === 'show' ? …` recopiés) et `playbackMethodLabel` (dupliqué entre
> `PlaybackMethodBadge` et `ActivityView`). `StatusBadge` y puise ses libellés de statut et
> ne garde que sa table de tons.

### A2. Composants communs manquants

| À créer | Remplace | Sites |
|---|---|---|
| `ui/MetricCard.vue` + `ui/MetricGrid.vue` | `<article class="metric-card"><span/><strong/><small/></article>` | [LibraryView.vue:12](frontend/src/views/LibraryView.vue:12), [DownloadsView.vue:7](frontend/src/views/DownloadsView.vue:7), [DashboardView.vue:18](frontend/src/views/DashboardView.vue:18), `LibraryAnalyticsView`, `UserEditorDrawer`, + `activity/ActivityMetricCard.vue` (déjà un doublon spécialisé) |
| `ui/PanelCard.vue` (`<section class="panel">` + `panel-head` + eyebrow/titre/action + état vide) | markup répété | **33 fichiers** contiennent `panel-head` |
| `ui/DataTable.vue` (`table-wrap table-cards rich` + `data-label` + tri) | tableau responsive recopié | 10 fichiers (`NotificationsTable`, `UsersTable`, `ArrInstancesCard`, `DownloadClientsCard`, `EmailProvidersCard`, `DownloadsView`, `IssuesView`, `LogsView`…) |
| `ui/TabNav.vue` | `<nav class="detail-tabs"><button :class="{active:…}">` | `DownloadsView`, `NotificationsView`, `MediaDetailView`, `LogsView`, `UserEditorDrawer` |
| `ui/Pagination.vue` / `ui/LoadMore.vue` | offset/limit + « Charger plus » | [NotificationsView.vue:56](frontend/src/views/NotificationsView.vue:56), [DownloadsView.vue:58](frontend/src/views/DownloadsView.vue:58), [DiscoverView.vue:116](frontend/src/views/DiscoverView.vue:116), [LibraryView.vue:66](frontend/src/views/LibraryView.vue:66) |
| `ui/ToggleSwitch.vue` | switch accessible fait main, **35 lignes de CSS** | [NotificationsView.vue:13](frontend/src/views/NotificationsView.vue:13) (unique aujourd'hui, mais tous les `input type=checkbox` de Settings devraient y passer) |
| `ui/CrudResourceCard.vue` | voir A4 (`useCrudResource`) | `ArrInstancesCard`, `DownloadClientsCard`, `EmailProvidersCard` |
| carte média unique | `poster-shell` + badges + titre | [LibraryCard.vue](frontend/src/components/library/LibraryCard.vue) vs [DiscoverView.vue:80-112](frontend/src/views/DiscoverView.vue:80) (inline) vs `media/MediaPoster.vue` — **3 implémentations** de la même carte affiche |

### A3. Utilitaires dupliqués → `frontend/src/utils/format.js` — ✅ fait

Aucun module de formatage n'existe ; chaque composant réécrit le sien.

| Helper | Occurrences | Pire cas |
|---|---|---|
| `formatDate` / `formatDateTime` (`Intl.DateTimeFormat('fr-FR', …)`) | **22 définitions** dans 21 fichiers, avec **4 valeurs de repli différentes** (`'-'`, `'—'`, `'Aucune'`, `'Non renseignée'`) | incohérence visible à l'écran |
| `formatDuration(ms)` | **4** ([ActivityView.vue:206](frontend/src/views/ActivityView.vue:206), `HistoryTable`, `SessionDetailDrawer`, `PopularMediaPanel`, `ScheduledTasksTab`) — et **3 formats de sortie différents** | `35 min` vs `0.6 h` |
| `formatBandwidth` | 2 (identiques : `ActivityView`, `SessionDetailDrawer`) | |
| `shortDate` / `formatLongDate` | 4 (`ConcurrencyPanel`, `DailyActivityChart`, `ActivityChartPanel`, `CalendarView`) | |
| `formatBytes` | 1 (`DiskSpacePanel`) mais absent là où il faudrait | |
| `signedPercent`, `formatValue` (`toLocaleString('fr-FR')`) | 3 | |
| `proxyUrl` | 2 — copie exacte, désormais dans `utils/mediaImage.js` | |
| relative time (« il y a N s ») | 2 ([ActivityView.vue:178](frontend/src/views/ActivityView.vue:178), [DashboardView.vue:142](frontend/src/views/DashboardView.vue:142)) | |

`utils/format.js` porte les 21 formateurs, chacun en un seul exemplaire, et
`format.spec.js` fige leurs sorties. `mediaListHelpers.js` n'est plus qu'un jeu de
ré-exports vers `utils/labels.js` et `utils/mediaImage.js`.

Deux variantes subsistent volontairement, parce que ce sont des différences d'affichage
réelles et non des doublons : `formatDuration` (« 2 h ») vs `formatDurationExact`
(« 2 h 0 min », pour aligner les colonnes du tableau d'historique), et `formatBytes`
(échelle Go/To de l'espace disque *arr) vs `formatFileSize` (o → To de l'inventaire de
fichiers).

### A4. Composables manquants — ✅ fait (1-4), reste `useConfirmedAction`

`composables/` ne contient que `useConfirm` et `useModalA11y`. Cinq patterns transverses
sont recopiés à la main dans chaque vue :

1. **`useAsyncResource` / requête annulable + anti-course.** Le triplet
   `activeController?.abort()` + `AbortController` + `loadSequence`/`requestSequence` est
   réécrit ligne pour ligne dans [LibraryView.vue:258-317](frontend/src/views/LibraryView.vue:258),
   [DownloadsView.vue:109-120](frontend/src/views/DownloadsView.vue:109) et
   [DiscoverView.vue:240-276](frontend/src/views/DiscoverView.vue:240), avec chaque fois la
   même gestion `e.name !== 'AbortError'`. ~35 lignes × 3.
2. **`usePolling(fn, ms)`.** `setInterval(() => { if (!document.hidden) load() }, N)` +
   `clearInterval` en `onUnmounted` : 6 sites (`ActivityView` ×2, `DashboardView` ×3,
   `DownloadsView`, `LibraryView`). `LibraryView` oublie le garde `document.hidden` —
   incohérence que le composable règle d'office.
3. **`useSession()` / `useIsAdmin()`.** `api('/api/session')` puis
   `Boolean(session?.is_owner || session?.role === 'admin')` est refait dans
   [App.vue:129](frontend/src/App.vue:129), [LibraryView.vue:409](frontend/src/views/LibraryView.vue:409),
   [MediaDetailView.vue:231](frontend/src/views/MediaDetailView.vue:231) — **3 requêtes réseau**
   pour la même donnée, plus `ProfileView`. Un composable + cache module = 1 requête.
4. **`useDebouncedSearch`.** `clearTimeout/setTimeout` 250-300 ms : `LibraryView` (250),
   `DiscoverView` (300), `NotificationsView` (300), `EmailTemplatesPanel` (500).
5. **`useCrudResource(basePath)`** — voir A5/`ArrInstancesCard`.
6. **`useConfirmedAction`** — *reporté*, à faire avec le découpage de `MediaDetailView`
   et `LibraryView` (A5) : l'état qui l'entoure (`busy`, `error`, `load`) part dans les
   composables extraits, faire les deux séparément produirait deux fois le même diff. Le bloc
   `if (!await askConfirm({…})) return; busy=true; try { await api(…); await load() } catch { error=… } finally { busy=false }`
   apparaît **6 fois** dans `NotificationsView`, **5 fois** dans `MediaDetailView`,
   **4 fois** dans `LibraryView`. ~10 lignes × 15.
7. **`useFeedback`.** Trois systèmes de retour utilisateur coexistent : `toasts` +
   `toastTimers` ([App.vue:140](frontend/src/App.vue:140)), `feedback` + `feedbackTimeout`
   ([NotificationsView.vue:129](frontend/src/views/NotificationsView.vue:129)),
   `successMessage`/`error` refs (partout ailleurs), plus `success()/fail()` de
   `settingsForm.js`. À unifier sur le `ToastStack` existant.

### A5. God components à éclater

#### `views/MediaDetailView.vue` — 533 lignes, orchestrateur monolithique
Le template est propre (7 sous-composants), c'est le `<script setup>` qui a tout absorbé :
**19 fonctions async**, 24 `ref`/`reactive`, 4 sources de données à fusionner.

À extraire :
- `composables/useMediaDetail.js` — `load()`, `mediaPath()`, `sourcePath()`/`sourceId()`
  ([lignes 210-268, 405-406](frontend/src/views/MediaDetailView.vue:210)).
- `composables/useSeasonEpisodes.js` — `loadEpisodesEnvelope`, `loadAvailability`,
  `loadVfStatus`, `loadSeasonEpisodes`, `loadVf` + le `mergedVfDetail` de **42 lignes**
  ([165-206](frontend/src/views/MediaDetailView.vue:165), [410-458](frontend/src/views/MediaDetailView.vue:410)).
  C'est la logique la plus dense de tout le frontend et elle est aujourd'hui non testable.
- `composables/useRequestActions.js` — les 11 mutations de demande (`requestAction`,
  `rejectRequest`, `closeRequest`, `resendMail`, `notifyUser`, `addRequester`,
  `catchUpAll`, `promoteRequester`, `removeRequester`, `deleteRequest`, `submitRequest`),
  [285-399](frontend/src/views/MediaDetailView.vue:285). Elles sont **rebranchées une par une**
  en 13 `@events` vers `MediaRequestsTab` — le composable les colocalise avec le composant
  qui les déclenche et supprime le prop-drilling.

#### `components/media/MediaRequestsTab.vue` — 360 lignes, **13 emits**
Un seul composant porte : ajout de co-demandeur, carte de demande, stepper de statut,
détail par saison, historique de mails, liste des co-demandeurs + menu contextuel, barre
de 9 actions. À découper en `RequestCard.vue` / `RequestStatusStepper.vue` /
`RequestMailHistory.vue` / `RequesterList.vue` / `RequestActionBar.vue`. Le nombre d'emits
tombe de 13 à 3-4 par composant.

#### `views/DashboardView.vue` — 259 lignes
[Lignes 184-206](frontend/src/views/DashboardView.vue:184) : **12 appels API** dans un
`Promise.allSettled`, dont les résultats sont réinjectés via **trois tableaux parallèles
indexés à la main** (`results`, `refs`, `failedLabels`) — plus un cas spécial
`results[10]` codé en dur. Ajouter/retirer un endpoint casse silencieusement
l'alignement. À remplacer par une liste déclarative
`[{ path, target, label, transform }]` et une boucle unique, extraite en
`composables/useDashboardData.js`.

#### `views/LibraryView.vue` — 453 lignes
Le composant fait à la fois : agrégation de 4 sources (library / requests / orphans /
metrics), 7 filtres, métriques calculées, sélection multiple + actions groupées,
pagination par `IntersectionObserver`, polling. À extraire :
`composables/useLibraryFeed.js` (agrégation + pagination, lignes 107-333),
`composables/useMediaFilters.js` (les prédicats de [185-193](frontend/src/views/LibraryView.vue:185)
et `matchesStatusFilter`), `composables/useBulkSelection.js`.
Le commentaire métier de `matchesStatusFilter` est précieux — il doit suivre le code
extrait, pas rester dans la vue.

#### `views/DownloadsView.vue` — 133 lignes mais très dense (code compacté)
14 fonctions de classification/format (`rowKey`, `statusKey`, `statusLabel`, `canAct`,
`isImportPending`, `isUnmatched`, `needsEpisodeImport`, `requiresIntervention`,
`queueDetailPath`…) mélangées à la vue. Ce sont des **fonctions pures sur la file *arr** :
les sortir dans `frontend/src/downloads/queueRules.js`, seul moyen de les tester (aucun
test aujourd'hui) — et `DashboardView` réimplémente déjà les siennes
([lignes 129-132](frontend/src/views/DashboardView.vue:129) : `queueState`,
`downloadingCount`, `importingCount`, `blockedCount`) avec des règles **divergentes** de
celles de `DownloadsView`. Deux définitions de « bloqué » dans l'app.
Extraire aussi le bloc `<article class="download-card">` en `downloads/DownloadCard.vue`.

#### `App.vue` — 168 lignes dont une navigation triplée
Le même arbre de menu est écrit **trois fois** : sidebar desktop
([lignes 13-61](frontend/src/App.vue:13)), overlay mobile ([85-105](frontend/src/App.vue:85)),
et une 3ᵉ fois côté `SettingsView` pour la liste d'onglets. Les libellés/routes divergeront.
→ un `frontend/src/navigation.js` exporté (`[{ label, to, icon, admin, children }]`) +
`components/nav/NavSection.vue` rendu par les deux surfaces.
Extraire aussi la logique de toasts de lecture (`showPlaybackToasts`, `seenPlaybackEvents`,
`toastTimers`, [140-157](frontend/src/App.vue:140)) en `composables/usePlaybackToasts.js`.

#### `views/DiscoverView.vue` — 305 lignes
Bloc `discover-command` (recherche + sections + filtres, [5-63](frontend/src/views/DiscoverView.vue:5))
à extraire en `discover/DiscoverCommandBar.vue` ; carte affiche à fusionner avec
`LibraryCard` (A2) ; `endpoint()` ([229-238](frontend/src/views/DiscoverView.vue:229)) à
déplacer dans un module `discover/api.js`.

### A6. CSS — 86 Ko globaux, propriété diffuse

- `assets/css/views.css` : **48 Ko / 2262 lignes**, un seul fichier pour toutes les pages.
- **15 sélecteurs sont définis dans plusieurs fichiers globaux** à la fois :
  `.actions`, `.checklist`, `.code-editor`, `.detail-drawer`, `.detail-row`,
  `.language-tag`, `.media-card`, `.metric-card`, `.page`, `.segmented`,
  `.slide-up-enter-from`, `.slide-up-leave-to`, `.template-settings`, `.toolbar`,
  `.unmatched-header`. Le rendu dépend donc de l'ordre d'import — fragile.
- Dans `views.css` seul : `.media-card` apparaît **13 fois**, `.poster-shell` 11,
  `.activity-chart` 9, `.settings-card` 8, `.detail-row` 8, `.dashboard-metrics` 8.
- Deux blocs portent le **même commentaire** `/* --- Dashboard Specific Styles --- */`
  (lignes 1631 et 1683).
- `views.css` style des composants qui ont leur propre SFC :
  `.settings-card` → `SettingsCard.vue`, `.health-card` → `HealthGrid.vue`,
  `.calendar-event` → `CalendarView.vue`, etc.

**Action** : ne garder en global que tokens (`base.css`) et primitives réellement
partagées (`components.css` : `.panel`, `.badge`, `.btn`, `table-wrap`, `.media-grid`).
Tout le reste redescend dans le `<style scoped>` du composant propriétaire — ce que font
déjà correctement `ActivityView`, `DownloadsView`, `DiscoverView`, `NotificationsView`.
Supprimer les redéfinitions inter-fichiers en premier (risque de régression visuelle réel :
faire un fichier à la fois, capture avant/après).

### A7. Divers frontend

- **`settingsForm.js` duplique le schéma backend.** [Lignes 15-40](frontend/src/settingsForm.js:15) :
  ~110 clés recopiées à la main depuis le modèle `Settings`. Toute colonne ajoutée côté
  Python est silencieusement ignorée par l'UI (`for (const key of Object.keys(form))`).
  → exposer un `/api/settings/schema` (dérivé de `Settings.__table__.columns`) et
  construire `form` dynamiquement, ou au minimum un test qui compare les deux listes.
- **Registre d'onglets Settings triplé** : `tabs` ([SettingsView.vue:55](frontend/src/views/SettingsView.vue:55)),
  la chaîne de `v-else-if` ([17-28](frontend/src/views/SettingsView.vue:17)), et
  `settingsSections` ([App.vue:135](frontend/src/App.vue:135)). → un seul tableau
  `{ key, label, icon, component, savable }` + `<component :is>`. Le `v-if` de la ligne 4
  (liste de 8 clés en dur) devient `currentTab.savable`.
- **Couverture de tests déséquilibrée** : 995 tests backend contre **27 tests frontend
  (7 fichiers `.spec.js`)**, dont aucun sur les vues lourdes. Les extractions ci-dessus (composables +
  modules purs `queueRules.js`, `format.js`) sont précisément ce qui rend cette logique
  testable — à faire dans le même mouvement.

---

## Partie B — Backend

### B1. `sonarr.py` / `radarr.py` — le plus gros doublon du projet — ✅ fait

985 + 750 lignes, avec **~20 fonctions de signature identique**. Vérifié par diff après
normalisation des noms de produit :
`sonarr.py:811-985` vs `radarr.py:576-760` (175 lignes) ne diffèrent que par **14 lignes**,
toutes des docstrings et un paramètre `includeSeries`.

Fonctions strictement mutualisables (mêmes chemins `/api/v3/*`, même corps) :
`get_notifications`, `find_webhook_notification`, `find_plex_notification`,
`test_notification`, `get_webhook_schema`, `build_webhook_payload`, `create_notification`,
`update_notification`, `get_quality_profiles`, `get_root_folders`, `get_tags`,
`get_disk_space`, `check_connection`, `_norm_title`.

Quasi-identiques (paramétrables par `entity = "series" | "movie"`) :
`get_queue`, `delete_queue_item`, `trigger_import`, `get_manual_import_candidates`,
`grab_release`, `get_releases`, `_normalize_release`, `get_calendar`, `movie_exists` /
`series_exists`, `delete_movie` / `delete_series`, `search_movie` / `search_series`,
`get_queue_movie_ids` / `get_queue_series_ids`.

**Action** : créer `app/services/arr_common.py` avec ces fonctions prenant
`(url, api_key, *, product: str)`. `sonarr.py`/`radarr.py` ne gardent que le **vraiment
spécifique** : `add_series` + `_disable_specials_by_default` + `_search_tvdb_id` +
`get_series_episode_stats` + `aggregate_monitored_episode_stats` +
`get_season_aired_episode_counts` d'un côté, `add_movie` + `resolve_tmdb_id` +
`_search_tmdb_id` de l'autre. Gain estimé : **~450 lignes**, et surtout un seul endroit
à corriger quand l'API *arr change.

### B2. `routers/webhook.py` — 1130 lignes, deux responsabilités

Le fichier mélange **ingestion** de webhooks et **administration** de webhooks.

À découper :
- `webhook_ingest.py` — `POST /sonarr`, `/radarr`, `/plex` + helpers de matching.
- `webhook_admin.py` — `GET /status`, `POST /check-live/{service}`,
  `POST /configure/{service}`, `GET /plex-connector-status/{service}`
  (`check_live_webhook` fait à lui seul **123 lignes**).

Puis, **dans** `webhook_ingest.py` :
- `sonarr_webhook` ([450-521](app/routers/webhook.py:450)) et `radarr_webhook`
  ([525-590](app/routers/webhook.py:525)) suivent la même séquence : ouvrir session →
  charger `Settings` → vérifier le secret → parser → brancher `Test` → brancher les
  événements de suppression → filtrer `Download`/`Import` → `trigger_plex_library_refresh`
  → extraire les identifiants → `_mark_available_and_notify`. Un handler générique
  paramétré par `(media_type, entity_key, id_fields, delete_events, file_key)` +
  deux tables de configuration élimine ~90 lignes et le risque de traiter un événement
  d'un côté seulement (déjà le cas : `MovieAdded` n'a pas d'équivalent Sonarr).
- `_mark_available_and_notify` fait **183 lignes** ([117-299](app/routers/webhook.py:117)) et
  `plex_webhook` **182** ([597-778](app/routers/webhook.py:597)) : à déplacer dans
  `services/` (respectivement `request_lifecycle.py`, qui existe déjà, et un
  `services/plex_webhook.py`). Un routeur ne devrait pas porter de logique métier de
  cette taille.

### B3. `routers/arr_api.py` — 1026 lignes, 6 domaines dans un fichier

Contient : CRUD instances *arr, CRUD clients de téléchargement, Prowlarr, recherche/grab
de releases, file *arr, import manuel, historique de téléchargements, profils/dossiers/tags.

À découper en `arr_instances_api.py`, `download_clients_api.py`, `prowlarr_api.py`,
`arr_queue_api.py`, `manual_import_api.py`, `downloads_api.py`.

Doublons internes à corriger au passage :
- **6 paires d'endpoints jumeaux** `sonarr_*` / `radarr_*` : `/{service}/profiles`,
  `/{service}/folders`, `/{service}/tags`, `/downloads/{service}-manual-import` (GET+POST).
  [Lignes 757-868 et 969-1029](app/routers/arr_api.py:757). Un seul endpoint
  `/{service}/profiles` avec `service: Literal["sonarr","radarr"]` remplace les 12.
- Les CRUD `arr-instances` et `download-clients` ([203-254](app/routers/arr_api.py:203) et
  [311-354](app/routers/arr_api.py:311)) sont le même code : list / create / update /
  toggle / delete + `_set_single_default`. Un helper générateur de routeur CRUD
  (`make_crud_router(model, schema, path)`) couvre aussi `email_providers_api.py`.

### B4. `models.py` — 1177 lignes, 30 modèles, 1 god-model — ✅ découpé (reste `Settings`)

- **Découper en package** `app/models/` : `settings.py`, `media.py` (`MediaRequest`,
  `LibraryItem`, `RequestSeasonStatus`, `VfEpisodeStatus`, `EpisodeAvailability`),
  `arr.py` (`ArrInstance`, `DownloadClient`, `*QueueObservation`,
  `SeriesAcquisitionBatch`), `notifications.py`, `playback.py`, `users.py`, `logs.py`.
  `__init__.py` réexporte tout : **zéro import à modifier ailleurs**, changement à risque nul.
- **`Settings` : 285 lignes, ~168 colonnes** dans une table singleton. Dont **73 colonnes
  liées aux emails** (templates, sujets, coquille, bandeaux par évènement).
  → extraire une table `EmailTemplate`/`EmailBranding` (une ligne par évènement au lieu
  de 3 × N colonnes). C'est le seul point de cet audit qui **exige une migration Alembic**
  et n'est donc pas behavior-preserving au sens strict : à traiter en dernier, seul,
  avec `docs/plan-modele-donnees.md`.
- `SonarrQueueObservation` / `RadarrQueueObservation`
  ([935-1010](app/models.py:935)) partagent 15 colonnes sur 20. Une base commune
  `QueueObservationMixin` (colonnes + `__table_args__` générés) suffit ; garder deux
  tables distinctes (les `season_number`/`episode_number`/`batch_id` sont légitimement
  Sonarr-only).

### B5. Helpers dupliqués à centraliser — ✅ fait (partiellement)

| Helper | Sites | Remède |
|---|---|---|
| `_delete_vf_episode_cache` | **4 copies identiques** : [webhook.py:87](app/routers/webhook.py:87), [requests_api.py:237](app/routers/requests_api.py:237), [misc_api.py:165](app/routers/misc_api.py:165), [arr_tracker.py:39](app/services/arr_tracker.py:39) | → `services/vff_scanner.py` ou un `services/vf_cache.py`. Le commentaire d'`arr_tracker.py` invoque un risque d'import circulaire — un module feuille dédié le lève. |
| `_link_request_to_library_item` | 2 : [plex_sync.py:107](app/services/plex_sync.py:107), [vff_scanner.py:49](app/services/vff_scanner.py:49) | → `services/media_matching.py` (qui existe et ne fait que 30 lignes) |
| `_norm_title` | 2 identiques (`sonarr.py`, `radarr.py`) + `_norm_title_for_dedup` (`watchlist_poller.py:433`) | → `services/media_matching.py` |
| résolution d'instance *arr | `_resolve_arr_instance` ([arr_api.py:104](app/routers/arr_api.py:104)) vs `_resolve_arr_connection` ([webhook.py:425](app/routers/webhook.py:425)) | une seule fonction, deux vues du résultat |
| `check_connection` | **6 définitions** (sonarr, radarr, prowlarr, seer, plex, tautulli) | signature commune + registre `{service: checker}` ; simplifie aussi `metrics_api.health_check` |

### B6. Fonctions god à découper

| Fonction | Lignes | Découpage |
|---|---|---|
| `_run_vf_scan` ([vff_scanner.py:664](app/services/vff_scanner.py:664)) | **284** | la plus grosse fonction du projet : sélection des cibles / scan Plex / persistance des statuts épisode / déclenchement des recherches / notifications. Au moins 4 fonctions. |
| `media_detail` ([library_api.py:331](app/routers/library_api.py:331)) | **199** | endpoint qui agrège demandes + Plex + *arr + calendrier + VF. → `services/media_detail.py` ; le routeur ne garde que la validation et la sérialisation. |
| `_mark_available_and_notify` ([webhook.py:117](app/routers/webhook.py:117)) | 183 | cf. B2 |
| `plex_webhook` ([webhook.py:597](app/routers/webhook.py:597)) | 182 | cf. B2 |
| `check_live_webhook` ([webhook.py:843](app/routers/webhook.py:843)) | 123 | cf. B2 |
| `monitor_radarr_queue` / `monitor_sonarr_queue` | 118 / 121 | la boucle (charger instances + requests + settings → itérer → observer → résoudre → alerter) est commune ; seule la classification par entité diffère. `radarr_queue_monitor` importe déjà `classify_queue_record` de son homologue — pousser la mutualisation jusqu'à la boucle, dans un `arr_queue_monitor.py`. |
| `_merge_users` ([users_api.py:564](app/routers/users_api.py:564)) | 95 | logique métier dans un routeur → `services/user_merge.py` |

### B7. Infrastructure

- **`ArrClient` ouvre un `httpx.AsyncClient` par requête**
  ([arr_http_client.py:22-42](app/services/arr_http_client.py:22)) : aucun pooling de
  connexions, un handshake TCP+TLS par appel. Sur les jobs qui bouclent sur les instances
  (`monitor_*_queue` toutes les 60 s, `check_arr_statuses`, `arr_orphans`) c'est le
  chemin chaud. → un client partagé par `(base_url, timeout)` avec `limits=`, fermé au
  shutdown. Ajouter aussi `raise_for_status` en option pour supprimer les
  `resp.raise_for_status()` répétés dans les ~40 appelants.
- **`AsyncSessionLocal()` ouvert à la main sur 62 sites / 26 fichiers.** Les services
  (hors requête HTTP) sont légitimes ; mais dans les **routeurs**
  (`arr_api`, `calendar_api`, `library_api`, `maintenance`, `metrics_api`, `webhook`) une
  session manuelle contourne `Depends(get_db_async)`. `webhook.py` utilise le motif
  `db = AsyncSessionLocal(); try: … finally: await db.close()` là où
  `async with AsyncSessionLocal() as db:` suffit (et est déjà le motif de `jobs.py`).
  À uniformiser, puis vérifier qu'aucun routeur n'ouvre plus de session hors `Depends`.
- **`jobs.py` : triple bookkeeping.** 20 `job_*` + **16 `cron_*` d'une ligne**
  ([496-562](app/jobs.py:496)) + `WorkerSettings.functions` + `WorkerSettings.cron_jobs`.
  Ajouter un job = 4 éditions. → un `JOB_REGISTRY = [{name, target, interval, event,
  cron}]` et génération des wrappers. L'abstraction `_run` elle-même
  ([78-153](app/jobs.py:78)) est bonne : ne pas y toucher.

### B8. `routers/misc_api.py` — fourre-tout

506 lignes contenant : proxy d'images (+ cache disque), catalogue i18n, onboarding,
SSO Plex, et **tout le domaine « conflits »** (`/conflicts`, `/conflicts/resolve`,
`/conflicts/auto-resolve`, `/conflicts/ignore`, `/conflicts/no-tmdb`,
`/conflicts/orphan` + `_load_ignored`/`_save_ignored`/`_merge_entries`).
→ `image_proxy_api.py`, `onboarding_api.py`, `conflicts_api.py` ; `misc_api.py` ne garde
que i18n + SSO, ou disparaît.
Note : `_load_ignored`/`_save_ignored` ([305-318](app/routers/misc_api.py:305)) persistent
un état applicatif dans un fichier alors que tout le reste est en base — à signaler comme
incohérence de stockage, pas seulement de rangement.

---

## Partie C — Templates Jinja et racine du dépôt

### C1. `setup.html` (626 l.) et `login.html` (544 l.)

Chacun est une page autonome et complète : même `<head>` (favicon SVG inline identique
au caractère près, mêmes 3 `<link>` de fonts), **même CDN Bootstrap 5.3.3 +
Bootstrap-icons** — alors que l'app Vue n'utilise pas Bootstrap du tout — puis 380 et
280 lignes de CSS inline, puis 90 et 145 lignes de JS inline.

Deux systèmes de design coexistent donc (Bootstrap pour l'auth, tokens maison pour
l'app), et les tokens de couleur sont recopiés dans chaque `<style>`.

→ `templates/_auth_base.html` (head + shell de carte, en `{% extends %}`) +
`app/static/css/auth.css` + `app/static/js/{setup,login}.js`. Dans le même mouvement,
vérifier ce qui est réellement utilisé de Bootstrap : si c'est de la grille et deux
boutons, la dépendance CDN (et la requête réseau externe au moment du login) est
supprimable.

### C2. Fichiers morts / hors place à la racine — ✅ fait

- `app/routers/api.py` — stub d'une ligne, plus référencé (`grep` = 0).
- `scratch.py` (14,6 Ko), `scratch2.py`, `fix_settings.py`, `fix_settings_js.py` (ce
  dernier patche un `settings.js` qui n'existe plus), `check_db.py`, `update_db.py`.
- Bases de données commitées ou traînantes : `db.sqlite` (0 o), `plexarr.db` (0 o),
  `migration_test.db` (200 Ko), `.coverage`.
- `implementation_plan.md`, `task.md`, `docs/REFACTORING_TASKS.md` — obsolètes.

À supprimer ou déplacer dans `scripts/` selon ce qui sert encore. Vérifier `.gitignore`
pour les `.db`/`.coverage`.

---

## Priorisation

| # | Chantier | Gain | Risque | Migration DB |
|---|---|---|---|---|
| ✅ 1 | `arr_common.py` (B1) | −450 lignes, 1 seul point de correction API *arr | faible | non |
| ✅ 2 | `utils/format.js` (A3) | 22 `formatDate` → 1 ; corrige les incohérences d'affichage | faible | non |
| ✅ 3 | `ModalShell` + `utils/labels.js` (A1) | 5 modales + 4 tables de libellés divergentes | faible | non |
| ✅ 4 | Composables `useLatestRequest` / `usePolling` / `useSession` / `useDebounced` (A4) | corrige 2 incohérences (polling, 3× `/api/session`) | faible | non |
| ✅ 5 | Helpers backend dupliqués (B5) | 4 copies de `_delete_vf_episode_cache`, 2 du rapprochement LibraryItem | faible | non |
| ✅ 6 | Découper `models.py` en package (B4, hors `Settings`) | lisibilité, réexport = 0 import cassé | nul | non |
| ✅ 7 | Découper `webhook.py` / `arr_api.py` / `misc_api.py` (B2, B3, B8) | modules par domaine, parité de 273 routes | moyen | non |
| ✅ 8 | Primitives `MetricCard` / `PanelCard` / `TabNav` / chargement et toggle (A2) | six primitives testées et adoptées dans les vues principales | moyen (visuel) | non |
| ✅ 9 | Éclater `MediaDetailView` + `MediaRequestsTab` (A5) | composables saisons/actions + sous-composants demande | moyen | non |
| ✅ 10 | `queueRules.js` + réconcilier les 2 définitions de « bloqué » (A5) | une partition commune Dashboard/Downloads | moyen | non |
| ✅ 11 | Nettoyage CSS (A6) | propriétés de primitives rendues à `components.css`/SFC, conflits globaux supprimés | moyen (visuel) | non |
| ✅ 12 | `ArrClient` pooling + sessions (B7) | pools partagés bornés et fermeture au shutdown ; context manager au démarrage | moyen | non |
| ✅ 13 | `_run_vf_scan` et `media_detail` (B6) | scan découpé en helpers ; agrégation déplacée dans `services/media_detail.py` | élevé | non |
| ✅ 14 | Extraire les colonnes email de `Settings` (B4) | `EmailTemplate` par événement + `EmailBranding`, façade compatible | élevé | **oui (`0089`)** |
| ✅ — | Nettoyage des fichiers morts (C2) | 10 fichiers, dont 4 cassés | nul | non |

Les items 1 à 6 étaient behavior-preserving et vérifiables mécaniquement ; ils sont
faits. Le 7 exige la même capture avant/après des routes. Les 11, 13 et 14 méritent
chacun leur propre branche.

**Changements d'affichage assumés au cours des chantiers 1-6** — tous des harmonisations,
détaillées dans les messages de commit :
1. le statut `failed` s'affichait « Echec », « Échec » ou « Erreur » selon la page ; les
   formes accentuées correctes l'emportent partout (idem « A approuver », « Refusee »,
   « Serie ») ;
2. la croix de fermeture de `ConfirmModal` passe du caractère « × » à l'icône Lucide, comme
   les quatre autres modales ;
3. la page Bibliothèque ne rafraîchit plus un onglet en arrière-plan (elle était la seule
   des six à ne pas avoir le garde de visibilité) ;
4. le rapprochement demande → `LibraryItem` de `vff_scanner` privilégie désormais le GUID
   Plex sur les identifiants externes, comme le faisait déjà `plex_sync` — un `tmdb_id`
   partagé pouvait faire attribuer le statut VF au mauvais média.

**Deux constats à trancher côté produit**, hors refactorisation :
- remplacer les 74 `class="badge"` par `<StatusBadge>` change l'apparence de 29 fichiers ;
- `DashboardView` et `DownloadsView` ont deux définitions divergentes de « bloqué » pour la
  file *arr (A5) — un chiffre du tableau de bord ne correspond pas à la page qu'il ouvre.

**Outillage manquant relevé en chemin** : le dépôt n'a pas d'ESLint. Un `onUnmounted`
laissé sans son import pendant le chantier 4 aurait levé un `ReferenceError` au montage de
la page Bibliothèque sans que Vite ni `npm run build` ne le signalent. Un
`eslint-plugin-vue` avec `no-undef` ferme cette classe d'erreur.

## Vérification après chaque étape

```bash
python -m pytest -q && npm run test:unit && docker compose up --build -d && docker compose logs --tail 20 plex-rss
```
