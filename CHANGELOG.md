

### build

- bump fastapi from 0.137.0 to 0.137.1 (#21) ([25d758e](https://github.com/remi-deher/plex-rss/commit/25d758e804ff6c43bd437b73a9649de67a781ccf))
- bump sqlalchemy from 2.0.50 to 2.0.51 (#22) ([dbeb3d3](https://github.com/remi-deher/plex-rss/commit/dbeb3d36e581be8e61cdb9cbc7ed73cc6e7c9529))
- bump httpx from 0.27.2 to 0.28.1 (#23) ([e34992d](https://github.com/remi-deher/plex-rss/commit/e34992dd1d8cf6ecdbf21f7ccacb320e05fde740))

### style

- ruff format sur 8 fichiers ([82b5b5b](https://github.com/remi-deher/plex-rss/commit/82b5b5b3ca1abb3c527ba5fdf83a8ebfacdeb1be))
- format python files with ruff ([4387835](https://github.com/remi-deher/plex-rss/commit/4387835dd843b8e70af56b0d9754778a8a0fb881))

### test

- filtrer le DeprecationWarning httpx/starlette dans pytest.ini ([cd47c25](https://github.com/remi-deher/plex-rss/commit/cd47c25ddff1f56eb48b495b245af88610c9f3e2))

### ♻️ Refactoring

- factorisation + tests unitaires complets (73% couverture) ([8bf9ff8](https://github.com/remi-deher/plex-rss/commit/8bf9ff81d909151afa8af1ca7ea1e65a560794a2))
- reorganiser la carte Plex en sous-sections (Connexion / Source watchlist / Comportement) ([a655841](https://github.com/remi-deher/plex-rss/commit/a65584123745396287bac76c1559ba9c93a388c7))
- vocabulaire orienté utilisateur, parcours de demande lisible et hiérarchie des réglages ([2869afa](https://github.com/remi-deher/plex-rss/commit/2869afa8d5b061f805d0bd7741e7dc76dbcba5e8))
- clarifier l'onglet Notifications ([ef6680b](https://github.com/remi-deher/plex-rss/commit/ef6680b37ce8ae940029438f3a8b15cd6ef08299))

### ⚡ Performance

- paralleliser /api/health, cacher next_release_at, eviter le N+1 Sonarr/Radarr ([241be93](https://github.com/remi-deher/plex-rss/commit/241be930d8472c3128a4ea2b4b5d9ea5e544a398))

### ✨ Nouveautés

- per-user notification controls and disabled-user email fix ([fecd363](https://github.com/remi-deher/plex-rss/commit/fecd3636a8728908d3e2fcc50a0a2cd81d6af7a4))
- RSS-only email by default, 3-state mail status in requests table ([fa8ade2](https://github.com/remi-deher/plex-rss/commit/fa8ade25df5034fc6c9ab2573dc1f42e392231fe))
- notification history log in settings ([30f3add](https://github.com/remi-deher/plex-rss/commit/30f3adde53f8efd0b1aa0fc0662d92ab2ea293e4))
- notification improvements batch 1 ([c48ecf9](https://github.com/remi-deher/plex-rss/commit/c48ecf956b9007b0479a6ff2357fffe4f39445bd))
- notification improvements batch 2 ([ba04259](https://github.com/remi-deher/plex-rss/commit/ba042594ac70a18772331f6481853f89260bc072))
- notification improvements batch 3 ([96e2c66](https://github.com/remi-deher/plex-rss/commit/96e2c66774522f857cc2d0e70431addc2bad837b))
- add custom subjects with variables and preview-as-user feature ([02d5676](https://github.com/remi-deher/plex-rss/commit/02d5676643e92757468642820ccb94670fc824a2))
- add variable insertion helper and fix timezone offset in notification settings and request pages ([aba77e4](https://github.com/remi-deher/plex-rss/commit/aba77e4e179f7ff1b242fd22fa01b12283bb3503))
- add option to mark requests as processed without sending emails ([8418b94](https://github.com/remi-deher/plex-rss/commit/8418b94b534008416d1651539489d2c2b45b26e4))
- implement bulk actions, source filter, available date sort, quick links, error visibility, and unit tests ([30f1429](https://github.com/remi-deher/plex-rss/commit/30f14295959c5acdda2c4ec47272c432c4128f73))
- mark-processed envoie le mail intelligent selon le statut ([6f6a821](https://github.com/remi-deher/plex-rss/commit/6f6a821dc9c99e1ee3d8d0050eb37f09e69ba786))
- separer renvoi mail demande et envoi mail dispo/cloture sur mark-processed ([9103cec](https://github.com/remi-deher/plex-rss/commit/9103cec41929a1fc7e01f85f3ca61005982462d3))
- importer tous les comptes Seer meme sans demande + badge dedie ([9dff193](https://github.com/remi-deher/plex-rss/commit/9dff193869fbc5074e15172dc4fe03948f5a06f8))
- afficher Transmis à Sonarr/Radarr au lieu de Envoyé selon le type de média ([9d04069](https://github.com/remi-deher/plex-rss/commit/9d040695aaf05d872712917b1d578f50eded47da))
- renommer le filtre de statut Envoyées en Transmises ([26afc55](https://github.com/remi-deher/plex-rss/commit/26afc5504543b48952af49b2aa5d0d732ceddc8f))
- prochaines sorties, top demandés, espace disque, détail utilisateur ([40cfeb4](https://github.com/remi-deher/plex-rss/commit/40cfeb4aa8472bb9cc3454181176f4a1b4f54f83))
- squelettes, modale de confirmation, thème clair, raccourci recherche, micro-animations ([8138edd](https://github.com/remi-deher/plex-rss/commit/8138edda468f9da04d3e23ec41a2fa3edcf258af))
- parite du theme clair sur les styles par page ([622e418](https://github.com/remi-deher/plex-rss/commit/622e41855805f8e579d22e0d387099f5ee1bb5f3))
- filtrage AJAX, chips filtres, undo suppression, grille multi-select, auto-refresh statuts ([b314c53](https://github.com/remi-deher/plex-rss/commit/b314c53c8497bb62aea825614e2e39daee351a02))

### 🐛 Corrections

- ruff import sorting + mypy Protocol pour get_or_404 ([7e0b44f](https://github.com/remi-deher/plex-rss/commit/7e0b44fa5abd0490fdd455bb721c0056bba5d2a6))
- omit empty user_id query parameter in email preview ([3a01538](https://github.com/remi-deher/plex-rss/commit/3a01538b9d877cb6b199edb7da203a244da76f32))
- migrate requests page status and type filters to server side and preserve query parameters in pagination ([1075e89](https://github.com/remi-deher/plex-rss/commit/1075e8905f727f250def991ec0121a65f39b119f))
- fallback direct sur Sonarr/Radarr quand Seer ne detecte pas la disponibilite ([9042c6a](https://github.com/remi-deher/plex-rss/commit/9042c6a2f8823229b0c8188cc7bd52198f652080))
- les emails reels utilisent le Nom d'usage (custom_name) comme l'apercu ([d2d139e](https://github.com/remi-deher/plex-rss/commit/d2d139e9c75acb025c63c8628d624a22865af62e))
- ajouter X-Plex-Client-Identifier pour la récupération de la watchlist API ([4d5819c](https://github.com/remi-deher/plex-rss/commit/4d5819c9faa8c070f2d8737e088dbba28658d813))
- utiliser discover.provider.plex.tv pour la watchlist (metadata.provider renvoie 404) ([774aa4b](https://github.com/remi-deher/plex-rss/commit/774aa4b61ba71efbc4f372c988231cd85e24a11e))
- corriger la boucle de rechargement infinie sur le filtre statut de la page demandes ([e6faad4](https://github.com/remi-deher/plex-rss/commit/e6faad49a19801155ef827d36b679ecf48c89325))
- lire les services depuis d.services dans /api/health ([407ef2f](https://github.com/remi-deher/plex-rss/commit/407ef2fb21da6134bc4fcbd23801772d1e8de41a))
- normaliser les demandes RSS sur TMDB (resolution IMDB via Radarr) ([343b6a0](https://github.com/remi-deher/plex-rss/commit/343b6a02f86f957ab42b2fb5268a10883fce19f6))
- resoudre les noms de co-demandeurs en direct (RSS-only affichait l'ID Plex brut) ([5a6013c](https://github.com/remi-deher/plex-rss/commit/5a6013caafcacb0e3a20082b9aae00585c7be8ce))
- resoudre les noms en direct dans le journal d'activite du dashboard ([adc8bfa](https://github.com/remi-deher/plex-rss/commit/adc8bfa5a3ffc7127eff8c4a3a551ed6264186c0))
- ruff format 5 fichiers + mypy cast sur sort key (api.py:838) ([3afeb6f](https://github.com/remi-deher/plex-rss/commit/3afeb6ffb89b5279f6a008cf8b6c59805a2c0d9d))

### 👷 CI/CD

- supprimer le push CHANGELOG vers main (bloque par branch protection) ([5ee8c0d](https://github.com/remi-deher/plex-rss/commit/5ee8c0dee1fb2f2b295bc7f489458e977504a883))
- restaurer le commit CHANGELOG vers main (bypass bot a configurer) ([8c840e2](https://github.com/remi-deher/plex-rss/commit/8c840e269bf6cc9b59a71b2658b4a02f7d4bf46d))
- relancer les github actions ([b085537](https://github.com/remi-deher/plex-rss/commit/b0855374ffdacf3c6d2d2968410afa8a3fc2b1fc))
- utiliser RELEASE_PAT pour le push CHANGELOG (bypass branch protection) ([0d2470c](https://github.com/remi-deher/plex-rss/commit/0d2470c08bdd420f08b21555633105699227bc84))
- revenir a GITHUB_TOKEN (branch protection desactivee) ([713571e](https://github.com/remi-deher/plex-rss/commit/713571e862b206b5c28d06124c46c644afbd4ecf))

### 📖 Documentation

- update CHANGELOG.md for v2.0.0 ([c52db22](https://github.com/remi-deher/plex-rss/commit/c52db22754c5f254da649dd109ba4c6c27f73bfd))

### ✨ Nouveautés

- security headers, login rate limiting, coverage, mypy, changelog ([775909a](https://github.com/remi-deher/plex-rss/commit/775909a0524a83005025b881b6617b2f2dfb19ed))
- release v2.0.0 - Seer integration, tvdb dedup and conflict management ([2a6e159](https://github.com/remi-deher/plex-rss/commit/2a6e159471712fd5ff483caa2eab8f7ff078654a))

### 🐛 Corrections

- migrate models to Mapped[T], fix UploadFile type in webhook — resolves 76 mypy errors ([645a338](https://github.com/remi-deher/plex-rss/commit/645a338b5363e2a8afcd7202f78dcf714671397c))
- ruff linting + couverture tests 60% ([5d291e9](https://github.com/remi-deher/plex-rss/commit/5d291e915ed56938df98bf41ae9cc235f75d5ab3))
- ruff format + couverture tests 60% ([70f2c2a](https://github.com/remi-deher/plex-rss/commit/70f2c2a47f3d234af6f85805a149731674d45ed2))
- guard null seer-loading element in loadSeerCells ([b2301f3](https://github.com/remi-deher/plex-rss/commit/b2301f35caf7b4f93ab09131bc46f28862d23f41))
- upgrade pip >= 26.1 (CVE-2026-6357, CVE-2026-3219, CVE-2025-8869, CVE-2026-1703) ([11eb626](https://github.com/remi-deher/plex-rss/commit/11eb6262623e0ff4d7a2ff9a7614a7a650add51a))
- upgrade pip then remove it post-install to eliminate pip CVEs ([76035b2](https://github.com/remi-deher/plex-rss/commit/76035b24ca90f4355c9fffce3191d0b86421d1ff))
- naive datetime for activity_log cutoff (500 on /api/activity) ([500e08d](https://github.com/remi-deher/plex-rss/commit/500e08d61a1879f8c8def887612836381ec2f5cc))
- restore bouton Sync Seer sur la page utilisateurs ([a73690f](https://github.com/remi-deher/plex-rss/commit/a73690f5af9f92a9d2b256e6bc80270ebd0e34ac))
- badge Hybride si seer_user_id lie, meme sans seer_active ([97ef6c0](https://github.com/remi-deher/plex-rss/commit/97ef6c018e4430566255e80be37057542871054e))
- badges Hybride/Seer/RSS corrects + boutons sync statuts dans parametres ([bc5c76b](https://github.com/remi-deher/plex-rss/commit/bc5c76b5af3fc721da35a82689c824fcaacd7811))

### 📖 Documentation

- update CHANGELOG.md for v2.0.0 ([929def2](https://github.com/remi-deher/plex-rss/commit/929def28c30991a8d5ef2f6abc56f99521b16332))
- update CHANGELOG.md for v2.0.0 ([83df62f](https://github.com/remi-deher/plex-rss/commit/83df62f8b084b580790f2e06e03bbb63fb70f86e))
- update CHANGELOG.md for v2.0.0 ([5a08f0d](https://github.com/remi-deher/plex-rss/commit/5a08f0d3a14b3a6b1733fb2e36d22300ac195f29))
- update CHANGELOG.md for v2.0.0 ([95800ef](https://github.com/remi-deher/plex-rss/commit/95800eff5df5d780a2e63df38f846edec15d1aaf))
- update CHANGELOG.md for v2.0.0 ([cf3cf62](https://github.com/remi-deher/plex-rss/commit/cf3cf62bb5e144ed9f55902d1e0655e300f708e4))
- update CHANGELOG.md for v2.0.0 ([db0a5a4](https://github.com/remi-deher/plex-rss/commit/db0a5a478c341a46e10022b2126dd0aaa597c7b5))
- update CHANGELOG.md for v2.0.0 ([8f21a7e](https://github.com/remi-deher/plex-rss/commit/8f21a7e79d201819ee3c783956475672ec931972))
- update CHANGELOG.md for v2.0.0 ([42fd37b](https://github.com/remi-deher/plex-rss/commit/42fd37b5263b2360b36771c727d8dcdd55255f74))
- update CHANGELOG.md for v2.0.0 ([8f89f06](https://github.com/remi-deher/plex-rss/commit/8f89f06f2eab1fa6cbe46ba6ae3e5276da01c75b))
- update CHANGELOG.md for v2.0.0 ([da68c81](https://github.com/remi-deher/plex-rss/commit/da68c81717e5bf3b4b47be8ea4aa9ba955b065a3))

### 🔧 Maintenance

- multi-stage Dockerfile, add .dockerignore ([fbb416d](https://github.com/remi-deher/plex-rss/commit/fbb416d6b96a2eb13d3f11512c343258a1d16764))

### build

- bump docker/setup-buildx-action from 3 to 4 (#12) ([2d698fa](https://github.com/remi-deher/plex-rss/commit/2d698faab420e966fae12688f756aaed532aec6d))
- bump sqlalchemy from 2.0.36 to 2.0.50 (#15) ([7cc84ce](https://github.com/remi-deher/plex-rss/commit/7cc84ce70be6473e49da061d7eafcf4853095eeb))
- bump dependabot/fetch-metadata from 2 to 3 (#14) ([b39398f](https://github.com/remi-deher/plex-rss/commit/b39398f7ffb7e79ecc9d4a5c900d512dac58a000))
- bump aiosmtplib from 3.0.2 to 5.1.1 (#19) ([4670540](https://github.com/remi-deher/plex-rss/commit/4670540b67d8500f4af217ef7aac3f654e4f0f89))
- bump python-multipart from 0.0.12 to 0.0.32 (#17) ([d577942](https://github.com/remi-deher/plex-rss/commit/d577942eacf4d0e78e9edd9626899f7b93180617))
- bump uvicorn from 0.30.6 to 0.49.0 (#18) ([f208d13](https://github.com/remi-deher/plex-rss/commit/f208d1313da26a1d1631d428c6398c2904d8057d))

### style

- run formatter and organize imports on codebase ([e64746a](https://github.com/remi-deher/plex-rss/commit/e64746a4c7c6f23d22ddba66da9d982046af1975))
- fix import order in metrics test ([8a7d427](https://github.com/remi-deher/plex-rss/commit/8a7d4273edb7bb170c8cedeba071d4ce0dd84e31))
- ruff format 6 files ([d5a4ef2](https://github.com/remi-deher/plex-rss/commit/d5a4ef28eb1bc85d43e5bc6548bf991d0ade7798))

### ✨ Nouveautés

- add secure authentication and initial setup wizard ([e817599](https://github.com/remi-deher/plex-rss/commit/e8175998e2f71e50a4af644334646dab53c0fb27))
- add GitHub and Docker Hub links to app layout and settings ([3e4fdc3](https://github.com/remi-deher/plex-rss/commit/3e4fdc3d735db26ab9719f848f52315dc0b29e4a))
- implement Plex SSO auth and fix settings reload after backup import ([21942f5](https://github.com/remi-deher/plex-rss/commit/21942f5da507decd577d9b81da0ba22fb6dce11d))
- integrate Overseerr support, logging viewer, and notification queue ([4855234](https://github.com/remi-deher/plex-rss/commit/48552346dd0464dba0ef22072f567c9163c5ef1a))
- setup GitHub Actions workflows for lint, release, security and automated Docker publish, and refine Plex SSO URL redirection ([a2c193e](https://github.com/remi-deher/plex-rss/commit/a2c193e2383734f674a9d869f58ab348dc04ba89))
- align check_connection method names, add integration tests and configure dependabot auto-merge workflow ([a03e286](https://github.com/remi-deher/plex-rss/commit/a03e2867ddc27a8243b07ba0e4a93fd0d84ef0a3))
- add tests for notification queue, api settings and plex_api; rename plex test_connection to check_connection ([2a35e30](https://github.com/remi-deher/plex-rss/commit/2a35e30485b2be53d9575d0817742448b75f4e27))
- add metrics support, contribution guidelines, and extend tests coverage ([1fcee3b](https://github.com/remi-deher/plex-rss/commit/1fcee3bf10827e74392f8bf32052fdfd23b35cac))
- publish to GHCR in addition to Docker Hub, add GHCR line in README ([b8bf318](https://github.com/remi-deher/plex-rss/commit/b8bf31833903c844272479fdd9e5e9e2fca94d77))

### 🐛 Corrections

- parse datetime strings on import and migrate to Plex OAuth v2 pins API to fix null pin_id ([114d478](https://github.com/remi-deher/plex-rss/commit/114d478511f6e4cf7d3612437e8f35a5a70415ec))
- enforce strict column type mapping for import to support SQLite type constraints ([695c215](https://github.com/remi-deher/plex-rss/commit/695c215d9b1b30d88e373170da2eb43b2c58ad2e))
- sort imports in test files to satisfy ruff I001 ([6a74dc4](https://github.com/remi-deher/plex-rss/commit/6a74dc4bb9d50b98da213237448bbeb5cdcaa16e))
- use pull_request_target for dependabot auto-merge permissions ([a56fecb](https://github.com/remi-deher/plex-rss/commit/a56fecbbbf9c44a8c12b89fc0e22057e307016af))
- update vulnerable dependencies and remove unused python-jose ([ee750e4](https://github.com/remi-deher/plex-rss/commit/ee750e40ec4960919bf1c258cab2c36fc1c06128))
- upgrade OS packages in Docker image and pin starlette to patched version ([c5f8748](https://github.com/remi-deher/plex-rss/commit/c5f8748a134a40f88a19ea004fc3c94c09d4d809))
- upgrade fastapi to 0.137.0, remove conflicting starlette pin ([676688f](https://github.com/remi-deher/plex-rss/commit/676688fd51be9d7d039b122fcc0a32fe062c79f4))
- switch base image to python:3.12-alpine to reduce OS CVE surface ([8c30985](https://github.com/remi-deher/plex-rss/commit/8c30985d9086e7af97b5ec1dc9ac91b25fd4d973))
- upgrade pip then remove it post-install to eliminate pip CVEs ([6f92641](https://github.com/remi-deher/plex-rss/commit/6f926415609414db09593522479936c439ac9e88))
- correct 4 bugs found in code review ([12a56b5](https://github.com/remi-deher/plex-rss/commit/12a56b55669b6b22a4c2eaeb821c8acb2fd9e0d6))
- update TemplateResponse calls for Starlette >=0.36, add HTML page tests ([d672985](https://github.com/remi-deher/plex-rss/commit/d67298562a71ef68f0e28f5435a6baf0d6394c37))

### 👷 CI/CD

- optimize dependabot auto-merge action permissions and token usage ([97d5f44](https://github.com/remi-deher/plex-rss/commit/97d5f44b659039b3e9f0fa053aa354309e7a9da0))
- add testing workflow for pytest ([5e88f68](https://github.com/remi-deher/plex-rss/commit/5e88f68b594c1dd926368a05bf760f4bfcb30437))
- trigger workflows to register status checks ([9b4d7d6](https://github.com/remi-deher/plex-rss/commit/9b4d7d67555a1a2c9a1742a4ad547b2230b3cd30))
- add workflow_dispatch trigger to Trivy scan ([665f2e5](https://github.com/remi-deher/plex-rss/commit/665f2e5b6dfb10a6145808503951c62473eab211))

### 📖 Documentation

- add badges and Docker Hub link to README ([3a61bcd](https://github.com/remi-deher/plex-rss/commit/3a61bcd0fde71a39fdf3c55cf7488d6f9f38a914))
- fix Docker image name in README compose example ([17625ec](https://github.com/remi-deher/plex-rss/commit/17625ec76c873834cdef250d9cd12ed9df69fb97))
- improve README styling and structure, add Docker Hub workflow and DOCKER_HUB.md description ([67ad552](https://github.com/remi-deher/plex-rss/commit/67ad552c73f29d9fe26eb190e083169c8ff47c5f))

### 🔧 Maintenance

- add v1 tag, versioned Docker image on tag, update README and CONTRIBUTING ([e88b9e4](https://github.com/remi-deher/plex-rss/commit/e88b9e41f350abe71cf2b209d01696b833d17c50))
