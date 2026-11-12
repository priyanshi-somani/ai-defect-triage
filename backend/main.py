"""FastAPI Application Entrypoint."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.api import health, auth, defects
from backend.services.evidence_validation_service import EvidenceQualityError

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


@app.exception_handler(EvidenceQualityError)
async def evidence_quality_error_handler(request: Request, exc: EvidenceQualityError):
    """Handle deterministic evidence quality gate failures with structured 422 payload."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.errors,
            "errors": exc.errors,
            "message": "Defect evidence quality validation failed.",
        },
    )



@app.get("/")
def root():
    """Root endpoint redirecting to documentation / health check."""
    return {
        "message": "AI-Assisted Bug Triage & Defect Management System API",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health"
    }
