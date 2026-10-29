"""Defect domain service layer handling defect creation, persistence, and audit logging."""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from backend.models.defect import Defect
from backend.models.history import DefectHistory
from backend.models.user import User
from backend.models.enums import DefectStatus, DefectSeverity, DefectPriority, AuditActionType
from backend.schemas.defect import DefectCreate

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
    def get_defect_by_id(db: Session, defect_id: str) -> Optional[Defect]:
        """Retrieve a defect by its unique identifier."""
        return db.query(Defect).filter(Defect.id == defect_id).first()
