"""Test-only helpers for code paths migrated to SQLAlchemy AsyncSession."""

from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


class _AwaitableValue:
    def __init__(self, value: Any = None):
        self.value = value

    def __await__(self):
        async def _resolve():
            return self.value

        return _resolve().__await__()


class TestSession:
    """Expose a synchronous SQLite session through the AsyncSession protocol.

    FastAPI's TestClient runs the application in another event loop while many
    historical tests prepare and inspect data synchronously. This adapter keeps
    that setup ergonomic without restoring synchronous database APIs in app code.
    """

    __test__ = False

    def __init__(self, session: Session, dispose: Callable[[], None] | None = None):
        self.sync_session = session
        self._dispose = dispose

    def __getattr__(self, name: str):
        return getattr(self.sync_session, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def execute(self, *args, **kwargs):
        return _AwaitableValue(self.sync_session.execute(*args, **kwargs))

    def get(self, *args, **kwargs):
        return _AwaitableValue(self.sync_session.get(*args, **kwargs))

    def begin_nested(self):
        return _AsyncTransactionContext(self.sync_session.begin_nested())

    def commit(self):
        self.sync_session.commit()
        return _AwaitableValue()

    def rollback(self):
        self.sync_session.rollback()
        return _AwaitableValue()

    def flush(self):
        self.sync_session.flush()
        return _AwaitableValue()

    def refresh(self, instance, *args, **kwargs):
        self.sync_session.refresh(instance, *args, **kwargs)
        return _AwaitableValue()

    def delete(self, instance):
        self.sync_session.delete(instance)
        return _AwaitableValue()

    def close(self):
        self.sync_session.close()
        if self._dispose:
            self._dispose()
            self._dispose = None
        return _AwaitableValue()


class AsyncSessionContext:
    """Async context manager returning a test session without owning it."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _AsyncTransactionContext:
    def __init__(self, transaction):
        self.transaction = transaction

    async def __aenter__(self):
        return self.transaction.__enter__()

    async def __aexit__(self, exc_type, exc, traceback):
        return self.transaction.__exit__(exc_type, exc, traceback)


def make_test_session() -> TestSession:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return TestSession(session, engine.dispose)
