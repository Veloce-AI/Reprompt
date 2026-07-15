"""Database engine/session setup.

Reads DATABASE_URL from the environment. Defaults to a local SQLite file so
M1.3 development and tests don't depend on docker-compose/Postgres being up.
Models are written to be Postgres-compatible (see models.py) — swapping
DATABASE_URL to a postgresql+psycopg:// URL is the only change needed later.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

# SQLite needs check_same_thread=False for use across FastAPI's threadpool;
# this is a no-op for other dialects.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
