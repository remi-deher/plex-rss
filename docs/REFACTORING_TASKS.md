# Plan de refactorisation — dégraissage & modularisation

Spécification autonome destinée à être exécutée par un agent IA. Chaque tâche est
**behavior-preserving** (aucun changement de comportement observable) et validée par la
suite de tests. Traiter **une tâche à la fois**, dans l'ordre, avec un commit par tâche.

## Règles générales (à respecter pour CHAQUE tâche)

1. **Aucun changement de comportement.** On déplace/factorise du code, on ne modifie ni
   les réponses HTTP, ni les emails, ni la logique métier.
2. **Vérification après chaque tâche** (obligatoire, dans l'ordre) :
   ```bash
   python -m pytest -q -k "not test_check_vf_statuses_propagates_linked_library_item_without_rescanning_request"
   # attendu : "538 passed, 1 deselected" (le test désélectionné est un flaky pré-existant, sans rapport)
   docker compose up --build -d
   docker compose logs --tail 20 plex-rss   # doit finir par "Application startup complete."
   ```
3. **Un commit par tâche**, message clair (`refactor: <tâche>`). Ne pas mélanger deux tâches.
4. Si une tâche ne peut pas rester behavior-preserving sur un site précis, **laisser ce
   site tel quel** et le noter dans le message de commit, plutôt que de forcer.

## Faits d'architecture (état actuel, déjà vérifié)

- `app/routers/api.py` : **3708 lignes, 120 endpoints**, `router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(require_auth)])`, monté dans `app/main.py` (`app.include_router(api.router)`).
- `app/utils.py` contient déjà : `db_session`, `get_or_404`, `parse_email_list`, `identity_keys`.
- Il n'existe **pas** de `app/dependencies.py`.
- `get_db` vient de `app/database.py` ; le modèle `Settings` de `app/models.py`.
- `require_auth` est défini dans `api.py` (et une copie dans `email_templates.py`).
- Suite de tests : dossier `tests/`, 538 tests verts (hors le flaky désélectionné).

---

## Tâche 1 — Helpers de date (`now_utc` / `now_utc_naive`)

**But :** centraliser les 46 `datetime.now(timezone.utc)` (dont 19 en `.replace(tzinfo=None)`).

**À faire :**
1. Ajouter dans `app/utils.py` :
   ```python
   from datetime import datetime, timezone

   def now_utc() -> datetime:
       """Instant courant, aware UTC."""
       return datetime.now(timezone.utc)

   def now_utc_naive() -> datetime:
       """Instant courant UTC sans tzinfo (colonnes DB stockées en naïf-UTC)."""
       return datetime.now(timezone.utc).replace(tzinfo=None)
   ```
2. Remplacer **exactement** :
   - `datetime.now(timezone.utc).replace(tzinfo=None)` → `now_utc_naive()` (19 sites)
   - `datetime.now(timezone.utc)` restant → `now_utc()`
3. Ajouter l'import `from ..utils import now_utc, now_utc_naive` (ou chemin adapté) dans chaque
   fichier touché : principalement `app/routers/api.py`, `app/scheduler.py`,
   `app/notification_queue.py` (+ tout autre fichier concerné, cf. `grep -rl 'datetime.now(timezone.utc)' app`).

**NE PAS toucher :**
- Les **4** `datetime.now()` **naïfs locaux** (sans `timezone.utc`) — ils sont intentionnels.
- Les imports `from datetime import datetime, timezone, timedelta` restent (encore utilisés pour `timedelta`, `fromisoformat`, etc.).

**Acceptation :**
- `grep -rn 'datetime.now(timezone.utc)' app --include=*.py` → **0 résultat**.
- Tests verts + Docker OK.

---

## Tâche 2 — Dépendance `current_settings` (supprimer les `db.query(Settings).first()`)

**But :** réduire les **73** `db.query(Settings).first()`. On ne convertit que les **endpoints
de routers** dont le comportement est « récupérer les settings, 404 si absent » ou « supposer
présent ». On **ne touche pas** aux services/scheduler (hors scope requête) ni aux sites avec
gestion de `None` spécifique (redirection `/setup`, valeur par défaut, etc.).

**À faire :**
1. Créer `app/dependencies.py` :
   ```python
   from fastapi import Depends, HTTPException
   from sqlalchemy.orm import Session

   from .database import get_db
   from .models import Settings


   def get_settings_or_404(db: Session = Depends(get_db)) -> Settings:
       s = db.query(Settings).first()
       if not s:
           raise HTTPException(status_code=404, detail="Paramètres non initialisés")
       return s
   ```
2. Dans les endpoints de `app/routers/*.py` qui font :
   ```python
   s = db.query(Settings).first()
   if not s:
       raise HTTPException(status_code=404, ...)   # ou 404 équivalent
   ```
   → remplacer par un paramètre `settings: Settings = Depends(get_settings_or_404)` et
   supprimer la requête + le guard. Adapter le nom de variable utilisé ensuite (`s`/`settings`).
3. **Cas à NE PAS convertir** (laisser tel quel) :
   - Tout site hors router (`scheduler.py`, `notification_queue.py`, `services/*`).
   - Les endpoints qui gèrent `None` **sans 404** : redirection vers `/setup`, création d'un
     `Settings` par défaut, valeur de repli silencieuse, etc.
   - `update_settings` / `save_templates` et assimilés qui **écrivent** dans `s` après un guard
     personnalisé : convertir seulement si le guard est un simple 404, sinon laisser.
4. Traiter fichier par fichier ; relancer les tests après chaque fichier de router converti.

**Acceptation :**
- Réduction nette du nombre de `db.query(Settings).first()` dans `app/routers/` (viser la
  majorité des sites-router). Le compte global baisse significativement.
- Aucun changement de code de statut/redirection observable → tests verts + Docker OK.

---

## Tâche 3 — Collapse des fonctions `send_*` d'email

**But :** les 9 `async def send_*_notification` de `app/services/email_service.py` répètent le
même squelette (build ctx → template-ou-défaut → render → sujet-ou-défaut + fallback → `_send`).
Le motif `getattr(settings, X, None) if isinstance(..., str) else None` apparaît 8 fois.

**À faire :**
1. Ajouter un helper interne :
   ```python
   def _resolve_str_setting(settings, field):
       val = getattr(settings, field, None)
       return val if isinstance(val, str) else None


   async def _send_templated(
       settings, request, recipient, display_name=None, *,
       template_field, default_template, subject_field, default_subject, subject_fallback,
       extra_ctx=None,
   ):
       ctx = _build_context(request, display_name)
       if extra_ctx:
           ctx.update(extra_ctx)
       html = render_template(_resolve_str_setting(settings, template_field) or default_template, ctx)
       subject = render_subject(
           _resolve_str_setting(settings, subject_field) or default_subject, ctx, fallback=subject_fallback
       )
       await _send(settings, recipient, subject, html)
   ```
2. Réécrire avec ce helper **uniquement les fonctions au motif simple** :
   - `send_request_notification` → `template_field="email_request_template"`, `default_template=DEFAULT_REQUEST_TEMPLATE`, `subject_field="email_request_subject"`, `default_subject="[Plexarr] Nouvelle demande : {{ title }}"`, `subject_fallback=f"[Plexarr] Nouvelle demande : {request.title}"`.
   - `send_available_notification` → `email_available_template` / `DEFAULT_AVAILABLE_TEMPLATE` / `email_available_subject` / `"[Plexarr] {{ title }} est disponible sur Plex !"` / `f"[Plexarr] {request.title} est disponible sur Plex !"`.
   - `send_available_vf_notification` → `email_available_vf_template` / `DEFAULT_AVAILABLE_VF_TEMPLATE` / `email_available_vf_subject` / `"[Plexarr] {{ title }} est disponible sur Plex en VF !"` / fallback correspondant.
   - `send_available_vo_tracking_notification` → `email_available_vo_tracking_template` / `DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE` / `email_available_vo_tracking_subject` / `"[Plexarr] {{ title }} est disponible sur Plex en VO !"` / fallback correspondant.
   - `send_failure_notification` → `email_failure_template` / `DEFAULT_FAILURE_TEMPLATE` / `email_failure_subject` / `"[Plexarr] Échec de transmission : {{ title }}"` / fallback correspondant, avec `extra_ctx={"reason": reason or "Erreur inconnue"}`.
3. **Laisser leur logique propre** (mais elles peuvent réutiliser `_resolve_str_setting`) :
   - `send_vo_only_notification`, `send_vf_available_notification` (détection de jalon langue
     via `_render_language_milestone_email` **avant** le fallback template).
   - `send_episode_track_notification` (utilise `_render_milestone_email`).
   - `send_partially_available_notification` (compteurs d'épisodes + sujet non-Jinja).

**Acceptation :**
- `python -m pytest tests/test_email_service.py -q` → **27 passed**, assertions inchangées
  (les libellés avec `&nbsp;` et les sujets restent identiques au rendu actuel).
- Suite complète verte + Docker OK.

---

## Tâche 4 — Extraire les filtres du calendrier

**But :** dans `unified_calendar` (`api.py`), le bloc de filtres `search / user / status / source /
vf` est dupliqué entre la boucle épisodes (Sonarr) et la boucle films (Radarr).

**À faire :**
1. Ajouter un helper au-dessus de l'endpoint :
   ```python
   def _calendar_entry_excluded(tracked, *, search_text, search_target, user, status, source, vf) -> bool:
       """True si l'entrée doit être exclue selon les filtres avancés (hors type/tracked_only)."""
       if search_text and search_text.lower() not in (search_target or "").lower():
           return True
       if user and (not tracked or user not in tracked.get("requested_by_ids", [])):
           return True
       if status and (not tracked or tracked.get("request_status") != status):
           return True
       if source and (not tracked or source not in tracked.get("request_sources", [])):
           return True
       if vf:
           if not tracked:
               return True
           if vf == "vf" and not (tracked.get("in_library") and tracked.get("has_vf") is True):
               return True
           if vf == "vo" and not (tracked.get("in_library") and tracked.get("has_vf") is False):
               return True
           if vf == "unchecked" and not (tracked.get("in_library") and tracked.get("has_vf") is None):
               return True
           if vf == "requested" and tracked.get("in_library"):
               return True
       return False
   ```
2. Remplacer les deux blocs dupliqués par un appel :
   - épisodes : `if _calendar_entry_excluded(tracked, search_text=search, search_target=series.get("title"), user=user, status=status, source=source, vf=vf): continue`
   - films : idem avec `search_target=title`.
3. **Garder inline** (ils diffèrent) : `tracked_only` et le filtre `type` (`if type == "movie": continue` côté épisodes, `if type == "show": continue` côté films).

**Acceptation :**
- `python -m pytest tests/test_calendar.py -q` → **6 passed** (surtout `test_calendar_advanced_filtering`, qui couvre les 7 cas de filtre).
- Suite complète verte + Docker OK.

---

## Tâche 5 — Découper `api.py` en routers par domaine (gros chantier)

**But :** casser le monolithe de 3708 lignes / 120 endpoints en modules par domaine.

**Contrainte de compatibilité :** chaque endpoint doit rester au **même chemin** (`/api/...`),
avec la même dépendance d'auth. Deux approches acceptables — choisir la 1 :

- **Approche recommandée :** chaque module domaine définit
  `router = APIRouter(prefix="/api", tags=["<domaine>"], dependencies=[Depends(require_auth)])`
  et est inclus dans `main.py`. Pour cela, **déplacer `require_auth`** dans `app/dependencies.py`
  (créé en Tâche 2) et l'importer partout (y compris `email_templates.py`, qui en a une copie).

**Procédure :**
1. Déplacer `require_auth` vers `app/dependencies.py` ; remplacer les définitions locales par un import.
2. Créer un module partagé `app/routers/_shared.py` (ou `app/serializers.py`) pour les helpers
   transverses utilisés par plusieurs domaines : `_format_datetime`, constructeurs de dicts,
   index de suivi du calendrier, etc. (voir Tâche 6).
3. Créer les modules par domaine et **y déplacer les endpoints + leurs helpers dédiés**. Bucketing
   suggéré (adapter selon les préfixes réels observés dans `api.py`) :
   - `app/routers/requests_api.py` — demandes (`/api/requests...`, actions, stats de demandes).
   - `app/routers/calendar_api.py` — `/api/calendar`, `/api/upcoming` + helpers `_parse_arr_date`, `_arr_poster`, `_movie_release_events`, `_calendar_entry_excluded`.
   - `app/routers/library_api.py` — bibliothèque, détail média, timeline.
   - `app/routers/arr_api.py` — Sonarr/Radarr/Prowlarr (recherche interactive, grab, instances si côté API).
   - `app/routers/vff_api.py` — statut/détail VF, actions VFF.
   - `app/routers/settings_api.py` — `/api/settings`, sous-réglages.
   - `app/routers/notifications_api.py` — logs de notif, aperçu/preview éventuel, test SMTP.
   - `app/routers/metrics_api.py` — `/api/metrics`, health, activité, poll history.
   - `app/routers/users_api.py` — utilisateurs (si dans api.py).
   - `app/routers/misc_api.py` — le reliquat non classable.
4. Mettre à jour `app/main.py` : remplacer `app.include_router(api.router)` par les
   `include_router` de chaque nouveau module. Conserver l'ordre relatif aux autres routers.
5. Supprimer `api.py` une fois vidé (ou le laisser ne réexporter que ce qui est importé ailleurs —
   **vérifier** : `grep -rn "from .*routers.api import\|routers\.api\." app tests` et corriger les imports,
   notamment `from ..scheduler import ...` et les imports croisés helpers).
6. Attention aux **imports circulaires** : les helpers partagés vont dans `_shared.py`, pas dans un
   module domaine importé par un autre.

**Acceptation (parité de routes obligatoire) :**
- Avant le split, capturer la liste des routes :
  ```bash
  python -c "from app.main import app; import json; print(json.dumps(sorted((r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r,'methods'))))" > /tmp/routes_before.json
  ```
- Après le split, régénérer `/tmp/routes_after.json` de la même façon et vérifier
  `diff /tmp/routes_before.json /tmp/routes_after.json` → **aucune différence**.
- Suite complète verte + Docker OK (l'app démarre, tous les endpoints répondent comme avant).

---

## Tâche 6 — Sérialiseurs par modèle (optionnel, après #5)

**But :** centraliser les ~15 constructions manuelles de dicts + `_format_datetime`.

**À faire :** dans `app/serializers.py`, créer des fonctions pures :
`serialize_request(r) -> dict`, `serialize_calendar_event(...) -> dict`, `serialize_user(u) -> dict`,
etc., reprenant **à l'identique** les dicts actuels. Remplacer les constructions inline par ces
appels. `_format_datetime` devient un helper de ce module.

**Acceptation :** tests verts (les payloads JSON doivent être strictement identiques) + Docker OK.

---

## Tâche 7 — Découper `settings.html` (optionnel, plus faible ROI)

**But :** le template fait 3353 lignes (7 onglets + gros `<script>` inline).

**À faire :**
1. Extraire chaque onglet dans `app/templates/settings/_connexions.html`,
   `_notifications.html`, `_templates.html`, `_avance.html`, `_vff.html`, `_conflits.html`,
   `_maintenance.html`, inclus via `{% include "settings/_xxx.html" %}` depuis `settings.html`.
2. Déplacer le bloc `<script>` (hors expressions Jinja) vers un fichier statique
   `app/static/js/settings.js` servi par la route statique, en gardant dans le template
   uniquement les rares valeurs injectées par Jinja (via `data-*` ou un petit objet JSON inline).
   ⚠️ Attention aux blocs `{% raw %}` déjà présents dans le JS (variables de templates email) :
   le code sorti en `.js` n'a plus besoin de `{% raw %}`.
3. Vérifier l'équilibre des balises et le rendu.

**Acceptation :** la page `/settings` se rend et se comporte à l'identique (navigation onglets,
éditeur de templates, aperçu, sauvegarde). Rendu Jinja OK + Docker OK.

---

## Ordre recommandé

1 → 2 → 3 → 4 → 5 → (6) → (7). Les tâches 1-4 déblaient le terrain à faible risque ; la 5 est le
gros gain structurel ; 6-7 sont du polish optionnel. **Commit + suite de tests verte entre chaque.**
