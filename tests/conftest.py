"""Pytest configuration, database fixtures, and test authentication helpers."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.models  # Ensures all ORM models are registered on Base.metadata
from backend.main import app
from backend.database import Base, get_db
from backend.models.user import User
from backend.models.enums import UserRole
from backend.security import hash_password, create_access_token

# Isolated in-memory SQLite database for test suites
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables in memory before tests and drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Provide a transactional database session rolled back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    """Provide a FastAPI TestClient with overridden database session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session):
    """Factory fixture for creating persistent test users."""
    def _make_user(
        username: str = "testuser",
        email: str = None,
        password: str = "Password123!",
        role: UserRole = UserRole.REPORTER,
        is_active: bool = True
    ) -> User:
        user = User(
            username=username,
            email=email or f"{username}@example.com",
            password_hash=hash_password(password),
            role=role.value if isinstance(role, UserRole) else str(role),
            is_active=is_active
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make_user


@pytest.fixture
def auth_headers():
    """Factory fixture generating HTTP Authorization bearer headers for a user."""
    def _auth_headers(user: User) -> dict:
        token = create_access_token(data={"sub": user.username, "role": user.role, "user_id": user.id})
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers
