"""FastAPI Application Entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.api import health, auth, defects

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-Assisted Bug Triage & Defect Management System (CISC 594 - Version 1.0 Baseline)",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(defects.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    """Root endpoint redirecting to documentation / health check."""
    return {
        "message": "AI-Assisted Bug Triage & Defect Management System API",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health"
    }
