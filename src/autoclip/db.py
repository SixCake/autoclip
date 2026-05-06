"""SQLite engine, Session factory, and DB init helpers.

Design notes (per design.md §6 / §16.5):
- check_same_thread=False: required for multiprocessing pipeline workers
- foreign_keys ON pragma: enforced via event listener (SQLite default is OFF)
- in-memory StaticPool factory provided for fast unit tests
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings
from .models import Base

# ---------------------------------------------------------------------------
# Engine factories
# ---------------------------------------------------------------------------

def _attach_fk_pragma(engine: Engine) -> None:
    """Enable SQLite foreign_keys (OFF by default in SQLite)."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app_engine(db_path: Path | None = None) -> Engine:
    """Create the production SQLite engine backing one DB file.

    Default path: `<settings.data_dir>/autoclip.db`.
    """
    settings = get_settings()
    if db_path is None:
        db_path = settings.data_dir / "autoclip.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = f"sqlite:///{db_path}"
    engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},  # multiprocessing safe
        future=True,
    )
    _attach_fk_pragma(engine)
    return engine


def create_memory_engine() -> Engine:
    """Create an in-memory SQLite engine for unit tests.

    StaticPool ensures a single connection is shared so all sessions see
    the same in-memory DB.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    _attach_fk_pragma(engine)
    return engine


# ---------------------------------------------------------------------------
# Session factory + helpers
# ---------------------------------------------------------------------------

def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a sessionmaker bound to the given engine."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def init_db(engine: Engine) -> None:
    """Create all tables. Idempotent."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop all tables. Idempotent. Used by tests."""
    Base.metadata.drop_all(engine)
