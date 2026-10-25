"""Authentication and RBAC Endpoint Tests (TC-AUTH-001, TC-AUTH-010, Registration & Login)."""

import pytest
from backend.models.enums import UserRole


def test_user_registration_success(client):
    """Verify registration succeeds for all supported roles."""
    roles = [
        ("reporter_user", "reporter@example.com", UserRole.REPORTER),
        ("dev_user", "dev@example.com", UserRole.DEVELOPER),
        ("qa_user", "qa@example.com", UserRole.QA_TRIAGE),
        ("admin_user", "admin@example.com", UserRole.ADMIN),
    ]

    for username, email, role in roles:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": email,
                "password": "SecurePassword123!",
                "role": role.value
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == username
        assert data["email"] == email
        assert data["role"] == role.value
        assert data["is_active"] is True
        assert "password_hash" not in data


def test_registration_duplicate_username_rejected(client, make_user):
    """Verify duplicate username returns HTTP 409 Conflict."""
    make_user(username="duplicate_alice", email="alice1@example.com")

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "duplicate_alice",
            "email": "alice2@example.com",
            "password": "Password123!",
            "role": UserRole.REPORTER.value
        }
    )
    assert response.status_code == 409
    assert "already taken" in response.json()["detail"]


def test_registration_duplicate_email_rejected(client, make_user):
    """Verify duplicate email returns HTTP 409 Conflict."""
    make_user(username="bob_user", email="common@example.com")

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "charlie_user",
            "email": "common@example.com",
            "password": "Password123!",
            "role": UserRole.REPORTER.value
        }
    )
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_registration_short_password_rejected(client):
    """Verify password shorter than 8 characters is rejected with HTTP 422."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "shortpass_user",
            "email": "short@example.com",
            "password": "pass7",
            "role": UserRole.REPORTER.value
        }
    )
    assert response.status_code == 422


def test_user_login_success(client, make_user):
    """Verify valid login returns signed JWT bearer token and user data."""
    make_user(username="valid_login_user", password="CorrectPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "valid_login_user",
            "password": "CorrectPassword123!"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in_seconds"] > 0
    assert data["user"]["username"] == "valid_login_user"


def test_login_invalid_password_rejected(client, make_user):
    """Verify login with incorrect password returns HTTP 401."""
    make_user(username="password_check_user", password="ActualPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "password_check_user",
            "password": "WrongPassword999!"
        }
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


def test_login_nonexistent_user_rejected(client):
    """Verify login with non-existent username returns HTTP 401."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "ghost_user",
            "password": "SomePassword123!"
        }
    )
    assert response.status_code == 401


def test_login_inactive_user_rejected(client, make_user):
    """Verify inactive user login is rejected with HTTP 403."""
    make_user(username="inactive_user", password="Password123!", is_active=False)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "inactive_user",
            "password": "Password123!"
        }
    )
    assert response.status_code == 403
    assert "Account is inactive" in response.json()["detail"]


def test_get_current_user_profile(client, make_user, auth_headers):
    """Verify GET /api/v1/auth/me returns authenticated user representation."""
    user = make_user(username="profile_user", role=UserRole.DEVELOPER)
    headers = auth_headers(user)

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "profile_user"
    assert data["role"] == UserRole.DEVELOPER.value


def test_tc_auth_001_reporter_permitted_access(client, make_user, auth_headers):
    """TC-AUTH-001: Reporter possesses valid authentication and can access base profile."""
    reporter = make_user(username="reporter_alpha", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == UserRole.REPORTER.value


def test_tc_auth_010_unauthorized_role_rejected(client, make_user, auth_headers):
    """TC-AUTH-010: Unauthorized role operations return HTTP 403 Forbidden with security logging."""
    reporter = make_user(username="reporter_beta", role=UserRole.REPORTER)
    developer = make_user(username="developer_beta", role=UserRole.DEVELOPER)
    qa_user = make_user(username="qa_beta", role=UserRole.QA_TRIAGE)
    admin_user = make_user(username="admin_beta", role=UserRole.ADMIN)

    # Reporter denied admin-only route
    res_rep_admin = client.get("/api/v1/auth/admin-only", headers=auth_headers(reporter))
    assert res_rep_admin.status_code == 403
    assert "Operation not permitted" in res_rep_admin.json()["detail"]

    # Developer denied admin-only route
    res_dev_admin = client.get("/api/v1/auth/admin-only", headers=auth_headers(developer))
    assert res_dev_admin.status_code == 403

    # Reporter denied triage-only route
    res_rep_triage = client.get("/api/v1/auth/triage-only", headers=auth_headers(reporter))
    assert res_rep_triage.status_code == 403

    # Developer denied triage-only route
    res_dev_triage = client.get("/api/v1/auth/triage-only", headers=auth_headers(developer))
    assert res_dev_triage.status_code == 403

    # QA permitted triage-only route
    res_qa_triage = client.get("/api/v1/auth/triage-only", headers=auth_headers(qa_user))
    assert res_qa_triage.status_code == 200

    # Admin permitted both routes
    res_adm_admin = client.get("/api/v1/auth/admin-only", headers=auth_headers(admin_user))
    assert res_adm_admin.status_code == 200
    res_adm_triage = client.get("/api/v1/auth/triage-only", headers=auth_headers(admin_user))
    assert res_adm_triage.status_code == 200
