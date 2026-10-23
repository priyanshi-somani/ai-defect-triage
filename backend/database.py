"""Database connection factory and SQLAlchemy session management."""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import settings

# Ensure data directory exists if using local sqlite file
if settings.DATABASE_URL.startswith("sqlite:///./data/"):
    os.makedirs("./data", exist_ok=True)

# Create engine
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

# Enable SQLite foreign key constraints
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency injection yield for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
