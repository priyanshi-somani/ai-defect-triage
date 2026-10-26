"""User SQLAlchemy ORM entity."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from backend.database import Base
from backend.models.enums import UserRole


class User(Base):
    """User database entity representing system actors and credentials."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default=UserRole.REPORTER.value)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<User id={self.id} username='{self.username}' role='{self.role}'>"
