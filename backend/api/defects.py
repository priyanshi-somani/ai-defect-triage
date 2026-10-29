"""Defect management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth_deps import get_current_user
from backend.models.user import User
from backend.schemas.defect import DefectCreate, DefectResponse
from backend.services.defect_service import DefectService

router = APIRouter(prefix="/defects", tags=["defects"])


@router.post(
    "",
    response_model=DefectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new defect report",
)
def create_defect(
    request: DefectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new defect report with input validation and initial audit trail.
    
    Requirements Addressed:
        FR-001: Authenticated submission (Reporter, Developer, QA, Admin).
        FR-002: Title boundary validation (10-120 chars, non-empty, non-numeric).
        FR-003: Description boundary validation (minimum 30 chars).
        FR-004: Sequential ID assignment (DEF-1001 sequence), reporter_id, created_at.
        FR-005: Status initialized to 'Open', version initialized to 1.
        FR-009: Severity enum validation.
        FR-010: Priority enum validation.
    """
    return DefectService.create_defect(db=db, request=request, current_user=current_user)


@router.get(
    "/{defect_id}",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve defect by ID",
)
def get_defect(
    defect_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve defect representation by unique ID.
    
    Requirements Addressed:
        FR-001: Defect inspection.
        TC-DEF-010: Defect persistence and retrieval consistency.
    """
    defect = DefectService.get_defect_by_id(db, defect_id)
    if not defect:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Defect '{defect_id}' not found.",
        )
    return defect
