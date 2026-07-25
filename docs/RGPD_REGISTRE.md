# Registre des activités de traitement (RGPD, Art. 30)

> Modèle de registre pour une instance **Plexarr** auto-hébergée. Il documente les
> traitements de données personnelles réalisés par le logiciel. Chaque administrateur
> d'instance est responsable de traitement pour son propre déploiement : complétez les
> champs entre crochets `[…]` avec les informations réelles de votre instance.
>
> Ce document décrit le comportement du **logiciel**. Il ne constitue pas un avis
> juridique. Pour un déploiement à finalité autre que strictement personnelle/familiale,
> faites valider ce registre par une personne compétente.

## 1. Responsable de traitement

| Champ | Valeur |
|---|---|
| Nom / entité | `[à compléter — cf. Réglages → RGPD]` |
| Contact | `[email de contact — cf. Réglages → RGPD]` |
| Finalité générale | Suivi personnel des demandes de médias (films/séries) et de leur disponibilité sur une instance Plex partagée entre proches |
| Caractère | Auto-hébergé, sans finalité commerciale |

## 2. Finalités et base légale

| Finalité | Base légale (Art. 6) |
|---|---|
| Créer et gérer un compte pour suivre ses demandes | Exécution du service demandé par la personne |
| Transmettre les demandes à Sonarr/Radarr et suivre les téléchargements/imports | Exécution du service demandé |
| Envoyer les notifications (disponibilité, VF, échec) souhaitées | Exécution du service / intérêt légitime |
| Journaliser les tentatives de connexion (IP) | Intérêt légitime — sécurité, protection contre les accès abusifs |
| Diagnostiquer les incidents techniques | Intérêt légitime — bon fonctionnement du service |

Aucune décision automatisée ni profilage au sens de l'Art. 22.

## 3. Catégories de personnes concernées

- Utilisateurs invités sur l'instance (comptes Plex reliés).
- Administrateur(s) de l'instance.

## 4. Catégories de données traitées

| Catégorie | Données | Table(s) | Rétention |
|---|---|---|---|
| Identité | Identifiant Plex, UUID Plex, nom d'affichage, avatar | `plex_users` | Tant que le compte existe |
| Contact | Email Plex, email de notification | `plex_users` | Tant que le compte existe |
| Authentification | Hash bcrypt du mot de passe, secret TOTP (chiffré), passkeys (clé publique) | `plex_users`, `passkey_credentials` | Tant que le compte existe |
| Activité | Historique des demandes de médias, statuts, co-demandeurs | `media_requests` | Tant que le compte existe |
| Notifications | Journaux d'envoi (email destinataire, canal, résultat), jalons | `notification_logs`, `notification_milestones` | `notification_log_retention_days` (défaut 30 j) |
| Signalements | Signalements de problème média (nom du rapporteur) | `media_issues` | Tant que le compte existe |
| Connexion / sécurité | Adresse IP, horodatage, username, succès/échec | `login_attempts` | `login_attempt_retention_days` (**défaut 90 j**) |
| Journaux techniques | Actions admin, événements de diagnostic, exécutions de tâches | `admin_action_logs`, `diagnostic_events`, `job_run_logs` | `audit_log_retention_days` (défaut : indéfini, configurable) |
| Historique de polling | Statistiques d'exécution des cycles | `poll_history` | `poll_history_retention_days` (défaut 30 j) |

Les secrets (tokens Plex/\*arr, mots de passe SMTP/clients, clés API, secrets TOTP) sont
**chiffrés au repos** (Fernet, colonnes `EncryptedText`). Les mots de passe sont **hachés**
(bcrypt), jamais stockés en clair. Les adresses email ne sont pas écrites en clair dans les
journaux applicatifs (masquage `mask_email`).

## 5. Destinataires / sous-traitants et transferts

| Destinataire | Données échangées | Localisation | Base de transfert |
|---|---|---|---|
| Plex Inc. | Authentification, lecture de la watchlist | États-Unis | Politique de confidentialité Plex `[à vérifier]` |
| TMDB (The Movie Database) | Recherche d'affiches/synopsis (pas de donnée personnelle de la personne concernée) | États-Unis | Politique TMDB `[à vérifier]` |
| Sonarr / Radarr / Prowlarr (instances de l'administrateur) | Transmission des demandes | Auto-hébergé (LAN) | Sous contrôle de l'administrateur |
| Canaux de notification activés (Email/SMTP, Discord, Telegram, ntfy, Gotify) | Email destinataire ou identifiant de canal, titre du média | Selon le service configuré | Selon le fournisseur choisi |

Aucune donnée n'est vendue ni utilisée à des fins publicitaires.

## 6. Droits des personnes et modalités d'exercice

| Droit (Art.) | Mise en œuvre dans Plexarr |
|---|---|
| Accès / portabilité (15, 20) | Export JSON par personne : `GET /api/users/{id}/data-export` (bouton « Exporter les données » dans la fiche utilisateur) |
| Effacement (17) | Suppression d'un compte → purge en cascade des données rattachées (`services/gdpr.erase_user_data`) |
| Rectification (16) | Édition de la fiche utilisateur |
| Limitation / opposition (18, 21) | Désactivation du compte / des canaux de notification ; contact administrateur |
| Réclamation | CNIL — <https://www.cnil.fr/fr/plaintes> |

Contact pour l'exercice des droits : voir la page publique `/privacy` (renseignée via
Réglages → RGPD).

## 7. Mesures de sécurité

- Chiffrement au repos des secrets (Fernet) ; clé `PLEXARR_ENCRYPTION_KEY` à conserver séparément des sauvegardes.
- Mots de passe hachés (bcrypt).
- Cookie de session `HttpOnly`, `SameSite=Strict`, `Secure` (derrière HTTPS).
- Limitation du nombre de tentatives de connexion (anti-force brute).
- Rétention bornée des adresses IP et purge automatique des journaux.
- Masquage des emails dans les journaux applicatifs.
- Recommandation : placer l'instance derrière HTTPS et ne pas exposer PostgreSQL/Redis.

## 8. Durées de conservation — synthèse

| Donnée | Réglage | Défaut |
|---|---|---|
| Journaux de notification | `notification_log_retention_days` | 30 j |
| Historique de polling | `poll_history_retention_days` | 30 j |
| Tentatives de connexion (IP) | `login_attempt_retention_days` | **90 j** |
| Journaux d'audit & diagnostic | `audit_log_retention_days` | Indéfini (configurable) |
| Compte, demandes, signalements | — | Tant que le compte existe |

---

*Dernière mise à jour du modèle : 22 juillet 2026. Adaptez et datez ce registre pour votre
instance.*
