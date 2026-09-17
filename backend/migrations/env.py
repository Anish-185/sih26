"""Alembic environment: the URL comes from DATABASE_URL (app.db.database_url)."""

from alembic import context
from sqlalchemy import create_engine

from app import records  # noqa: F401 — registers the models on Base.metadata
from app.db import Base, database_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
