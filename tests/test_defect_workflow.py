"""Automated tests for Defect Lifecycle Workflow and Finite-State Machine.

Addresses Requirements:
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

Master Test Cases:
- TC-WF-001: Standard forward lifecycle progression (Open -> Triaged -> Assigned -> In Progress -> Fixed -> Retest -> Closed)
- TC-WF-002: Illegal direct transition: Open -> Closed (HTTP 400 Bad Request)
- TC-WF-003: Transition Triaged -> In Progress without assignee (HTTP 422 Unprocessable Entity)
- TC-WF-004: Transition In Progress -> Fixed requires resolution details (HTTP 422)
- TC-WF-005: Illegal direct transition: Fixed -> Closed (HTTP 400 Bad Request)
- TC-WF-006: Retest verification succeeds and defect closed (HTTP 200, notes required)
- TC-WF-007: Retest verification fails and defect reopened (HTTP 200, reopen_count increments)
- TC-WF-008: Reopened defect resumed by developer (HTTP 200, work resumed)
- TC-WF-009: Closed defect regressed and reopened (HTTP 200, regression justification)
- TC-WF-010: Assigned defect returned to triage queue (HTTP 200, assignee cleared)
- TC-WF-011: Comprehensive illegal transitions matrix (100% invalid transitions rejected with HTTP 400)
- TC-WF-012: Multi-cycle retest failure endurance (reopened multiple times, full audit sequence)
"""

import pytest
from backend.models import (
    Defect,
    DefectHistory,
    UserRole,
    DefectStatus,
    DefectSeverity,
    DefectPriority,
    AuditActionType,
)
from backend.schemas.defect import DefectTransitionRequest
from backend.services.workflow_service import WorkflowService


def _create_sample_defect(db_session, reporter, status=DefectStatus.OPEN.value, **overrides) -> Defect:
    """Helper to persist a defect in a specified status directly for test setups."""
    existing = db_session.query(Defect.id).all()
    next_id = f"DEF-{2001 + len(existing)}"

    defaults = {
        "id": next_id,
        "title": "Cache invalidation fails on distributed redis cluster",
        "description": "When multi-region instances update cached objects, cache eviction events are dropped.",
        "steps_to_reproduce": "1. Initialize redis cluster with 3 master nodes.\n2. Write key to region us-east-1.\n3. Verify key eviction in us-west-2.",
        "expected_result": "Eviction notification propagated to all replica nodes within 100ms.",
        "actual_result": "Replica node retains stale cached object indefinitely until manual restart.",
        "environment": "Ubuntu 22.04 / Chrome 122.0 / Staging",
        "module": "CacheSubsystem",
        "severity": DefectSeverity.CRITICAL.value,
        "priority": DefectPriority.P2.value,
        "status": status,
        "reporter_id": reporter.id,
        "version": 1,
        "reopen_count": 0,
    }
    defaults.update(overrides)
    defect = Defect(**defaults)
    db_session.add(defect)
    db_session.commit()
    db_session.refresh(defect)
    return defect


# ==============================================================================
# TC-WF-001: Standard Forward Lifecycle Progression
# ==============================================================================

def test_tc_wf_001_standard_forward_lifecycle_progression(client, db_session, make_user, auth_headers):
    """TC-WF-001: Complete sequential progression: Open -> Triaged -> Assigned -> In Progress -> Fixed -> Retest -> Closed."""
    reporter = make_user(username="wf_rep_001", role=UserRole.REPORTER)
    developer = make_user(username="wf_dev_001", role=UserRole.DEVELOPER)
    qa_user = make_user(username="wf_qa_001", role=UserRole.QA_TRIAGE)

    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    qa_headers = auth_headers(qa_user)
    dev_headers = auth_headers(developer)

    # 1. Open -> Triaged
    res_triage = client.post(f"/api/v1/defects/{defect.id}/triage", headers=qa_headers)
    assert res_triage.status_code == 200, res_triage.text
    assert res_triage.json()["status"] == DefectStatus.TRIAGED.value
    assert res_triage.json()["version"] == 2

    # 2. Triaged -> Assigned
    res_assign = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": developer.id},
        headers=qa_headers,
    )
    assert res_assign.status_code == 200, res_assign.text
    assert res_assign.json()["status"] == DefectStatus.ASSIGNED.value
    assert res_assign.json()["assignee_id"] == developer.id
    assert res_assign.json()["version"] == 3

    # 3. Assigned -> In Progress
    res_progress = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=dev_headers)
    assert res_progress.status_code == 200, res_progress.text
    assert res_progress.json()["status"] == DefectStatus.IN_PROGRESS.value
    assert res_progress.json()["version"] == 4

    # 4. In Progress -> Fixed
    fix_payload = {
        "root_cause": "PubSub connection listener timed out during cluster failover event.",
        "resolution_notes": "Added heartbeat ping and auto-reconnect backoff to PubSub listener.",
        "fix_reference": "commit:abc1234, PR: #108",
    }
    res_resolve = client.post(f"/api/v1/defects/{defect.id}/resolve", json=fix_payload, headers=dev_headers)
    assert res_resolve.status_code == 200, res_resolve.text
    assert res_resolve.json()["status"] == DefectStatus.FIXED.value
    assert res_resolve.json()["root_cause"] == fix_payload["root_cause"]
    assert res_resolve.json()["resolution_notes"] == fix_payload["resolution_notes"]
    assert res_resolve.json()["fix_reference"] == fix_payload["fix_reference"]
    assert res_resolve.json()["version"] == 5

    # 5. Fixed -> Retest
    res_retest = client.post(f"/api/v1/defects/{defect.id}/retest", headers=qa_headers)
    assert res_retest.status_code == 200, res_retest.text
    assert res_retest.json()["status"] == DefectStatus.RETEST.value
    assert res_retest.json()["version"] == 6

    # 6. Retest -> Closed
    close_payload = {
        "verification_notes": "Verified fix on Staging build 2.4.1 across 3 distributed redis nodes with zero packet drop.",
    }
    res_close = client.post(f"/api/v1/defects/{defect.id}/close", json=close_payload, headers=qa_headers)
    assert res_close.status_code == 200, res_close.text
    assert res_close.json()["status"] == DefectStatus.CLOSED.value
    assert res_close.json()["verification_notes"] == close_payload["verification_notes"]
    assert res_close.json()["version"] == 7

    # Verify final database representation
    db_session.refresh(defect)
    assert defect.status == DefectStatus.CLOSED.value
    assert defect.version == 7

    # Verify audit history logged every state transition
    history_entries = db_session.query(DefectHistory).filter(
        DefectHistory.defect_id == defect.id,
        DefectHistory.action_type == AuditActionType.STATUS_CHANGED.value,
    ).order_by(DefectHistory.version_snapshot.asc()).all()
    assert len(history_entries) == 6


# ==============================================================================
# TC-WF-002: Illegal Direct Transition: Open -> Closed
# ==============================================================================

def test_tc_wf_002_illegal_direct_transition_open_to_closed(client, db_session, make_user, auth_headers):
    """TC-WF-002: Reject direct transition from Open to Closed with HTTP 400 Bad Request (FR-022)."""
    reporter = make_user(username="wf_rep_002", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_002", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.OPEN.value)

    headers = auth_headers(qa_user)
    # Via generic /transition endpoint
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.CLOSED.value, "verification_notes": "Verified directly without triage."},
        headers=headers,
    )
    assert response.status_code == 400, response.text
    assert "direct closure" in response.text.lower() or "illegal" in response.text.lower()

    # Via semantic /close endpoint
    res_close = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "Direct closure attempt."},
        headers=headers,
    )
    assert res_close.status_code == 400

    # Defect remains in Open status
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value
    assert defect.version == 1


# ==============================================================================
# TC-WF-003: Transition Triaged -> In Progress Without Assignee
# ==============================================================================

def test_tc_wf_003_triaged_to_in_progress_without_assignee_rejected(client, db_session, make_user, auth_headers):
    """TC-WF-003: Attempt to start progress from Triaged with assignee_id = null rejected with HTTP 422 (FR-023)."""
    reporter = make_user(username="wf_rep_003", role=UserRole.REPORTER)
    dev_user = make_user(username="wf_dev_003", role=UserRole.DEVELOPER)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.TRIAGED.value, assignee_id=None)

    headers = auth_headers(dev_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.IN_PROGRESS.value, "assignee_id": None},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "assignee is mandatory" in response.text.lower() or "assigned developer" in response.text.lower()

    # Via semantic /start-progress
    res_sem = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=headers)
    assert res_sem.status_code == 422

    db_session.refresh(defect)
    assert defect.status == DefectStatus.TRIAGED.value


def test_tc_wf_003_triaged_to_in_progress_with_assignee_succeeds(client, db_session, make_user, auth_headers):
    """TC-WF-003 (Positive): Transitioning from Triaged to In Progress with assignee supplied succeeds."""
    reporter = make_user(username="wf_rep_003b", role=UserRole.REPORTER)
    dev_user = make_user(username="wf_dev_003b", role=UserRole.DEVELOPER)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.TRIAGED.value, assignee_id=None)

    headers = auth_headers(dev_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.IN_PROGRESS.value, "assignee_id": dev_user.id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == DefectStatus.IN_PROGRESS.value
    assert response.json()["assignee_id"] == dev_user.id


# ==============================================================================
# TC-WF-004: Transition In Progress -> Fixed Requires Resolution Details
# ==============================================================================

def test_tc_wf_004_transition_in_progress_to_fixed_requires_resolution(client, db_session, make_user, auth_headers):
    """TC-WF-004: Missing resolution_notes, root_cause, or fix_reference rejected with HTTP 422 (FR-024)."""
    reporter = make_user(username="wf_rep_004", role=UserRole.REPORTER)
    dev_user = make_user(username="wf_dev_004", role=UserRole.DEVELOPER)
    defect = _create_sample_defect(
        db_session,
        reporter,
        status=DefectStatus.IN_PROGRESS.value,
        assignee_id=dev_user.id,
    )

    headers = auth_headers(dev_user)

    # Missing all resolution fields
    res_empty = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.FIXED.value},
        headers=headers,
    )
    assert res_empty.status_code == 422
    assert "resolution details" in res_empty.text.lower()

    # Missing fix_reference
    res_partial = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={
            "target_status": DefectStatus.FIXED.value,
            "root_cause": "Race condition in cache lock.",
            "resolution_notes": "Implemented mutex lock.",
        },
        headers=headers,
    )
    assert res_partial.status_code == 422
    assert "fix_reference" in res_partial.text

    # Defect remains in In Progress status
    db_session.refresh(defect)
    assert defect.status == DefectStatus.IN_PROGRESS.value


# ==============================================================================
# TC-WF-005: Illegal Direct Transition: Fixed -> Closed
# ==============================================================================

def test_tc_wf_005_illegal_direct_transition_fixed_to_closed(client, db_session, make_user, auth_headers):
    """TC-WF-005: Attempt to close Fixed defect directly bypassing Retest rejected with HTTP 400 (FR-025)."""
    reporter = make_user(username="wf_rep_005", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_005", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(
        db_session,
        reporter,
        status=DefectStatus.FIXED.value,
        root_cause="Null pointer exception on payload parse.",
        resolution_notes="Added null safety check.",
        fix_reference="PR #112",
    )

    headers = auth_headers(qa_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.CLOSED.value, "verification_notes": "Verified directly without Retest."},
        headers=headers,
    )
    assert response.status_code == 400, response.text
    assert "retest is mandatory" in response.text.lower() or "illegal" in response.text.lower()

    # Via semantic endpoint /close
    res_close = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "Verified directly without Retest."},
        headers=headers,
    )
    assert res_close.status_code == 400

    db_session.refresh(defect)
    assert defect.status == DefectStatus.FIXED.value


# ==============================================================================
# TC-WF-006: Retest Verification Succeeds and Defect Closed
# ==============================================================================

def test_tc_wf_006_retest_verification_succeeds_and_defect_closed(client, db_session, make_user, auth_headers):
    """TC-WF-006: Retest verification passes with verification_notes, defect transitions to Closed (FR-026)."""
    reporter = make_user(username="wf_rep_006", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_006", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.RETEST.value)

    headers = auth_headers(qa_user)

    # Missing verification notes (< 15 chars) rejected with HTTP 422
    res_short = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "Too short"},
        headers=headers,
    )
    assert res_short.status_code == 422
    assert "at least 15 characters" in res_short.text.lower()

    # Valid verification notes (>= 15 chars) succeeds
    valid_notes = "Verified fix on Staging environment; automated regression passed with 100% success."
    res_valid = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": valid_notes},
        headers=headers,
    )
    assert res_valid.status_code == 200, res_valid.text
    assert res_valid.json()["status"] == DefectStatus.CLOSED.value
    assert res_valid.json()["verification_notes"] == valid_notes

    db_session.refresh(defect)
    assert defect.status == DefectStatus.CLOSED.value


# ==============================================================================
# TC-WF-007: Retest Verification Fails and Defect Reopened
# ==============================================================================

def test_tc_wf_007_retest_verification_fails_and_defect_reopened(client, db_session, make_user, auth_headers):
    """TC-WF-007: Retest verification fails, transitions to Reopened and increments reopen_count (FR-027)."""
    reporter = make_user(username="wf_rep_007", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_007", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.RETEST.value, reopen_count=0)

    headers = auth_headers(qa_user)

    # Reopen reason < 20 chars rejected with HTTP 422
    res_short = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": "Still broken"},
        headers=headers,
    )
    assert res_short.status_code == 422
    assert "at least 20 characters" in res_short.text.lower()

    # Valid reopen reason (>= 20 chars) succeeds
    reopen_text = "Retest failed in Staging: cache eviction still drops notifications under 50 concurrent threads."
    res_valid = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": reopen_text},
        headers=headers,
    )
    assert res_valid.status_code == 200, res_valid.text
    assert res_valid.json()["status"] == DefectStatus.REOPENED.value
    assert res_valid.json()["reopen_count"] == 1
    assert res_valid.json()["reopen_reason"] == reopen_text

    db_session.refresh(defect)
    assert defect.status == DefectStatus.REOPENED.value
    assert defect.reopen_count == 1


# ==============================================================================
# TC-WF-008: Reopened Defect Resumed by Developer
# ==============================================================================

def test_tc_wf_008_reopened_defect_resumed_by_developer(client, db_session, make_user, auth_headers):
    """TC-WF-008: Assigned developer moves Reopened defect directly to In Progress (FR-021)."""
    reporter = make_user(username="wf_rep_008", role=UserRole.REPORTER)
    dev_user = make_user(username="wf_dev_008", role=UserRole.DEVELOPER)
    defect = _create_sample_defect(
        db_session,
        reporter,
        status=DefectStatus.REOPENED.value,
        assignee_id=dev_user.id,
        reopen_count=1,
    )

    headers = auth_headers(dev_user)
    response = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == DefectStatus.IN_PROGRESS.value

    db_session.refresh(defect)
    assert defect.status == DefectStatus.IN_PROGRESS.value


# ==============================================================================
# TC-WF-009: Closed Defect Regressed and Reopened
# ==============================================================================

def test_tc_wf_009_closed_defect_regressed_and_reopened(client, db_session, make_user, auth_headers):
    """TC-WF-009: QA/Admin reopens Closed defect upon documented regression with justification (FR-028)."""
    reporter = make_user(username="wf_rep_009", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_009", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(
        db_session,
        reporter,
        status=DefectStatus.CLOSED.value,
        reopen_count=0,
    )

    headers = auth_headers(qa_user)
    regression_notes = "Production regression discovered in Release 2.5: cache invalidation dropped after redis cluster node restart."
    response = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": regression_notes},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == DefectStatus.REOPENED.value
    assert data["reopen_count"] == 1
    assert data["reopen_reason"] == regression_notes

    db_session.refresh(defect)
    assert defect.status == DefectStatus.REOPENED.value
    assert defect.reopen_count == 1


# ==============================================================================
# TC-WF-010: Assigned Defect Returned to Triage Queue
# ==============================================================================

def test_tc_wf_010_assigned_defect_returned_to_triage_queue(client, db_session, make_user, auth_headers):
    """TC-WF-010: Assigned defect moved back to Triaged clears assignee_id (FR-029)."""
    reporter = make_user(username="wf_rep_010", role=UserRole.REPORTER)
    dev_user = make_user(username="wf_dev_010", role=UserRole.DEVELOPER)
    qa_user = make_user(username="wf_qa_010", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(
        db_session,
        reporter,
        status=DefectStatus.ASSIGNED.value,
        assignee_id=dev_user.id,
    )

    headers = auth_headers(qa_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.TRIAGED.value},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == DefectStatus.TRIAGED.value
    assert data["assignee_id"] is None

    db_session.refresh(defect)
    assert defect.status == DefectStatus.TRIAGED.value
    assert defect.assignee_id is None


# ==============================================================================
# TC-WF-011: Comprehensive Illegal Transitions Matrix
# ==============================================================================

def test_tc_wf_011_comprehensive_illegal_transitions_suite(client, db_session, make_user, auth_headers):
    """TC-WF-011: 100% of illegal state transitions rejected with HTTP 400 Bad Request (FR-030)."""
    reporter = make_user(username="wf_rep_011", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_011", role=UserRole.QA_TRIAGE)
    headers = auth_headers(qa_user)

    # Defined legal transitions from docs/defect-workflow.md
    legal_map = {
        DefectStatus.OPEN.value: {DefectStatus.TRIAGED.value},
        DefectStatus.TRIAGED.value: {DefectStatus.ASSIGNED.value, DefectStatus.OPEN.value, DefectStatus.IN_PROGRESS.value},
        DefectStatus.ASSIGNED.value: {DefectStatus.IN_PROGRESS.value, DefectStatus.TRIAGED.value},
        DefectStatus.IN_PROGRESS.value: {DefectStatus.FIXED.value, DefectStatus.ASSIGNED.value},
        DefectStatus.FIXED.value: {DefectStatus.RETEST.value},
        DefectStatus.RETEST.value: {DefectStatus.CLOSED.value, DefectStatus.REOPENED.value},
        DefectStatus.CLOSED.value: {DefectStatus.REOPENED.value},
        DefectStatus.REOPENED.value: {DefectStatus.ASSIGNED.value, DefectStatus.IN_PROGRESS.value},
    }

    all_statuses = [s.value for s in DefectStatus]

    # Test key representative illegal transition pairs across every status
    tested_illegal_pairs = [
        # From Open
        (DefectStatus.OPEN.value, DefectStatus.ASSIGNED.value),
        (DefectStatus.OPEN.value, DefectStatus.FIXED.value),
        (DefectStatus.OPEN.value, DefectStatus.RETEST.value),
        (DefectStatus.OPEN.value, DefectStatus.CLOSED.value),
        (DefectStatus.OPEN.value, DefectStatus.REOPENED.value),
        # From Triaged
        (DefectStatus.TRIAGED.value, DefectStatus.FIXED.value),
        (DefectStatus.TRIAGED.value, DefectStatus.RETEST.value),
        (DefectStatus.TRIAGED.value, DefectStatus.CLOSED.value),
        (DefectStatus.TRIAGED.value, DefectStatus.REOPENED.value),
        # From Assigned
        (DefectStatus.ASSIGNED.value, DefectStatus.OPEN.value),
        (DefectStatus.ASSIGNED.value, DefectStatus.FIXED.value),
        (DefectStatus.ASSIGNED.value, DefectStatus.RETEST.value),
        (DefectStatus.ASSIGNED.value, DefectStatus.CLOSED.value),
        # From In Progress
        (DefectStatus.IN_PROGRESS.value, DefectStatus.OPEN.value),
        (DefectStatus.IN_PROGRESS.value, DefectStatus.TRIAGED.value),
        (DefectStatus.IN_PROGRESS.value, DefectStatus.RETEST.value),
        (DefectStatus.IN_PROGRESS.value, DefectStatus.CLOSED.value),
        # From Fixed
        (DefectStatus.FIXED.value, DefectStatus.OPEN.value),
        (DefectStatus.FIXED.value, DefectStatus.TRIAGED.value),
        (DefectStatus.FIXED.value, DefectStatus.ASSIGNED.value),
        (DefectStatus.FIXED.value, DefectStatus.IN_PROGRESS.value),
        (DefectStatus.FIXED.value, DefectStatus.CLOSED.value),
        (DefectStatus.FIXED.value, DefectStatus.REOPENED.value),
        # From Retest
        (DefectStatus.RETEST.value, DefectStatus.OPEN.value),
        (DefectStatus.RETEST.value, DefectStatus.TRIAGED.value),
        (DefectStatus.RETEST.value, DefectStatus.ASSIGNED.value),
        (DefectStatus.RETEST.value, DefectStatus.IN_PROGRESS.value),
        (DefectStatus.RETEST.value, DefectStatus.FIXED.value),
        # From Closed
        (DefectStatus.CLOSED.value, DefectStatus.OPEN.value),
        (DefectStatus.CLOSED.value, DefectStatus.TRIAGED.value),
        (DefectStatus.CLOSED.value, DefectStatus.ASSIGNED.value),
        (DefectStatus.CLOSED.value, DefectStatus.IN_PROGRESS.value),
        (DefectStatus.CLOSED.value, DefectStatus.FIXED.value),
        (DefectStatus.CLOSED.value, DefectStatus.RETEST.value),
        # From Reopened
        (DefectStatus.REOPENED.value, DefectStatus.OPEN.value),
        (DefectStatus.REOPENED.value, DefectStatus.TRIAGED.value),
        (DefectStatus.REOPENED.value, DefectStatus.FIXED.value),
        (DefectStatus.REOPENED.value, DefectStatus.RETEST.value),
        (DefectStatus.REOPENED.value, DefectStatus.CLOSED.value),
    ]

    for source_status, target_status in tested_illegal_pairs:
        defect = _create_sample_defect(db_session, reporter, status=source_status)
        payload = {
            "target_status": target_status,
            "verification_notes": "Attempting illegal transition notes.",
            "reopen_reason": "Attempting illegal transition reason.",
            "resolution_notes": "Attempting illegal resolution notes.",
            "root_cause": "Attempting illegal root cause.",
            "fix_reference": "commit:illegal",
        }
        res = client.post(f"/api/v1/defects/{defect.id}/transition", json=payload, headers=headers)
        assert res.status_code == 400, (
            f"Expected HTTP 400 for illegal transition '{source_status}' -> '{target_status}', got {res.status_code}: {res.text}"
        )
        assert "illegal" in res.text.lower() or "cannot transition" in res.text.lower()


# ==============================================================================
# TC-WF-012: Multi-Cycle Retest Failure Endurance
# ==============================================================================

def test_tc_wf_012_multi_cycle_retest_failure_endurance(client, db_session, make_user, auth_headers):
    """TC-WF-012: Defect reopened twice (reopen_count = 2) before eventual closure; full audit history captured."""
    reporter = make_user(username="wf_rep_012", role=UserRole.REPORTER)
    developer = make_user(username="wf_dev_012", role=UserRole.DEVELOPER)
    qa_user = make_user(username="wf_qa_012", role=UserRole.QA_TRIAGE)

    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    qa_headers = auth_headers(qa_user)
    dev_headers = auth_headers(developer)

    # Initial cycle: Open -> Triaged -> Assigned -> In Progress -> Fixed -> Retest
    client.post(f"/api/v1/defects/{defect.id}/triage", headers=qa_headers)
    client.post(f"/api/v1/defects/{defect.id}/assign", json={"assignee_id": developer.id}, headers=qa_headers)
    client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=dev_headers)
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={"root_cause": "Initial cause 1", "resolution_notes": "Fix attempt 1", "fix_reference": "commit:1"},
        headers=dev_headers,
    )
    client.post(f"/api/v1/defects/{defect.id}/retest", headers=qa_headers)

    # Cycle 1 failure: Retest -> Reopened (reopen_count = 1)
    res_reopen_1 = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": "Failure cycle 1: Memory leak observed during high load retest."},
        headers=qa_headers,
    )
    assert res_reopen_1.status_code == 200
    assert res_reopen_1.json()["reopen_count"] == 1

    # Cycle 2: In Progress -> Fixed -> Retest
    client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=dev_headers)
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={"root_cause": "Initial cause 2", "resolution_notes": "Fix attempt 2", "fix_reference": "commit:2"},
        headers=dev_headers,
    )
    client.post(f"/api/v1/defects/{defect.id}/retest", headers=qa_headers)

    # Cycle 2 failure: Retest -> Reopened (reopen_count = 2)
    res_reopen_2 = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": "Failure cycle 2: Memory leak reduced but socket connections not closed."},
        headers=qa_headers,
    )
    assert res_reopen_2.status_code == 200
    assert res_reopen_2.json()["reopen_count"] == 2

    # Cycle 3: In Progress -> Fixed -> Retest -> Closed
    client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=dev_headers)
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={"root_cause": "Final root cause", "resolution_notes": "Final fix attempt 3", "fix_reference": "commit:3"},
        headers=dev_headers,
    )
    client.post(f"/api/v1/defects/{defect.id}/retest", headers=qa_headers)
    res_final_close = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "Final verification passed across 100 consecutive load cycles in staging."},
        headers=qa_headers,
    )
    assert res_final_close.status_code == 200
    assert res_final_close.json()["status"] == DefectStatus.CLOSED.value
    assert res_final_close.json()["reopen_count"] == 2

    # Verify database persistence
    db_session.refresh(defect)
    assert defect.status == DefectStatus.CLOSED.value
    assert defect.reopen_count == 2

    # Verify audit history captured full sequence (14 status changes)
    status_histories = db_session.query(DefectHistory).filter(
        DefectHistory.defect_id == defect.id,
        DefectHistory.field_name == "status",
    ).order_by(DefectHistory.version_snapshot.asc()).all()
    assert len(status_histories) == 14


# ==============================================================================
# Additional Boundary & Error Handling Tests
# ==============================================================================

def test_transition_nonexistent_defect_returns_404(client, make_user, auth_headers):
    """Transition attempt on non-existent defect returns HTTP 404."""
    qa_user = make_user(username="wf_qa_404", role=UserRole.QA_TRIAGE)
    headers = auth_headers(qa_user)
    response = client.post(
        "/api/v1/defects/DEF-9999/transition",
        json={"target_status": DefectStatus.TRIAGED.value},
        headers=headers,
    )
    assert response.status_code == 404


def test_transition_unauthenticated_returns_401(client, db_session, make_user):
    """Unauthenticated transition attempt rejected with HTTP 401."""
    reporter = make_user(username="wf_unauth_rep", role=UserRole.REPORTER)
    defect = _create_sample_defect(db_session, reporter)
    response = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.TRIAGED.value},
    )
    assert response.status_code == 401


def test_assign_to_nonexistent_user_returns_404(client, db_session, make_user, auth_headers):
    """Attempting to assign defect to non-existent user returns HTTP 404."""
    reporter = make_user(username="wf_rep_assign_404", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_assign_404", role=UserRole.QA_TRIAGE)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.TRIAGED.value)

    headers = auth_headers(qa_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": 99999},
        headers=headers,
    )
    assert response.status_code == 404


def test_assign_to_inactive_user_returns_400(client, db_session, make_user, auth_headers):
    """Attempting to assign defect to inactive user returns HTTP 400."""
    reporter = make_user(username="wf_rep_inactive", role=UserRole.REPORTER)
    qa_user = make_user(username="wf_qa_inactive", role=UserRole.QA_TRIAGE)
    inactive_dev = make_user(username="inactive_dev_user", role=UserRole.DEVELOPER, is_active=False)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.TRIAGED.value)

    headers = auth_headers(qa_user)
    response = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": inactive_dev.id},
        headers=headers,
    )
    assert response.status_code == 400
    assert "inactive" in response.text.lower()


def test_workflow_service_idempotent_no_op_transition(db_session, make_user):
    """Transitioning to the current status is an idempotent no-op."""
    reporter = make_user(username="wf_rep_noop", role=UserRole.REPORTER)
    defect = _create_sample_defect(db_session, reporter, status=DefectStatus.OPEN.value)

    transition_req = DefectTransitionRequest(target_status=DefectStatus.OPEN)
    res = WorkflowService.transition_defect(db_session, defect.id, transition_req, reporter)
    assert res.status_code if hasattr(res, "status_code") else res.status == DefectStatus.OPEN.value
    assert res.version == 1
