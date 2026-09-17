"""PostgreSQL connection for persisted inspections.

The URL comes from ``DATABASE_URL`` (default: the local ``metriq`` database over
the Unix socket). The engine is created lazily, so the rest of the API — search,
Q&A, OCR, analysis — still starts and works when no database is running; only
the ``/inspections`` endpoints need it.

The schema is owned by Alembic migrations (``backend/migrations``), never by
``create_all``:

    cd backend
    ./.venv/bin/alembic upgrade head
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg:///metriq"


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
