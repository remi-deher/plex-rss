"""Garde-fou : tout type d'évènement publié doit être déclaré dans `EVENT_TYPES`.

`app.realtime.publish` lève `ValueError` sur un type inconnu. Un appel oublié dans cette
liste ne se voit qu'à l'exécution, sur le chemin qui l'emprunte — celui de l'import complet
faisait échouer en 500 une migration qui avait pourtant réussi.
"""

import ast
import re
from pathlib import Path

from app.realtime import EVENT_TYPES

APP_ROOT = Path(__file__).resolve().parent.parent / "app"


def _published_event_types() -> set[str]:
    """Types passés en littéral à un appel `publish(...)` quelque part dans `app/`.

    L'AST est préféré à un grep : il ignore les mentions en commentaire ou en docstring,
    et ne retient que le premier argument positionnel d'un véritable appel.
    """
    found: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "publish":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def test_every_published_event_type_is_declared():
    published = _published_event_types()
    # Garde-fou du garde-fou : si l'extraction ne trouve plus rien, le test ne prouve rien.
    assert published, "aucun appel publish() détecté — l'extraction AST est à revoir"
    assert published <= EVENT_TYPES, (
        f"types publiés mais absents de EVENT_TYPES : {sorted(published - EVENT_TYPES)}"
    )


def test_spa_listens_to_every_declared_event_type():
    """La liste côté navigateur doit couvrir `EVENT_TYPES` : un type déclaré côté serveur
    mais absent de `frontend/src/events.js` n'est jamais reçu, l'évènement part dans le
    vide sans erreur nulle part."""
    events_js = (APP_ROOT.parent / "frontend" / "src" / "events.js").read_text(encoding="utf-8")
    declaration = re.search(r"const TYPES = \[(.*?)\];", events_js, re.S)
    assert declaration, "déclaration `const TYPES = [...]` introuvable dans events.js"
    listened = set(re.findall(r'"([^"]+)"', declaration.group(1)))

    assert EVENT_TYPES <= listened, (
        f"types déclarés mais non écoutés par la SPA : {sorted(EVENT_TYPES - listened)}"
    )
