"""Security and Cryptographic Verification Tests (TC-SEC-001 through TC-SEC-003)."""

import pytest
from backend.security import hash_password, verify_password, create_access_token, decode_access_token
from backend.models.enums import UserRole


def test_tc_sec_001_unauthenticated_request_rejected(client):
    """TC-SEC-001: Unauthenticated requests to protected endpoints return HTTP 401."""
    # Attempting to access protected profile endpoint without Authorization header
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"] == "Bearer"

    # Attempting to access with invalid/malformed bearer token
    response_invalid = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.token.payload"}
    )
    assert response_invalid.status_code == 401


def test_tc_sec_002_password_hashing_algorithm(db_session, make_user):
    """TC-SEC-002: Verify salted BCrypt hashing and confirm plaintext is never stored."""
    plaintext_password = "MySuperSecretPassword2026!"
    hashed = hash_password(plaintext_password)

    # BCrypt identifier prefix check ($2b$ with work factor 12)
    assert hashed.startswith("$2b$12$")
    assert hashed != plaintext_password

    # Verification function checks
    assert verify_password(plaintext_password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False

    # Verify database persistence stores only the hash
    user = make_user(username="hashcheck_user", email="hash@example.com", password=plaintext_password)
    assert user.password_hash.startswith("$2b$12$")
    assert plaintext_password not in user.password_hash


def test_tc_sec_003_input_sanitization_and_validation(client):
    """TC-SEC-003: Rejection of malformed, script-injected, or XSS payloads in auth fields."""
    # Attempt to inject XSS into username
    payload_xss_username = {
        "username": "<script>alert('xss')</script>",
        "email": "xss@example.com",
        "password": "ValidPassword123!",
        "role": UserRole.REPORTER.value
    }
    response = client.post("/api/v1/auth/register", json=payload_xss_username)
    assert response.status_code == 422  # Fails regex pattern validator

    # Attempt to inject invalid email
    payload_bad_email = {
        "username": "valid_user",
        "email": "not-an-email-address",
        "password": "ValidPassword123!",
        "role": UserRole.REPORTER.value
    }
    response_email = client.post("/api/v1/auth/register", json=payload_bad_email)
    assert response_email.status_code == 422


def test_token_expiration_and_tampering():
    """Verify that tampered tokens or invalid signatures fail to decode."""
    token = create_access_token(data={"sub": "alice", "role": "ROLE_REPORTER"})
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["sub"] == "alice"

    # Tamper with token characters
    tampered_token = token[:-4] + "xxxx"
    assert decode_access_token(tampered_token) is None
