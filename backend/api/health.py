"""Health check endpoint."""

from fastapi import APIRouter
from backend.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health():
    """Verify application health and build version."""
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }
