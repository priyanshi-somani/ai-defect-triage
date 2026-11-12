"""Defect management API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth_deps import get_current_user, require_roles
from backend.models.user import User
from backend.models.enums import UserRole
from backend.schemas.defect import (
    DefectCreate,
    DefectUpdate,
    DefectResponse,
    DefectTriageRequest,
    EvidenceValidationResponse,
)
from backend.services.defect_service import DefectService
from backend.services.evidence_validation_service import EvidenceValidationService

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


@router.put(
    "/{defect_id}",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update defect details",
)
def update_defect(
    defect_id: str,
    request: DefectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update defect details with author governance and status gating.
    
    Requirements Addressed:
        FR-006: Author can update Title, Description, Steps, Expected, Actual, Environment while in 'Open' status.
        FR-007: Non-author update attempt rejected with HTTP 403 Forbidden.
        FR-008: Author update attempt past 'Open' status rejected with HTTP 403 Forbidden.
    """
    return DefectService.update_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/triage",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Triage defect through deterministic evidence quality gate",
)
def triage_defect(
    defect_id: str,
    request: Optional[DefectTriageRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Transition defect from Open to Triaged upon passing deterministic evidence quality gate.

    Requirements Addressed:
        FR-011: Complete deterministic evidence quality evaluation.
        FR-012: Steps to Reproduce >= 2 numbered steps and >= 20 chars.
        FR-013: Expected and Actual results >= 10 chars each and non-identical.
        FR-014: Environment specifies target OS, client/browser version, and tier.
        FR-015: Reject transitions with HTTP 422 itemized error array.
        FR-016: Retain defect in Open status on failure.
        FR-032: Permitted only for ROLE_QA_TRIAGE or ROLE_ADMIN.
    """
    return DefectService.triage_defect(
        db=db,
        defect_id=defect_id,
        current_user=current_user,
        request=request,
    )


@router.get(
    "/{defect_id}/validate-evidence",
    response_model=EvidenceValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect defect evidence quality without state mutation",
)
def inspect_defect_evidence(
    defect_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Inspect defect evidence completeness against quality gates without state transition.

    Requirements Addressed:
        FR-011: Evidence quality gate evaluation.
        FR-032: Authorized for QA/Triage and Admin.
    """
    defect = DefectService.get_defect_by_id(db, defect_id)
    if not defect:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Defect '{defect_id}' not found.",
        )
    result = EvidenceValidationService.evaluate_evidence(defect)
    return EvidenceValidationResponse(
        is_valid=result.is_valid,
        errors=result.errors,
    )

