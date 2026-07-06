# Plan — Clarifier le modèle de données : `MediaRequest` vs `LibraryItem`

> **DÉCISION (2026-07-06) : Option B retenue et implémentée.** Table `library_items`
> séparée, migration `0030` (backfill des lignes `plex_sync` + suppression, réversible).
> UI : deux sections — **Bibliothèque** (`/library`, union library_items + demandes) et
> **Demandes** (`/requests`, hub du pipeline). Le document ci-dessous conserve l'analyse
> initiale des options pour référence.

## 1. Le problème

Depuis l'ajout du sync Plex et du suivi VFF, la table `media_requests`
([app/models.py](../app/models.py)) porte **deux concepts distincts** :

| Concept | Ce que c'est | Comment il naît |
|---|---|---|
| **Demande** | Quelqu'un veut un média | watchlist Plex, Overseerr, ajout manuel |
| **Élément de bibliothèque** | Un média déjà présent dans Plex | `sync_plex_media()` avec `source="plex_sync"` |

Pour faire entrer un élément de bibliothèque dans une table pensée pour des
demandes, le code triche ([app/scheduler.py](../app/scheduler.py), `sync_plex_media`) :

```python
plex_user_id="admin",          # ← il n'y a pas de demandeur
plex_user="Plex Library",      # ← faux demandeur
status=RequestStatus.available,# ← forcé, il n'y a pas de flux de demande
available_mail_sent=True,      # ← pour couper les notifications
request_mail_sent=True,        # ← idem
```

### Symptômes concrets
- Des champs n'ont **aucun sens** pour un élément de bibliothèque :
  `plex_user_id`, `plex_user`, `request_mail_sent`, `requested_at`,
  `extra_requesters`.
- L'enum `RequestStatus` (`pending → sent_to_arr → available → failed`) n'a
  **pas d'état** « présent en bibliothèque, jamais demandé ».
- Les compteurs par utilisateur, la page Utilisateurs et les stats sont pollués
  par le faux utilisateur `admin` / `Plex Library`.
- Toute requête « demandes de X » doit désormais penser à exclure `plex_sync`.

### Champs communs aux deux (à ne PAS dupliquer)
`title`, `year`, `media_type`, `tmdb_id`, `tvdb_id`, `imdb_id`, `plex_guid`,
`poster_url`, `overview`, `arr_id`, `arr_slug`, `arr_instance_id`,
`has_vf`, `vf_category`, `vf_checked_at`, `vf_available_at`.

## 2. Les trois options

### Option A — Assumer « MediaRequest = média suivi » (renommage sémantique)
On acte que la table suit **tout média d'intérêt**, demandé ou non, et on rend
le demandeur optionnel.

- `plex_user_id` → nullable ; introduire un champ `origin`
  (`watchlist` | `overseerr` | `manual` | `plex_library`).
- Ajouter un état ou un booléen `is_requested` pour distinguer demande vs présence.
- Renommer dans l'UI « Demandes » → « Médias » là où les deux se mélangent.

**Effort** : faible/moyen (1 migration additive, pas de déplacement de données).
**Risque** : faible.
**Limite** : la sémantique reste un peu floue ; on garde une table « fourre-tout ».

### Option B — Séparer `LibraryItem` de `MediaRequest` (deux tables)
Modèle propre : une table `library_items` (présence Plex + état VF) et
`media_requests` (demandes uniquement). Une demande *référence* éventuellement
un `library_item` quand le média arrive.

- `library_items` porte : identité média + `plex_guid` + champs VF + lien arr.
- `media_requests` redevient strictement « une demande d'un utilisateur ».
- Le suivi VFF déménage sur `library_items`.

**Effort** : élevé (2 migrations, backfill des `plex_sync`, réécriture des
requêtes VFF, du sync, des stats, des templates).
**Risque** : moyen/élevé (migration de données existantes).
**Bénéfice** : modèle conceptuellement juste, évolutif (base d'une vraie
« vue Bibliothèque » indépendante des demandes).

### Option C — Statu quo + garde-fous
Ne rien restructurer, mais documenter la convention et centraliser les filtres
(`source == "plex_sync"`) dans des helpers pour éviter les oublis.

**Effort** : minimal. **Risque** : nul court terme, mais la dette grossit.

## 3. Recommandation

**Option A maintenant**, en gardant l'Option B comme cible si la « Bibliothèque »
devient un pilier de premier plan.

Raison : l'Option A supprime 90 % de la douleur (faux utilisateur, stats
polluées, sémantique du statut) pour un coût faible et sans migration de données
risquée. Elle prépare le terrain pour B (le champ `origin` sert dans les deux
modèles). On ne paie le coût de B que si/quand la direction produit le justifie.

## 4. Étapes concrètes si Option A retenue

1. **Migration Alembic additive** :
   - `media_requests.plex_user_id` → nullable.
   - Ajouter `origin TEXT` (défaut dérivé de `source`).
   - Backfill : `origin = 'plex_library'` où `source = 'plex_sync'`, sinon mappé
     depuis `source`.
2. **`sync_plex_media`** : arrêter d'écrire `plex_user_id="admin"` /
   `plex_user="Plex Library"` ; poser `origin="plex_library"`,
   `plex_user_id=None`.
3. **Stats / page Utilisateurs** : filtrer `origin != 'plex_library'` (helper
   unique `requests_only(query)`), au lieu de compter le faux user.
4. **UI** : dans « Bibliothèque », afficher « — » ou « Plex » au lieu de
   « Plex Library » quand `plex_user_id is None`.
5. **Nettoyage** : script one-shot pour reclasser les lignes `plex_sync`
   existantes.

## 5. Question ouverte à trancher

- La « Bibliothèque » doit-elle à terme vivre **indépendamment** des demandes
  (Option B) ou rester une facette de la même liste (Option A) ?
- La réponse dépend de la direction produit — à décider à l'étape suivante.
