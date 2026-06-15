"""
Buffer mémoire circulaire pour les logs applicatifs.

Installe un handler Python logging qui conserve les MAX_LOGS dernières entrées
en mémoire. Utilisé par l'endpoint /api/logs pour afficher les logs dans l'UI.
"""

import logging
from collections import deque
from datetime import datetime, timezone

MAX_LOGS = 500

_buffer: deque = deque(maxlen=MAX_LOGS)

LEVEL_COLORS = {
    "DEBUG": "secondary",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "danger",
    "CRITICAL": "danger",
}


class MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            _buffer.append(
                {
                    "time": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "level": record.levelname,
                    "color": LEVEL_COLORS.get(record.levelname, "secondary"),
                    "logger": record.name,
                    "message": self.format(record) if record.exc_info else record.getMessage(),
                }
            )
        except Exception:
            pass


def get_logs() -> list[dict]:
    return list(reversed(_buffer))


def install():
    handler = MemoryLogHandler()
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
