"""Defect domain service layer handling defect creation, persistence, updating, and audit logging."""

import logging
from datetime import datetime
from typing import Optional, List, Tuple
from fastapi import HTTPException, status as http_status
from sqlalchemy import or_, func, case
from sqlalchemy.orm import Session

from backend.models.defect import Defect
from backend.models.history import DefectHistory
from backend.models.user import User
from backend.models.enums import UserRole, DefectStatus, DefectSeverity, DefectPriority, AuditActionType
from backend.schemas.defect import DefectCreate, DefectUpdate, DefectTriageRequest
from backend.services.evidence_validation_service import EvidenceValidationService

logger = logging.getLogger("defect.service")

STATUS_MAP = {
    "open": DefectStatus.OPEN.value,
    "triaged": DefectStatus.TRIAGED.value,
    "assigned": DefectStatus.ASSIGNED.value,
    "in progress": DefectStatus.IN_PROGRESS.value,
    "in_progress": DefectStatus.IN_PROGRESS.value,
    "fixed": DefectStatus.FIXED.value,
    "retest": DefectStatus.RETEST.value,
    "closed": DefectStatus.CLOSED.value,
    "reopened": DefectStatus.REOPENED.value,
}

SEVERITY_MAP = {
    "blocker": DefectSeverity.BLOCKER.value,
    "critical": DefectSeverity.CRITICAL.value,
    "major": DefectSeverity.MAJOR.value,
    "minor": DefectSeverity.MINOR.value,
    "trivial": DefectSeverity.TRIVIAL.value,
}

PRIORITY_MAP = {
    "p1": DefectPriority.P1.value,
    "p1-immediate": DefectPriority.P1.value,
    "p2": DefectPriority.P2.value,
    "p2-high": DefectPriority.P2.value,
    "p3": DefectPriority.P3.value,
    "p3-medium": DefectPriority.P3.value,
    "p4": DefectPriority.P4.value,
    "p4-low": DefectPriority.P4.value,
}

SUPPORTED_SORT_FIELDS = {"created_at", "updated_at", "severity", "priority", "id"}


class DefectService:
    """Service managing defect lifecycle operations, sequencing, and audit history."""

    @staticmethod
    def generate_next_defect_id(db: Session) -> str:
        """Generate sequential Defect ID formatted as DEF-XXXX (starting at DEF-1001).
        
        Requirements:
            FR-004: Unique non-repeating identifier in sequential DEF-1001 format.
        """
        defect_ids = db.query(Defect.id).filter(Defect.id.like("DEF-%")).all()
        if not defect_ids:
            return "DEF-1001"

        max_num = 1000
        for (d_id,) in defect_ids:
            try:
                num = int(d_id.split("-", 1)[1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                continue

        return f"DEF-{max_num + 1}"

    @staticmethod
    def create_defect(db: Session, request: DefectCreate, current_user: User) -> Defect:
        """Create a new defect record and initial audit history entry atomically.
        
        Requirements:
            FR-001: Defect creation by authenticated users with standard domain fields.
            FR-004: Auto-assign sequential ID, created_at, and reporter_id.
            FR-005: Initialize status to 'Open' and version to 1.
            FR-009: Severity enum validation.
            FR-010: Priority enum validation.
        """
        defect_id = DefectService.generate_next_defect_id(db)

        severity_val = (
            request.severity.value
            if isinstance(request.severity, DefectSeverity)
            else str(request.severity)
        )
        priority_val = (
            request.priority.value
            if isinstance(request.priority, DefectPriority)
            else str(request.priority)
        )

        defect = Defect(
            id=defect_id,
            title=request.title,
            description=request.description,
            steps_to_reproduce=request.steps_to_reproduce,
            expected_result=request.expected_result,
            actual_result=request.actual_result,
            environment=request.environment,
            module=request.module,
            severity=severity_val,
            priority=priority_val,
            status=DefectStatus.OPEN.value,
            reporter_id=current_user.id,
            version=1,
        )
        db.add(defect)
        db.flush()

        # Write initial immutable audit history entry
        history = DefectHistory(
            defect_id=defect.id,
            changed_by_user_id=current_user.id,
            action_type=AuditActionType.CREATED.value,
            field_name=None,
            old_value=None,
            new_value=DefectStatus.OPEN.value,
            version_snapshot=1,
        )
        db.add(history)
        db.commit()
        db.refresh(defect)

        logger.info(
            "DEFECT_CREATED: Defect '%s' created by user '%s' (id=%d)",
            defect.id,
            current_user.username,
            current_user.id,
        )
        return defect

    @staticmethod
    def update_defect(
        db: Session,
        defect_id: str,
        request: DefectUpdate,
        current_user: User,
    ) -> Defect:
        """Update an existing defect report with author governance and status checks.
        
        Requirements:
            FR-006: Author can update Title, Description, Steps, Expected, Actual, Environment while in 'Open' status.
            FR-007: Non-author update attempt rejected with HTTP 403 Forbidden.
            FR-008: Author update attempt past 'Open' status rejected with HTTP 403 Forbidden.
        """
        defect = db.query(Defect).filter(Defect.id == defect_id).first()
        if not defect:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Defect '{defect_id}' not found.",
            )

        # Authorization check per RBAC policy (roles-permissions.md):
        # Reporters and Developers are restricted to editing their own defects while in Open status.
        if current_user.role in [UserRole.REPORTER.value, UserRole.DEVELOPER.value]:
            if defect.reporter_id != current_user.id:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) attempted to update defect '%s' reported by user_id %d",
                    current_user.username,
                    current_user.role,
                    defect.id,
                    defect.reporter_id,
                )
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Cannot update a defect reported by another user.",
                )

            if defect.status != DefectStatus.OPEN.value:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' attempted to update defect '%s' currently in status '%s'",
                    current_user.username,
                    defect.id,
                    defect.status,
                )
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot update defect while in '{defect.status}' status. Updates only permitted in 'Open' status.",
                )

            # Restrict severity / priority alteration to QA_TRIAGE and ADMIN roles
            if request.severity is not None and request.severity.value != defect.severity:
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles may change defect severity.",
                )
            if request.priority is not None and request.priority.value != defect.priority:
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles may change defect priority.",
                )

        # Track field deltas
        updatable_fields = [
            "title",
            "description",
            "steps_to_reproduce",
            "expected_result",
            "actual_result",
            "environment",
            "module",
            "severity",
            "priority",
        ]

        deltas = []
        for field in updatable_fields:
            val = getattr(request, field)
            if val is not None:
                new_val_str = val.value if hasattr(val, "value") else str(val)
                old_val_str = getattr(defect, field)
                if old_val_str != new_val_str:
                    deltas.append((field, old_val_str, new_val_str))
                    setattr(defect, field, new_val_str)

        if deltas:
            db.flush()  # Increments defect.version via version_id_col
            for field, old_v, new_v in deltas:
                history = DefectHistory(
                    defect_id=defect.id,
                    changed_by_user_id=current_user.id,
                    action_type=AuditActionType.UPDATED.value,
                    field_name=field,
                    old_value=old_v,
                    new_value=new_v,
                    version_snapshot=defect.version,
                )
                db.add(history)
            db.commit()
            db.refresh(defect)
            logger.info(
                "DEFECT_UPDATED: Defect '%s' updated by user '%s' (version=%d, changes=%d)",
                defect.id,
                current_user.username,
                defect.version,
                len(deltas),
            )

        return defect

    @staticmethod
    def get_defect_by_id(db: Session, defect_id: str) -> Optional[Defect]:
        """Retrieve a defect by its unique identifier."""
        return db.query(Defect).filter(Defect.id == defect_id).first()

    @staticmethod
    def triage_defect(
        db: Session,
        defect_id: str,
        current_user: User,
        request: Optional[DefectTriageRequest] = None,
    ) -> Defect:
        """Evaluate defect evidence and transition status from Open to Triaged.

        Requirements:
            FR-011: Evaluate defect evidence completeness against quality gates.
            FR-012: Steps to Reproduce >= 2 numbered steps and >= 20 chars.
            FR-013: Expected and Actual results >= 10 chars each and non-identical.
            FR-014: Environment specifies target OS, client/browser version, and deployment environment.
            FR-015: Reject with HTTP 422 itemized error array on failure.
            FR-016: Defect retained in Open status until resolved.
            FR-032: Permitted only for ROLE_QA_TRIAGE or ROLE_ADMIN.
        """
        defect = db.query(Defect).filter(Defect.id == defect_id).first()
        if not defect:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Defect '{defect_id}' not found.",
            )

        if defect.status != DefectStatus.OPEN.value:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot triage defect currently in '{defect.status}' status. Only defects in 'Open' status can be triaged.",
            )

        # Validate evidence through the deterministic Evidence Quality Gate (FR-011 - FR-016)
        EvidenceValidationService.validate_or_raise(defect)

        old_status = defect.status
        defect.status = DefectStatus.TRIAGED.value

        deltas = [("status", old_status, defect.status)]

        if request:
            if request.severity is not None and request.severity.value != defect.severity:
                deltas.append(("severity", defect.severity, request.severity.value))
                defect.severity = request.severity.value
            if request.priority is not None and request.priority.value != defect.priority:
                deltas.append(("priority", defect.priority, request.priority.value))
                defect.priority = request.priority.value

        db.flush()  # Increments version via version_id_col

        for field, old_v, new_v in deltas:
            history = DefectHistory(
                defect_id=defect.id,
                changed_by_user_id=current_user.id,
                action_type=AuditActionType.STATUS_CHANGED.value if field == "status" else AuditActionType.UPDATED.value,
                field_name=field,
                old_value=old_v,
                new_value=new_v,
                version_snapshot=defect.version,
            )
            db.add(history)

        db.commit()
        db.refresh(defect)

        logger.info(
            "DEFECT_TRIAGED: Defect '%s' successfully promoted to 'Triaged' by user '%s' (version=%d)",
            defect.id,
            current_user.username,
            defect.version,
        )
        return defect

    @staticmethod
    def search_defects(
        db: Session,
        defect_id: Optional[str] = None,
        q: Optional[str] = None,
        status_filter: Optional[str] = None,
        severity: Optional[str] = None,
        priority: Optional[str] = None,
        module: Optional[str] = None,
        assignee_id: Optional[int] = None,
        reporter_id: Optional[int] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
        sort: Optional[str] = None,
    ) -> Tuple[List[Defect], int, int]:
        """Query, filter, sort, and paginate defects deterministically.

        Requirements Addressed:
            FR-041: Search by exact Defect ID and case-insensitive substring match on Title and Description.
            FR-042: Compound multi-attribute filtering by Status, Severity, Priority, Module, Assignee, Reporter, and Creation Date Range.
            FR-043: Paginate results with default page size 20, max 100.
            FR-044: Sorting by created_at, updated_at, severity, priority in ascending or descending order.
        """
        query = db.query(Defect)

        # FR-041: Search by exact Defect ID
        if defect_id and defect_id.strip():
            query = query.filter(Defect.id == defect_id.strip())

        # FR-041: Case-insensitive substring match on Title and Description
        if q and q.strip():
            term = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Defect.id.ilike(term),
                    Defect.title.ilike(term),
                    Defect.description.ilike(term),
                )
            )

        # FR-042: Multi-attribute compound filtering
        if status_filter and status_filter.strip():
            status_val = STATUS_MAP.get(status_filter.strip().lower(), status_filter.strip())
            query = query.filter(Defect.status == status_val)

        if severity and severity.strip():
            severity_val = SEVERITY_MAP.get(severity.strip().lower(), severity.strip())
            query = query.filter(Defect.severity == severity_val)

        if priority and priority.strip():
            priority_val = PRIORITY_MAP.get(priority.strip().lower(), priority.strip())
            query = query.filter(Defect.priority == priority_val)

        if module and module.strip():
            query = query.filter(func.lower(Defect.module) == module.strip().lower())

        if assignee_id is not None:
            query = query.filter(Defect.assignee_id == assignee_id)

        if reporter_id is not None:
            query = query.filter(Defect.reporter_id == reporter_id)

        if created_after is not None:
            if created_after.tzinfo is not None:
                created_after = created_after.replace(tzinfo=None)
            query = query.filter(Defect.created_at >= created_after)

        if created_before is not None:
            if created_before.tzinfo is not None:
                created_before = created_before.replace(tzinfo=None)
            query = query.filter(Defect.created_at <= created_before)

        # Compute total before pagination
        total = query.count()

        # FR-044: Sorting
        sort_clauses = []
        if sort and sort.strip():
            raw_clauses = [c.strip() for c in sort.split(",") if c.strip()]
            for raw_c in raw_clauses:
                if ":" in raw_c:
                    parts = raw_c.split(":", 1)
                else:
                    parts = raw_c.split()
                f_name = parts[0].strip().lower()
                f_order = parts[1].strip().lower() if len(parts) > 1 else "asc"
                if f_name not in SUPPORTED_SORT_FIELDS:
                    raise HTTPException(
                        status_code=http_status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid sort field '{f_name}'. Supported fields: created_at, updated_at, severity, priority.",
                    )
                if f_order not in {"asc", "desc"}:
                    raise HTTPException(
                        status_code=http_status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid sort order '{f_order}'. Supported orders: asc, desc.",
                    )
                sort_clauses.append((f_name, f_order))
        else:
            f_name = (sort_by or "created_at").strip().lower()
            f_order = (sort_order or "desc").strip().lower()
            if f_name not in SUPPORTED_SORT_FIELDS:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid sort field '{f_name}'. Supported fields: created_at, updated_at, severity, priority.",
                )
            if f_order not in {"asc", "desc"}:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid sort order '{f_order}'. Supported orders: asc, desc.",
                )
            sort_clauses.append((f_name, f_order))

        order_by_items = []
        for f_name, f_order in sort_clauses:
            if f_name == "created_at":
                col = Defect.created_at
            elif f_name == "updated_at":
                col = Defect.updated_at
            elif f_name == "severity":
                col = case(
                    {
                        DefectSeverity.BLOCKER.value: 1,
                        DefectSeverity.CRITICAL.value: 2,
                        DefectSeverity.MAJOR.value: 3,
                        DefectSeverity.MINOR.value: 4,
                        DefectSeverity.TRIVIAL.value: 5,
                    },
                    value=Defect.severity,
                    else_=6,
                )
            elif f_name == "priority":
                col = case(
                    {
                        DefectPriority.P1.value: 1,
                        DefectPriority.P2.value: 2,
                        DefectPriority.P3.value: 3,
                        DefectPriority.P4.value: 4,
                    },
                    value=Defect.priority,
                    else_=5,
                )
            elif f_name == "id":
                col = Defect.id

            order_by_items.append(col.asc() if f_order == "asc" else col.desc())

        # Deterministic secondary tie-breaker
        order_by_items.append(Defect.id.desc())
        query = query.order_by(*order_by_items)

        # FR-043: Pagination boundaries
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size

        items = query.offset(offset).limit(page_size).all()
        return items, total, total_pages

