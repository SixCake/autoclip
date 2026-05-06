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
    """Create all tables. Idempotent.

    Also performs lightweight schema upgrade for existing SQLite files:
    detects new nullable columns declared on ORM models and ALTER TABLE
    ADD COLUMN them when missing. This avoids needing Alembic for the
    MVP's nullable-only forward-compat additions.
    """
    Base.metadata.create_all(engine)
    _auto_add_missing_nullable_columns(engine)


def _auto_add_missing_nullable_columns(engine: Engine) -> None:
    """For each ORM table, ALTER TABLE ADD COLUMN any nullable column
    declared on the model but missing in the live DB.

    SQLite supports ADD COLUMN (with NULL default) since 3.2; safe for
    nullable forward-compat additions only. Refuses non-nullable adds.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # create_all just made it; columns are in sync
            live_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in live_cols:
                    continue
                if not col.nullable:
                    # Refuse silent non-null add — would break inserts on old rows
                    continue
                col_type_sql = col.type.compile(dialect=engine.dialect)
                conn.execute(text(
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type_sql}'
                ))


def drop_all(engine: Engine) -> None:
    """Drop all tables. Idempotent. Used by tests."""
    Base.metadata.drop_all(engine)
