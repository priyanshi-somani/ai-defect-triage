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
from sqlalchemy.orm.exc import StaleDataError

from backend.models.defect import Defect
from backend.models.history import DefectHistory
from backend.models.user import User
from backend.models.enums import (
    DefectStatus,
    AuditActionType,
    UserRole,
)
from backend.schemas.defect import (
    DefectResponse,
    DefectTransitionRequest,
    DefectAssignRequest,
    DefectResolveRequest,
    DefectCloseRequest,
    DefectReopenRequest,
)
from backend.services.defect_service import ConcurrencyConflictError
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
            DefectStatus.ASSIGNED.value,
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
    def _user_resolved_defect(cls, db: Session, defect: Defect, user_id: int) -> bool:
        """Check if user resolved this defect or was the assigned developer when marked Fixed."""
        # Check if the user is the assigned developer on a defect in Fixed or Retest
        if defect.assignee_id is not None and defect.assignee_id == user_id:
            return True

        # Check most recent transition to Fixed in defect history
        last_fixed = (
            db.query(DefectHistory)
            .filter(
                DefectHistory.defect_id == defect.id,
                DefectHistory.field_name == "status",
                DefectHistory.new_value == DefectStatus.FIXED.value,
            )
            .order_by(DefectHistory.timestamp.desc(), DefectHistory.id.desc())
            .first()
        )
        if last_fixed and last_fixed.changed_by_user_id == user_id:
            return True

        return False

    @classmethod
    def validate_transition_authorization(
        cls,
        db: Session,
        defect: Defect,
        old_status: str,
        target_status: str,
        current_user: User,
        request: DefectTransitionRequest,
    ) -> None:
        """Enforce Role-Based Access Control and Separation of Duties (FR-031 through FR-037)."""
        role = current_user.role

        # ----------------------------------------------------------------------
        # Target: TRIAGED
        # ----------------------------------------------------------------------
        if target_status == DefectStatus.TRIAGED.value:
            if old_status == DefectStatus.OPEN.value:
                # OP_TRIAGE_DEFECT: Only QA_TRIAGE and ADMIN (FR-032)
                if role not in [UserRole.QA_TRIAGE.value, UserRole.ADMIN.value]:
                    logger.warning(
                        "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to triage defect '%s'",
                        current_user.username,
                        role,
                        defect.id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only QA/Triage or Admin roles are authorized to triage defects.",
                    )
            elif old_status == DefectStatus.ASSIGNED.value:
                # Return to triage queue (FR-029): Only QA_TRIAGE and ADMIN
                if role not in [UserRole.QA_TRIAGE.value, UserRole.ADMIN.value]:
                    logger.warning(
                        "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to return defect '%s' to triage",
                        current_user.username,
                        role,
                        defect.id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only QA/Triage or Admin roles are authorized to return assigned defects to the triage queue.",
                    )

        # ----------------------------------------------------------------------
        # Target: OPEN
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.OPEN.value:
            # Returning to Open from Triaged: Only QA_TRIAGE and ADMIN
            if role not in [UserRole.QA_TRIAGE.value, UserRole.ADMIN.value]:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to move defect '%s' to Open",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles are authorized to return defects to Open status.",
                )

        # ----------------------------------------------------------------------
        # Target: ASSIGNED (OP_ASSIGN_DEFECT)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.ASSIGNED.value:
            if old_status == DefectStatus.IN_PROGRESS.value:
                # Pausing progress: designated assignee or Admin
                if role == UserRole.ADMIN.value:
                    pass
                elif role == UserRole.DEVELOPER.value:
                    if defect.assignee_id != current_user.id:
                        logger.warning(
                            "SECURITY_VIOLATION: Developer '%s' unauthorized to pause defect '%s' assigned to %s",
                            current_user.username,
                            defect.id,
                            defect.assignee_id,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the designated assigned developer or an Admin is authorized to pause progress on this defect.",
                        )
                else:
                    logger.warning(
                        "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to pause defect '%s'",
                        current_user.username,
                        role,
                        defect.id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the designated assigned developer or an Admin is authorized to pause progress on this defect.",
                    )
            else:
                # Standard assignment/reassignment (FR-033)
                if role == UserRole.REPORTER.value:
                    logger.warning(
                        "SECURITY_VIOLATION: Reporter '%s' attempted to assign defect '%s'",
                        current_user.username,
                        defect.id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Reporters are not authorized to assign or reassign defects.",
                    )
                elif role == UserRole.DEVELOPER.value:
                    # Developer self-assignment vs. reassignment
                    if defect.assignee_id is not None:
                        logger.warning(
                            "SECURITY_VIOLATION: Developer '%s' attempted to reassign already-assigned defect '%s'",
                            current_user.username,
                            defect.id,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Developers are not permitted to reassign defects. Reassignment is restricted to QA/Triage and Admin roles.",
                        )
                    if old_status != DefectStatus.TRIAGED.value:
                        logger.warning(
                            "SECURITY_VIOLATION: Developer '%s' attempted to self-assign defect '%s' in status '%s'",
                            current_user.username,
                            defect.id,
                            old_status,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Developers may only self-assign unassigned defects that are in 'Triaged' status.",
                        )
                    if request.assignee_id is not None and request.assignee_id != current_user.id:
                        logger.warning(
                            "SECURITY_VIOLATION: Developer '%s' attempted to assign defect '%s' to user %d",
                            current_user.username,
                            defect.id,
                            request.assignee_id,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Developers may only self-assign defects. Assigning defects to other users is restricted to QA/Triage and Admin roles.",
                        )
                # QA_TRIAGE and ADMIN are allowed to assign/reassign

        # ----------------------------------------------------------------------
        # Target: IN_PROGRESS (OP_START_PROGRESS, FR-034)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.IN_PROGRESS.value:
            if role == UserRole.ADMIN.value:
                pass  # Admin override permitted
            elif role == UserRole.DEVELOPER.value:
                if defect.assignee_id is not None and defect.assignee_id != current_user.id:
                    logger.warning(
                        "SECURITY_VIOLATION: Developer '%s' attempted to start progress on defect '%s' assigned to %d",
                        current_user.username,
                        defect.id,
                        defect.assignee_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the designated assigned developer or an Admin is authorized to start progress on this defect.",
                    )
                if old_status == DefectStatus.TRIAGED.value:
                    if request.assignee_id is not None and request.assignee_id != current_user.id:
                        logger.warning(
                            "SECURITY_VIOLATION: Developer '%s' attempted to start progress on defect '%s' with assignee %d",
                            current_user.username,
                            defect.id,
                            request.assignee_id,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Developers may only start progress on defects assigned to themselves.",
                        )
            else:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to start progress on defect '%s'",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the designated assigned developer or an Admin is authorized to start progress on this defect.",
                )

        # ----------------------------------------------------------------------
        # Target: FIXED (OP_RESOLVE_DEFECT, FR-034)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.FIXED.value:
            if role == UserRole.ADMIN.value:
                pass  # Admin override permitted
            elif role == UserRole.DEVELOPER.value:
                if defect.assignee_id != current_user.id:
                    logger.warning(
                        "SECURITY_VIOLATION: Developer '%s' attempted to resolve defect '%s' assigned to %s",
                        current_user.username,
                        defect.id,
                        defect.assignee_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the designated assigned developer or an Admin is authorized to mark this defect as Fixed.",
                    )
            else:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to resolve defect '%s'",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the designated assigned developer or an Admin is authorized to mark this defect as Fixed.",
                )

        # ----------------------------------------------------------------------
        # Target: RETEST (OP_RETEST_DEFECT, FR-035)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.RETEST.value:
            if role in [UserRole.REPORTER.value, UserRole.DEVELOPER.value]:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to retest defect '%s'",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles are authorized to initiate retest verification on a defect.",
                )
            # Strict Separation of Duties (FR-035): Developer who fixed cannot retest
            if cls._user_resolved_defect(db, defect, current_user.id):
                logger.warning(
                    "SEPARATION_OF_DUTIES_VIOLATION: User '%s' attempted to retest defect '%s' which they resolved",
                    current_user.username,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Separation of duties violation: The user who resolved this defect cannot retest it. Independent QA verification is required.",
                )

        # ----------------------------------------------------------------------
        # Target: CLOSED (OP_CLOSE_DEFECT, FR-035, FR-036)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.CLOSED.value:
            if role in [UserRole.REPORTER.value, UserRole.DEVELOPER.value]:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to close defect '%s'",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles are authorized to close defects. Developers and Reporters are forbidden from defect closure.",
                )
            # Strict Separation of Duties (FR-035): Developer who fixed cannot close
            if cls._user_resolved_defect(db, defect, current_user.id):
                logger.warning(
                    "SEPARATION_OF_DUTIES_VIOLATION: User '%s' attempted to close defect '%s' which they resolved",
                    current_user.username,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Separation of duties violation: The user who resolved this defect cannot close it. Independent QA verification is required.",
                )

        # ----------------------------------------------------------------------
        # Target: REOPENED (OP_REOPEN_DEFECT, FR-036)
        # ----------------------------------------------------------------------
        elif target_status == DefectStatus.REOPENED.value:
            if role not in [UserRole.QA_TRIAGE.value, UserRole.ADMIN.value]:
                logger.warning(
                    "SECURITY_VIOLATION: User '%s' (role: %s) unauthorized to reopen defect '%s'",
                    current_user.username,
                    role,
                    defect.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only QA/Triage or Admin roles are authorized to reopen defects.",
                )

    @classmethod
    def transition_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectTransitionRequest,
        current_user: User,
        if_match: Optional[str] = None,
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
            FR-056–FR-060: Optimistic concurrency control and stale transition rejection.
        """
        defect = db.query(Defect).filter(Defect.id == defect_id).first()
        if not defect:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Defect '{defect_id}' not found.",
            )

        # Concurrency version validation (FR-056 through FR-060)
        submitted_version = None
        if request and request.version is not None:
            submitted_version = request.version
        elif if_match is not None:
            clean = if_match.strip().strip('"').strip("'")
            if clean.startswith("W/"):
                clean = clean[2:].strip('"')
            try:
                submitted_version = int(clean)
            except ValueError:
                pass

        if submitted_version is not None and submitted_version != defect.version:
            latest_repr = DefectResponse.model_validate(defect).model_dump(mode="json")
            logger.warning(
                "CONCURRENCY_CONFLICT: Stale state transition rejected on defect '%s'. DB version=%d, submitted version=%d",
                defect.id,
                defect.version,
                submitted_version,
            )
            raise ConcurrencyConflictError(
                message=f"Defect '{defect.id}' was modified by another transaction. Database is at version {defect.version}, but version {submitted_version} was submitted.",
                current_version=defect.version,
                submitted_version=submitted_version,
                latest_defect=latest_repr,
            )

        old_status = defect.status
        target_status = (
            request.target_status.value
            if isinstance(request.target_status, DefectStatus)
            else str(request.target_status)
        )

        # Idempotent no-op check: if already in target status AND no field mutation requested
        if old_status == target_status:
            if (
                target_status == DefectStatus.ASSIGNED.value
                and request.assignee_id is not None
                and request.assignee_id != defect.assignee_id
            ):
                pass  # This is a reassignment mutation; proceed to RBAC and update logic
            else:
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

        # ----------------------------------------------------------------------
        # 2. Preliminary Input Checks (FR-023)
        # ----------------------------------------------------------------------
        if target_status == DefectStatus.IN_PROGRESS.value:
            if request.assignee_id is None and defect.assignee_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot transition to 'In Progress' without an assigned developer. Assignee is mandatory.",
                )

        # ----------------------------------------------------------------------
        # 3. Evaluate Role-Based Access Control & Separation of Duties (FR-031 - FR-037)
        # ----------------------------------------------------------------------
        cls.validate_transition_authorization(
            db=db,
            defect=defect,
            old_status=old_status,
            target_status=target_status,
            current_user=current_user,
            request=request,
        )

        old_assignee_id = defect.assignee_id

        # ----------------------------------------------------------------------
        # 4. Evaluate Specific Pre-Conditions for Each Target State
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
            if old_status == DefectStatus.IN_PROGRESS.value and assignee_id is None and defect.assignee_id is not None:
                assignee_id = defect.assignee_id

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
        try:
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
        except StaleDataError:
            db.rollback()
            latest = db.query(Defect).filter(Defect.id == defect_id).first()
            latest_repr = (
                DefectResponse.model_validate(latest).model_dump(mode="json")
                if latest
                else {}
            )
            logger.warning(
                "CONCURRENCY_COLLISION: StaleDataError caught on transition for defect '%s'",
                defect_id,
            )
            raise ConcurrencyConflictError(
                message=f"Defect '{defect_id}' was concurrently modified by another transaction. Stale transition rejected.",
                current_version=latest.version if latest else 0,
                submitted_version=submitted_version,
                latest_defect=latest_repr,
            )

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
        if_match: Optional[str] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'Assigned'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.ASSIGNED,
            assignee_id=request.assignee_id,
            version=request.version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)

    @classmethod
    def start_progress(
        cls,
        db: Session,
        defect_id: str,
        current_user: User,
        if_match: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'In Progress'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.IN_PROGRESS,
            version=version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)

    @classmethod
    def resolve_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectResolveRequest,
        current_user: User,
        if_match: Optional[str] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'Fixed'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.FIXED,
            root_cause=request.root_cause,
            resolution_notes=request.resolution_notes,
            fix_reference=request.fix_reference,
            version=request.version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)

    @classmethod
    def start_retest(
        cls,
        db: Session,
        defect_id: str,
        current_user: User,
        if_match: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'Retest'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.RETEST,
            version=version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)

    @classmethod
    def close_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectCloseRequest,
        current_user: User,
        if_match: Optional[str] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'Closed'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.CLOSED,
            verification_notes=request.verification_notes,
            version=request.version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)

    @classmethod
    def reopen_defect(
        cls,
        db: Session,
        defect_id: str,
        request: DefectReopenRequest,
        current_user: User,
        if_match: Optional[str] = None,
    ) -> Defect:
        """Convenience method to transition a defect to 'Reopened'."""
        transition_req = DefectTransitionRequest(
            target_status=DefectStatus.REOPENED,
            reopen_reason=request.reopen_reason,
            version=request.version,
        )
        return cls.transition_defect(db, defect_id, transition_req, current_user, if_match=if_match)
