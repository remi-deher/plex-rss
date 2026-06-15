

### ✨ Nouveautés

- security headers, login rate limiting, coverage, mypy, changelog ([775909a](https://github.com/remi-deher/plex-rss/commit/775909a0524a83005025b881b6617b2f2dfb19ed))
- release v2.0.0 - Seer integration, tvdb dedup and conflict management ([2a6e159](https://github.com/remi-deher/plex-rss/commit/2a6e159471712fd5ff483caa2eab8f7ff078654a))

### 🐛 Corrections

- migrate models to Mapped[T], fix UploadFile type in webhook — resolves 76 mypy errors ([645a338](https://github.com/remi-deher/plex-rss/commit/645a338b5363e2a8afcd7202f78dcf714671397c))
- ruff linting + couverture tests 60% ([5d291e9](https://github.com/remi-deher/plex-rss/commit/5d291e915ed56938df98bf41ae9cc235f75d5ab3))
- ruff format + couverture tests 60% ([70f2c2a](https://github.com/remi-deher/plex-rss/commit/70f2c2a47f3d234af6f85805a149731674d45ed2))

### 📖 Documentation

- update CHANGELOG.md for v2.0.0 ([929def2](https://github.com/remi-deher/plex-rss/commit/929def28c30991a8d5ef2f6abc56f99521b16332))
- update CHANGELOG.md for v2.0.0 ([83df62f](https://github.com/remi-deher/plex-rss/commit/83df62f8b084b580790f2e06e03bbb63fb70f86e))

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
