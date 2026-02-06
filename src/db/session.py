"""Database session management and initialization.

Handles engine creation, table creation, and session lifecycle.
Configures SQLite with WAL mode for better write concurrency.
"""

from contextlib import contextmanager
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from src.config.settings import get_settings
from src.db.models import Base


def create_engine_from_settings() -> Engine:
    """Create SQLAlchemy engine from settings with SQLite optimizations.

    Configures:
    - WAL (Write-Ahead Logging) mode for better concurrency
    - Foreign key constraints enforcement
    - Creates parent directory for database file if needed

    Returns:
        Configured SQLAlchemy engine
    """
    settings = get_settings()
    database_url = settings.database_url

    # Create parent directory for SQLite database if needed
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Database directory ensured: {db_file.parent}")

    # Create engine
    engine = create_engine(database_url, echo=False)

    # Configure SQLite for better performance and data integrity
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite pragmas on each connection."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    logger.info(f"Database engine created: {database_url}")
    return engine


def create_tables(engine: Engine) -> None:
    """Create all tables defined in models.

    Args:
        engine: SQLAlchemy engine
    """
    Base.metadata.create_all(engine)
    logger.info("Database tables created")


def get_session_factory(engine: Engine) -> sessionmaker:
    """Create session factory bound to engine.

    Args:
        engine: SQLAlchemy engine

    Returns:
        Session factory (sessionmaker)
    """
    return sessionmaker(bind=engine)


@contextmanager
def get_session(session_factory: sessionmaker):
    """Context manager for database sessions.

    Handles commit on success, rollback on exception.

    Args:
        session_factory: Session factory from get_session_factory

    Yields:
        SQLAlchemy Session instance

    Example:
        with get_session(session_factory) as session:
            session.add(trade)
            # Commits automatically on success
            # Rolls back on exception
    """
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Session rollback due to error: {e}")
        raise
    finally:
        session.close()


def init_db():
    """Initialize database: create engine, tables, and return session factory.

    This is the main entry point for database setup.

    Returns:
        Tuple of (engine, session_factory)

    Example:
        engine, SessionFactory = init_db()
        with get_session(SessionFactory) as session:
            session.query(Market).all()
    """
    engine = create_engine_from_settings()
    create_tables(engine)
    session_factory = get_session_factory(engine)
    logger.info("Database initialized successfully")
    return engine, session_factory
