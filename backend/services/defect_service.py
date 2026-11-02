"""Defect domain service layer handling defect creation, persistence, updating, and audit logging."""

import logging
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.defect import Defect
from backend.models.history import DefectHistory
from backend.models.user import User
from backend.models.enums import UserRole, DefectStatus, DefectSeverity, DefectPriority, AuditActionType
from backend.schemas.defect import DefectCreate, DefectUpdate

logger = logging.getLogger("defect.service")


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
                status_code=status.HTTP_404_NOT_FOUND,
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
                    status_code=status.HTTP_403_FORBIDDEN,
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
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot update defect while in '{defect.status}' status. Updates only permitted in 'Open' status.",
                )

            # Restrict severity / priority alteration to QA_TRIAGE and ADMIN roles
            if request.severity is not None and request.severity.value != defect.severity:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles may change defect severity.",
                )
            if request.priority is not None and request.priority.value != defect.priority:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
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
