"""Liste tous les endpoints montés, pour vérifier la parité de routes après refactorisation.

Usage: python scripts/dump_routes.py > /tmp/routes_before.json
Les routers sont montés via un wrapper `_IncludedRouter` (routage priorisé) qui n'expose
pas `.routes` : on repart donc des routers d'origine.
"""

import json

from app.main import app


def endpoints() -> list[list]:
    found = set()
    for route in app.routes:
        router = getattr(route, "original_router", None)
        targets = router.routes if router is not None else [route]
        for sub in targets:
            if hasattr(sub, "methods") and hasattr(sub, "path"):
                found.add((sub.path, tuple(sorted(sub.methods))))
    return sorted([path, list(methods)] for path, methods in found)


if __name__ == "__main__":
    print(json.dumps(endpoints(), indent=0))
