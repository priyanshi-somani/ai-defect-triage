"""Tests for application health check and baseline gateway."""

def test_health_check(client):
    """Verify GET /api/v1/health returns HTTP 200 and healthy status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0-dev"
    assert data["environment"] == "development"


def test_root_endpoint(client):
    """Verify root / endpoint returns operational documentation metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "AI-Assisted Bug Triage" in data["message"]
    assert data["docs"] == "/docs"
    assert data["health"] == "/api/v1/health"
