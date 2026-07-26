"""Etat partage entre l'ingestion des webhooks et leur diagnostic.

Les handlers d'ingestion (webhook.py) horodatent ici l'evenement "Test" recu de Sonarr,
Radarr ou Plex ; les endpoints de diagnostic (webhook_admin.py) le relisent pour afficher
"dernier test recu il y a X". En memoire seulement : reinitialise au redemarrage, ce qui
est le comportement voulu -- un test recu avant un redemarrage ne prouve rien sur la
configuration courante.
"""

from datetime import datetime

last_webhook_test: dict[str, datetime | None] = {"sonarr": None, "radarr": None, "plex": None}
