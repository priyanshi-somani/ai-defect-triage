"""Defect management API endpoints."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth_deps import get_current_user, require_roles
from backend.models.user import User
from backend.models.enums import UserRole
from backend.schemas.defect import (
    DefectCreate,
    DefectUpdate,
    DefectResponse,
    DefectHistoryResponse,
    PaginatedDefectResponse,
    DefectTriageRequest,
    EvidenceValidationResponse,
    DefectTransitionRequest,
    DefectAssignRequest,
    DefectResolveRequest,
    DefectCloseRequest,
    DefectReopenRequest,
)
from backend.services.defect_service import DefectService
from backend.services.evidence_validation_service import EvidenceValidationService
from backend.services.workflow_service import WorkflowService

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
    "",
    response_model=PaginatedDefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Search, filter, sort, and paginate defects",
)
def list_defects(
    id: Optional[str] = Query(default=None, description="Exact Defect ID to filter by"),
    defect_id: Optional[str] = Query(default=None, description="Exact Defect ID to filter by"),
    q: Optional[str] = Query(default=None, description="Case-insensitive substring search in Title and Description"),
    keyword: Optional[str] = Query(default=None, description="Alias for keyword substring search"),
    search: Optional[str] = Query(default=None, description="Alias for keyword substring search"),
    status: Optional[str] = Query(default=None, description="Filter by defect status"),
    severity: Optional[str] = Query(default=None, description="Filter by defect severity"),
    priority: Optional[str] = Query(default=None, description="Filter by defect priority"),
    module: Optional[str] = Query(default=None, description="Filter by defect module"),
    assignee_id: Optional[int] = Query(default=None, description="Filter by assignee user ID"),
    reporter_id: Optional[int] = Query(default=None, description="Filter by reporter user ID"),
    created_after: Optional[datetime] = Query(default=None, description="Filter defects created on or after date"),
    created_before: Optional[datetime] = Query(default=None, description="Filter defects created on or before date"),
    created_from: Optional[datetime] = Query(default=None, description="Alias for created_after"),
    created_to: Optional[datetime] = Query(default=None, description="Alias for created_before"),
    page: int = Query(default=1, ge=1, description="Page number (1-based index)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size (max 100)"),
    sort_by: Optional[str] = Query(default="created_at", description="Field to sort by: created_at, updated_at, severity, priority"),
    sort_order: Optional[str] = Query(default="desc", description="Sort order: asc, desc"),
    sort: Optional[str] = Query(default=None, description="Sort expression: e.g. 'created_at DESC, severity ASC'"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve paginated, filtered, and sorted defect reports.

    Requirements Addressed:
        FR-041: Exact Defect ID search and case-insensitive Title/Description substring search.
        FR-042: Compound multi-attribute filtering by Status, Severity, Priority, Module, Assignee, Reporter, and Creation Date Range.
        FR-043: Paginated responses with default page size of 20 and customizable page size up to 100 records.
        FR-044: Sorting by created_at, updated_at, severity, and priority in ascending or descending order.
        OP_VIEW_DEFECT: Accessible by all authenticated roles (Reporter, Developer, QA/Triage, Admin).
    """
    target_id = id or defect_id
    search_query = q or keyword or search
    start_date = created_after or created_from
    end_date = created_before or created_to

    items, total, total_pages = DefectService.search_defects(
        db=db,
        defect_id=target_id,
        q=search_query,
        status_filter=status,
        severity=severity,
        priority=priority,
        module=module,
        assignee_id=assignee_id,
        reporter_id=reporter_id,
        created_after=start_date,
        created_before=end_date,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        sort=sort,
    )

    return PaginatedDefectResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        defects=items,
    )


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


@router.get(
    "/{defect_id}/history",
    response_model=List[DefectHistoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological audit history for a defect",
)
def get_defect_history(
    defect_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve chronological audit trail of all mutations to the specified defect.

    Requirements Addressed:
        FR-049: Audit log tracking status transitions, assignments, and field edits.
        FR-050: Itemized audit log entry attributes.
        FR-051: Chronological history access open to all authenticated roles.
        OP_VIEW_AUDIT_LOG: Permitted for Reporter, Developer, QA/Triage, and Admin.
    """
    return DefectService.get_defect_history(db=db, defect_id=defect_id)


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


# ==============================================================================
# FSM Lifecycle Workflow State Transitions (FR-021 through FR-030)
# ==============================================================================

@router.post(
    "/{defect_id}/transition",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute finite-state machine lifecycle transition",
)
def transition_defect(
    defect_id: str,
    request: DefectTransitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a validated finite-state machine state transition.

    Requirements Addressed:
        FR-021: Enforce finite-state machine transitions.
        FR-022: Reject Open -> Closed (HTTP 400).
        FR-023: Reject Triaged -> In Progress without assignee (HTTP 422).
        FR-024: Require resolution details for Fixed (HTTP 422).
        FR-025: Reject Fixed -> Closed (HTTP 400).
        FR-026: Require verification notes for Closed (HTTP 422).
        FR-027: Require reopen reason for Retest -> Reopened (HTTP 422).
        FR-028: Permit Closed -> Reopened with regression notes (HTTP 422).
        FR-029: Permit Assigned -> Triaged (unassigned).
        FR-030: Reject illegal transitions (HTTP 400).
    """
    return WorkflowService.transition_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/assign",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign defect to developer",
)
def assign_defect(
    defect_id: str,
    request: DefectAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.DEVELOPER, UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Assign a defect to a designated developer (FR-033)."""
    return WorkflowService.assign_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/start-progress",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Commence active investigation/remediation",
)
def start_progress(
    defect_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.DEVELOPER, UserRole.ADMIN])),
):
    """Transition defect status to 'In Progress' (FR-034)."""
    return WorkflowService.start_progress(
        db=db,
        defect_id=defect_id,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/resolve",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve defect and mark Fixed",
)
def resolve_defect(
    defect_id: str,
    request: DefectResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.DEVELOPER, UserRole.ADMIN])),
):
    """Transition defect status to 'Fixed' with resolution details (FR-024, FR-034)."""
    return WorkflowService.resolve_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/retest",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Begin QA retest verification",
)
def start_retest(
    defect_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Transition defect status to 'Retest' (FR-035)."""
    return WorkflowService.start_retest(
        db=db,
        defect_id=defect_id,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/close",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Close verified defect",
)
def close_defect(
    defect_id: str,
    request: DefectCloseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Transition defect status to 'Closed' with verification notes (FR-026, FR-035, FR-036)."""
    return WorkflowService.close_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{defect_id}/reopen",
    response_model=DefectResponse,
    status_code=status.HTTP_200_OK,
    summary="Reopen defect after retest failure or regression",
)
def reopen_defect(
    defect_id: str,
    request: DefectReopenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN])),
):
    """Transition defect status to 'Reopened' with failure explanation (FR-027, FR-028, FR-036)."""
    return WorkflowService.reopen_defect(
        db=db,
        defect_id=defect_id,
        request=request,
        current_user=current_user,
    )


