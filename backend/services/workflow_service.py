"""Defect Lifecycle Finite-State Machine (FSM) Workflow Service.

Enforces deterministic state transitions, mandatory pre-conditions,
and immutable audit logging across the 8-state defect lifecycle.

Requirements Addressed:
- FR-021: Enforce finite-state machine transitions specified in docs/defect-workflow.md
- FR-022: Reject direct transition from Open to Closed (HTTP 400 Bad Request)
- FR-023: Reject transition from Triaged to In Progress without assignee (HTTP 422)
- FR-024: Require resolution_notes, root_cause, and fix_reference for Fixed (HTTP 422)
- FR-025: Reject direct transition from Fixed to Closed bypassing Retest (HTTP 400 Bad Request)
- FR-026: Require verification_notes (min 15 chars) to transition from Retest to Closed
- FR-027: Require reopen_reason (min 20 chars) and increment reopen_count on Retest -> Reopened
- FR-028: Permit Closed to Reopened with regression notes (min 20 chars) and increment reopen_count
- FR-029: Permit Assigned defect to return to Triaged (clearing assignee)
- FR-030: Reject all undefined or illegal transitions with HTTP 400 Bad Request
"""

import logging
from typing import Dict, Set, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.defect import Defect
from backend.models.history import DefectHistory
from backend.models.user import User
from backend.models.enums import (
    DefectStatus,
    AuditActionType,
)
from backend.schemas.defect import (
    DefectTransitionRequest,
    DefectAssignRequest,
    DefectResolveRequest,
    DefectCloseRequest,
    DefectReopenRequest,
)
from backend.services.evidence_validation_service import EvidenceValidationService

logger = logging.getLogger("workflow.service")


class WorkflowService:
    """Finite-state machine workflow engine governing defect lifecycle transitions."""

    # Formal 8-state transition matrix from docs/defect-workflow.md Section 5
    VALID_TRANSITIONS: Dict[str, Set[str]] = {
        DefectStatus.OPEN.value: {
            DefectStatus.TRIAGED.value,
        },
        DefectStatus.TRIAGED.value: {
            DefectStatus.ASSIGNED.value,
            DefectStatus.OPEN.value,
            DefectStatus.IN_PROGRESS.value,
        },
        DefectStatus.ASSIGNED.value: {
            DefectStatus.IN_PROGRESS.value,
            DefectStatus.TRIAGED.value,
        },
        DefectStatus.IN_PROGRESS.value: {
            DefectStatus.FIXED.value,
            DefectStatus.ASSIGNED.value,
        },
        DefectStatus.FIXED.value: {
            DefectStatus.RETEST.value,
        },
        DefectStatus.RETEST.value: {
            DefectStatus.CLOSED.value,
            DefectStatus.REOPENED.value,
        },
        DefectStatus.CLOSED.value: {
            DefectStatus.REOPENED.value,
        },
        DefectStatus.REOPENED.value: {
            DefectStatus.ASSIGNED.value,
            DefectStatus.IN_PROGRESS.value,
        },
    }

    @classmethod
    def is_transition_permitted(cls, from_status: str, to_status: str) -> bool:
        """Evaluate whether a state transition is topologically valid within the FSM."""
        allowed = cls.VALID_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    @classmethod
    def transition_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectTransitionRequest,
        current_user: User,
    ) -> Defect:
        """Execute a state machine transition with mandatory pre-conditions and audit trail.

        Requirements Addressed:
            FR-021: Enforce finite-state machine transitions.
            FR-022: Reject Open -> Closed (HTTP 400).
            FR-023: Reject Triaged -> In Progress without assignee (HTTP 422).
            FR-024: Require resolution details for Fixed (HTTP 422).
            FR-025: Reject Fixed -> Closed (HTTP 400).
            FR-026: Require verification notes for Closed (HTTP 422).
            FR-027: Require reopen reason and increment reopen_count for Retest -> Reopened.
            FR-028: Permit Closed -> Reopened with regression notes.
            FR-029: Permit Assigned -> Triaged (clearing assignee).
            FR-030: Reject undefined or illegal transitions with HTTP 400.
        """
        defect = db.query(Defect).filter(Defect.id == defect_id).first()
        if not defect:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Defect '{defect_id}' not found.",
            )

        old_status = defect.status
        target_status = (
            request.target_status.value
            if isinstance(request.target_status, DefectStatus)
            else str(request.target_status)
        )

        # Idempotent no-op check: if already in target status, return defect
        if old_status == target_status:
            return defect

        # ----------------------------------------------------------------------
        # 1. Validate Legal FSM Transition Topology (FR-021, FR-022, FR-025, FR-030)
        # ----------------------------------------------------------------------
        if old_status == DefectStatus.OPEN.value and target_status == DefectStatus.CLOSED.value:
            logger.warning(
                "ILLEGAL_TRANSITION: Attempted direct closure from 'Open' on defect '%s'",
                defect.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transition directly from 'Open' to 'Closed'. Direct closure bypassing triage and retest is strictly forbidden.",
            )

        if old_status == DefectStatus.FIXED.value and target_status == DefectStatus.CLOSED.value:
            logger.warning(
                "ILLEGAL_TRANSITION: Attempted direct closure from 'Fixed' on defect '%s' bypassing Retest",
                defect.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transition directly from 'Fixed' to 'Closed'. Retest is mandatory. Fixed defects cannot bypass Retest.",
            )

        if not cls.is_transition_permitted(old_status, target_status):
            allowed = sorted(list(cls.VALID_TRANSITIONS.get(old_status, set())))
            logger.warning(
                "ILLEGAL_TRANSITION: Defect '%s' invalid transition '%s' -> '%s' (allowed: %s)",
                defect.id,
                old_status,
                target_status,
                allowed,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal state transition from '{old_status}' to '{target_status}'. Permitted target statuses: {allowed}.",
            )

        old_assignee_id = defect.assignee_id

        # ----------------------------------------------------------------------
        # 2. Evaluate Specific Pre-Conditions for Each Target State
        # ----------------------------------------------------------------------

        # Target: TRIAGED
        if target_status == DefectStatus.TRIAGED.value:
            if old_status == DefectStatus.OPEN.value:
                # Evidence Quality Gate evaluation (FR-011 through FR-016)
                EvidenceValidationService.validate_or_raise(defect)
            elif old_status == DefectStatus.ASSIGNED.value:
                # Assigned returned to triage queue (FR-029)
                defect.assignee_id = None

        # Target: ASSIGNED
        elif target_status == DefectStatus.ASSIGNED.value:
            assignee_id = request.assignee_id
            if assignee_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot transition to 'Assigned' status without specifying a valid 'assignee_id'.",
                )
            assignee = db.query(User).filter(User.id == assignee_id).first()
            if not assignee:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Assignee user with ID {assignee_id} not found.",
                )
            if not assignee.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot assign defect to an inactive user account.",
                )
            defect.assignee_id = assignee.id

        # Target: IN_PROGRESS (FR-023)
        elif target_status == DefectStatus.IN_PROGRESS.value:
            if request.assignee_id is not None:
                assignee = db.query(User).filter(User.id == request.assignee_id).first()
                if not assignee:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Assignee user with ID {request.assignee_id} not found.",
                    )
                if not assignee.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot assign defect to an inactive user account.",
                    )
                defect.assignee_id = assignee.id

            if defect.assignee_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot transition to 'In Progress' without an assigned developer. Assignee is mandatory.",
                )

        # Target: FIXED (FR-024)
        elif target_status == DefectStatus.FIXED.value:
            root_cause = (request.root_cause or defect.root_cause or "").strip()
            resolution_notes = (request.resolution_notes or defect.resolution_notes or "").strip()
            fix_reference = (request.fix_reference or defect.fix_reference or "").strip()

            missing_details = []
            if not root_cause:
                missing_details.append("root_cause")
            if not resolution_notes:
                missing_details.append("resolution_notes")
            if not fix_reference:
                missing_details.append("fix_reference")

            if missing_details:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot mark defect as Fixed without mandatory resolution details: {', '.join(missing_details)}.",
                )

            defect.root_cause = root_cause
            defect.resolution_notes = resolution_notes
            defect.fix_reference = fix_reference

        # Target: RETEST
        elif target_status == DefectStatus.RETEST.value:
            pass

        # Target: CLOSED (FR-026)
        elif target_status == DefectStatus.CLOSED.value:
            verification_notes = (request.verification_notes or defect.verification_notes or "").strip()
            if not verification_notes or len(verification_notes) < 15:
                raise HTTPException(
                    status_code=422,
                    detail="Verification notes are mandatory to close a defect and must be at least 15 characters in length.",
                )
            defect.verification_notes = verification_notes

        # Target: REOPENED (FR-027, FR-028)
        elif target_status == DefectStatus.REOPENED.value:
            reopen_reason = (request.reopen_reason or defect.reopen_reason or "").strip()
            if not reopen_reason or len(reopen_reason) < 20:
                raise HTTPException(
                    status_code=422,
                    detail="Reopen reason is mandatory to reopen a defect and must be at least 20 characters in length.",
                )
            defect.reopen_reason = reopen_reason
            defect.reopen_count += 1

        # ----------------------------------------------------------------------
        # 3. Apply Status Mutation & Atomic Audit Log Persistence
        # ----------------------------------------------------------------------
        defect.status = target_status
        db.flush()  # Increments defect.version via SQLAlchemy version_id_col

        # Status change audit event
        action_type = (
            AuditActionType.REOPENED.value
            if target_status == DefectStatus.REOPENED.value
            else AuditActionType.STATUS_CHANGED.value
        )
        status_history = DefectHistory(
            defect_id=defect.id,
            changed_by_user_id=current_user.id,
            action_type=action_type,
            field_name="status",
            old_value=old_status,
            new_value=target_status,
            version_snapshot=defect.version,
        )
        db.add(status_history)

        # Assignee change audit event (if assignee was mutated)
        if old_assignee_id != defect.assignee_id:
            assign_history = DefectHistory(
                defect_id=defect.id,
                changed_by_user_id=current_user.id,
                action_type=AuditActionType.ASSIGNED.value,
                field_name="assignee_id",
                old_value=str(old_assignee_id) if old_assignee_id is not None else None,
                new_value=str(defect.assignee_id) if defect.assignee_id is not None else None,
                version_snapshot=defect.version,
            )
            db.add(assign_history)

        db.commit()
        db.refresh(defect)

        logger.info(
            "DEFECT_TRANSITION: Defect '%s' transitioned '%s' -> '%s' by user '%s' (version=%d)",
            defect.id,
            old_status,
            target_status,
            current_user.username,
            defect.version,
        )
        return defect

    @classmethod
    def assign_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectAssignRequest,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'Assigned'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.ASSIGNED,
            assignee_id=request.assignee_id,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)

    @classmethod
    def start_progress(
        cls,
        db: Session,
        defect_id: str,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'In Progress'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.IN_PROGRESS,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)

    @classmethod
    def resolve_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectResolveRequest,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'Fixed'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.FIXED,
            root_cause=request.root_cause,
            resolution_notes=request.resolution_notes,
            fix_reference=request.fix_reference,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)

    @classmethod
    def start_retest(
        cls,
        db: Session,
        defect_id: str,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'Retest'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.RETEST,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)

    @classmethod
    def close_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectCloseRequest,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'Closed'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.CLOSED,
            verification_notes=request.verification_notes,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)

    @classmethod
    def reopen_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectReopenRequest,
        current_user: User,
    ) -> Defect:
        """Convenience method to transition a defect to 'Reopened'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.REOPENED,
            reopen_reason=request.reopen_reason,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user)
