"""Automated tests for Defect Evidence Quality Validation.

Addresses Requirements:
- FR-011: Complete deterministic evidence quality evaluation prior to 'Triaged'
- FR-012: Steps to Reproduce >= 2 numbered steps and >= 20 total characters
- FR-013: Expected and Actual results >= 10 characters each and non-identical
- FR-014: Environment details specify target OS, client/browser version, and tier
- FR-015: Reject transitions with HTTP 422 itemized error array on failure
- FR-016: Defect retained in 'Open' status until all evidence deficiencies are resolved
- FR-032: Permitted only for ROLE_QA_TRIAGE or ROLE_ADMIN

Master Test Cases:
- TC-EVID-001: Complete evidence passes quality gate (transition to Triaged succeeds)
- TC-EVID-002: Missing reproduction steps blocks triage (HTTP 422, remains Open)
- TC-EVID-003: Unstructured reproduction steps blocks triage (HTTP 422, >= 2 numbered steps)
- TC-EVID-004: Missing expected or actual result blocks triage (HTTP 422, itemized error)
- TC-EVID-005: Identical expected and actual result blocks triage (HTTP 422, non-identical)
- TC-EVID-006: Missing environment details blocks triage (HTTP 422, OS/client/tier required)
- TC-EVID-007: Quality gate failure payload formatting (HTTP 422 detailed array)
"""

import pytest
from sqlalchemy import select
from backend.models import (
    Defect,
    DefectHistory,
    UserRole,
    DefectStatus,
    DefectSeverity,
    DefectPriority,
    AuditActionType,
)
from backend.services.evidence_validation_service import (
    EvidenceValidationService,
    EvidenceQualityError,
)


def _create_open_defect(db_session, reporter, **overrides) -> Defect:
    """Helper to persist a defect in 'Open' status directly for test fixtures."""
    # Find next ID
    existing = db_session.query(Defect.id).all()
    next_id = f"DEF-{1001 + len(existing)}"

    defaults = {
        "id": next_id,
        "title": "Database connection pool exhausted under load",
        "description": "Under high concurrency spikes, connections in the pool become exhausted without recycling.",
        "steps_to_reproduce": "1. Launch simulated load runner with 50 threads.\n2. Submit 200 concurrent requests to /api/v1/defects.\n3. Observe database connection count.",
        "expected_result": "Connection pool recycles idle connections within 500ms timeout.",
        "actual_result": "Application raises OperationalError with connection timeout after 30 seconds.",
        "environment": "Ubuntu 22.04 / Firefox 124.0 / Staging",
        "module": "DatabaseCore",
        "severity": DefectSeverity.MAJOR.value,
        "priority": DefectPriority.P3.value,
        "status": DefectStatus.OPEN.value,
        "reporter_id": reporter.id,
        "version": 1,
    }
    defaults.update(overrides)
    defect = Defect(**defaults)
    db_session.add(defect)
    db_session.commit()
    db_session.refresh(defect)
    return defect


# ==============================================================================
# TC-EVID-001: Complete Evidence Passes Quality Gate
# ==============================================================================

def test_tc_evid_001_complete_evidence_passes_quality_gate(client, db_session, make_user, auth_headers):
    """TC-EVID-001: Complete evidence passes quality gate, promotes status to 'Triaged' (FR-011, FR-012, FR-013, FR-014)."""
    reporter = make_user(username="evid_reporter_001", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_001", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter)

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()

    # Verify status transition to Triaged
    assert data["status"] == DefectStatus.TRIAGED.value
    assert data["version"] == 2

    # Verify database persistence
    db_session.refresh(defect)
    assert defect.status == DefectStatus.TRIAGED.value
    assert defect.version == 2

    # Verify audit history logged
    history = db_session.query(DefectHistory).filter(
        DefectHistory.defect_id == defect.id,
        DefectHistory.action_type == AuditActionType.STATUS_CHANGED.value,
    ).first()
    assert history is not None
    assert history.changed_by_user_id == qa_user.id
    assert history.field_name == "status"
    assert history.old_value == DefectStatus.OPEN.value
    assert history.new_value == DefectStatus.TRIAGED.value
    assert history.version_snapshot == 2


def test_tc_evid_001_admin_can_triage_with_severity_priority_update(client, db_session, make_user, auth_headers):
    """TC-EVID-001 (Admin variant): Admin can triage and adjust severity/priority simultaneously."""
    reporter = make_user(username="evid_reporter_001b", role=UserRole.REPORTER)
    admin_user = make_user(username="evid_admin_001b", role=UserRole.ADMIN)
    defect = _create_open_defect(db_session, reporter)

    headers = auth_headers(admin_user)
    payload = {
        "severity": DefectSeverity.BLOCKER.value,
        "priority": DefectPriority.P1.value,
    }
    response = client.post(f"/api/v1/defects/{defect.id}/triage", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["status"] == DefectStatus.TRIAGED.value
    assert data["severity"] == DefectSeverity.BLOCKER.value
    assert data["priority"] == DefectPriority.P1.value

    db_session.refresh(defect)
    assert defect.status == DefectStatus.TRIAGED.value
    assert defect.severity == DefectSeverity.BLOCKER.value
    assert defect.priority == DefectPriority.P1.value


# ==============================================================================
# TC-EVID-002: Missing Reproduction Steps Blocks Triage
# ==============================================================================

def test_tc_evid_002_missing_reproduction_steps_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-002: Missing reproduction steps blocks triage with HTTP 422 and retains defect in 'Open' (FR-012, FR-015, FR-016)."""
    reporter = make_user(username="evid_reporter_002", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_002", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, steps_to_reproduce="")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    # Verify itemized error array identifies steps_to_reproduce
    errors = data.get("detail") or data.get("errors")
    assert isinstance(errors, list)
    steps_errors = [e for e in errors if e.get("field") == "steps_to_reproduce"]
    assert len(steps_errors) >= 1
    assert any("empty" in e["message"].lower() or "numbered" in e["message"].lower() for e in steps_errors)

    # Verify defect remains in Open status (FR-016)
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value
    assert defect.version == 1

    # Verify no audit history created
    history_count = db_session.query(DefectHistory).filter(DefectHistory.defect_id == defect.id).count()
    assert history_count == 0


# ==============================================================================
# TC-EVID-003: Unstructured Reproduction Steps Blocks Triage
# ==============================================================================

def test_tc_evid_003_unstructured_steps_under_20_chars_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-003: Single unnumbered sentence under 20 chars rejected with HTTP 422 (FR-012)."""
    reporter = make_user(username="evid_reporter_003a", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_003a", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, steps_to_reproduce="Click button to see")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    steps_errors = [e for e in errors if e.get("field") == "steps_to_reproduce"]
    assert len(steps_errors) >= 1
    error_texts = " ".join(e["message"] for e in steps_errors).lower()
    assert "20 characters" in error_texts or "numbered" in error_texts

    # Defect remains in Open status
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_003_unnumbered_steps_over_20_chars_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-003: Narrative text without numbered steps rejected with HTTP 422 (FR-012)."""
    reporter = make_user(username="evid_reporter_003b", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_003b", role=UserRole.QA_TRIAGE)
    unstructured_text = "I opened the application and then clicked the upload button and it crashed."
    defect = _create_open_defect(db_session, reporter, steps_to_reproduce=unstructured_text)

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    steps_errors = [e for e in errors if e.get("field") == "steps_to_reproduce"]
    assert len(steps_errors) >= 1
    assert any("numbered" in e["message"].lower() for e in steps_errors)

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_003_single_numbered_step_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-003: Only one numbered step rejected with HTTP 422 requiring >= 2 numbered steps (FR-012)."""
    reporter = make_user(username="evid_reporter_003c", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_003c", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        steps_to_reproduce="1. Open the file upload page and select a 50MB file from disk.",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    steps_errors = [e for e in errors if e.get("field") == "steps_to_reproduce"]
    assert len(steps_errors) >= 1
    assert any("at least 2" in e["message"].lower() for e in steps_errors)

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_003_duplicate_step_numbers_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-003: Duplicate step numbers (1 and 1) rejected because they are not distinct (FR-012)."""
    reporter = make_user(username="evid_reporter_003d", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_003d", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        steps_to_reproduce="1. First step description.\n1. First step repeated again.",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-EVID-004: Missing Expected or Actual Result Blocks Triage
# ==============================================================================

def test_tc_evid_004_missing_expected_result_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-004: Missing Expected Result blocks triage with itemized error (FR-013)."""
    reporter = make_user(username="evid_reporter_004a", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_004a", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        expected_result="",
        actual_result="Application terminates with unhandled null pointer exception.",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    exp_errors = [e for e in errors if e.get("field") == "expected_result"]
    assert len(exp_errors) >= 1
    assert any("expected result" in e["message"].lower() for e in exp_errors)

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_004_missing_actual_result_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-004: Missing Actual Result blocks triage with itemized error (FR-013)."""
    reporter = make_user(username="evid_reporter_004b", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_004b", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        expected_result="Application renders dashboard with 200 OK status.",
        actual_result="",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    act_errors = [e for e in errors if e.get("field") == "actual_result"]
    assert len(act_errors) >= 1
    assert any("actual result" in e["message"].lower() for e in act_errors)

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-EVID-005: Identical Expected and Actual Result Blocks Triage
# ==============================================================================

def test_tc_evid_005_identical_expected_and_actual_result_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-005: Identical Expected and Actual results rejected with HTTP 422 (FR-013)."""
    reporter = make_user(username="evid_reporter_005", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_005", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        expected_result="Page crashes with internal server error 500.",
        actual_result="Page crashes with internal server error 500.",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    identical_errors = [e for e in errors if "identical" in e.get("message", "").lower()]
    assert len(identical_errors) >= 1

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_005_case_insensitive_identical_results_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-005: Results identical under case-folding rejected with HTTP 422 (FR-013)."""
    reporter = make_user(username="evid_reporter_005b", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_005b", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(
        db_session,
        reporter,
        expected_result="PAGE CRASHES WITH ERROR CODE 500",
        actual_result="page crashes with error code 500",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    identical_errors = [e for e in errors if "identical" in e.get("message", "").lower()]
    assert len(identical_errors) >= 1

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-EVID-006: Missing Environment Details Blocks Triage
# ==============================================================================

def test_tc_evid_006_empty_environment_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-006: Empty environment string rejected with HTTP 422 (FR-014)."""
    reporter = make_user(username="evid_reporter_006a", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_006a", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, environment="")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    env_errors = [e for e in errors if e.get("field") == "environment"]
    assert len(env_errors) >= 1

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_006_environment_missing_os_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-006: Environment missing target OS rejected with HTTP 422 (FR-014)."""
    reporter = make_user(username="evid_reporter_006b", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_006b", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, environment="Firefox 124.0 / Staging")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    env_errors = [e for e in errors if e.get("field") == "environment"]
    assert len(env_errors) >= 1
    assert "target os" in env_errors[0]["message"].lower()

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_006_environment_missing_client_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-006: Environment missing client/browser version rejected with HTTP 422 (FR-014)."""
    reporter = make_user(username="evid_reporter_006c", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_006c", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, environment="Ubuntu 22.04 / Staging")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    env_errors = [e for e in errors if e.get("field") == "environment"]
    assert len(env_errors) >= 1
    assert "client/browser" in env_errors[0]["message"].lower()

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_tc_evid_006_environment_missing_tier_blocks_triage(client, db_session, make_user, auth_headers):
    """TC-EVID-006: Environment missing deployment tier rejected with HTTP 422 (FR-014)."""
    reporter = make_user(username="evid_reporter_006d", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_006d", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, environment="Ubuntu 22.04 / Firefox 124.0")

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    env_errors = [e for e in errors if e.get("field") == "environment"]
    assert len(env_errors) >= 1
    assert "deployment environment" in env_errors[0]["message"].lower()

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-EVID-007: Quality Gate Failure Payload Formatting
# ==============================================================================

def test_tc_evid_007_quality_gate_failure_payload_formatting(client, db_session, make_user, auth_headers):
    """TC-EVID-007: Multiple simultaneous evidence failures produce itemized detailed error array (FR-015)."""
    reporter = make_user(username="evid_reporter_007", role=UserRole.REPORTER)
    qa_user = make_user(username="evid_qa_007", role=UserRole.QA_TRIAGE)

    defect = _create_open_defect(
        db_session,
        reporter,
        steps_to_reproduce="Single unnumbered sentence",
        expected_result="Page fails",
        actual_result="Page fails",
        environment="Staging",
    )

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 422, response.text
    data = response.json()

    errors = data.get("detail") or data.get("errors")
    assert isinstance(errors, list)
    assert len(errors) >= 3, f"Expected at least 3 errors, got: {errors}"

    # Verify each error structure contains field, message, and rule
    defective_fields = set()
    for err in errors:
        assert "field" in err
        assert "message" in err
        assert "rule" in err
        defective_fields.add(err["field"])

    assert "steps_to_reproduce" in defective_fields
    assert "actual_result" in defective_fields or "expected_result" in defective_fields
    assert "environment" in defective_fields

    # Confirm defect remains in Open status
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# Security & State Transition Boundary Tests
# ==============================================================================

def test_triage_unauthenticated_request_rejected(client, db_session, make_user):
    """Unauthenticated request to triage endpoint rejected with HTTP 401."""
    reporter = make_user(username="unauth_reporter", role=UserRole.REPORTER)
    defect = _create_open_defect(db_session, reporter)

    response = client.post(f"/api/v1/defects/{defect.id}/triage")
    assert response.status_code == 401


def test_triage_unauthorized_reporter_rejected(client, db_session, make_user, auth_headers):
    """Reporter role cannot triage defects (OP_TRIAGE_DEFECT requires QA or Admin) per FR-032."""
    reporter = make_user(username="unauth_reporter_role", role=UserRole.REPORTER)
    defect = _create_open_defect(db_session, reporter)

    headers = auth_headers(reporter)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 403


def test_triage_unauthorized_developer_rejected(client, db_session, make_user, auth_headers):
    """Developer role cannot triage defects per FR-032."""
    reporter = make_user(username="dev_reporter_triage", role=UserRole.REPORTER)
    developer = make_user(username="unauth_dev_triage", role=UserRole.DEVELOPER)
    defect = _create_open_defect(db_session, reporter)

    headers = auth_headers(developer)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 403


def test_triage_nonexistent_defect_returns_404(client, make_user, auth_headers):
    """Attempting to triage non-existent defect returns HTTP 404."""
    qa_user = make_user(username="qa_404_triage", role=UserRole.QA_TRIAGE)
    headers = auth_headers(qa_user)
    response = client.post("/api/v1/defects/DEF-9999/triage", headers=headers)
    assert response.status_code == 404


def test_triage_non_open_defect_rejected_with_400(client, db_session, make_user, auth_headers):
    """Defect already past 'Open' cannot be triaged again; returns HTTP 400."""
    reporter = make_user(username="already_triaged_reporter", role=UserRole.REPORTER)
    qa_user = make_user(username="already_triaged_qa", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, status=DefectStatus.TRIAGED.value)

    headers = auth_headers(qa_user)
    response = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert response.status_code == 400
    assert "only defects in 'open' status" in response.text.lower()


# ==============================================================================
# Evidence Inspection Endpoint Tests
# ==============================================================================

def test_inspect_defect_evidence_success(client, db_session, make_user, auth_headers):
    """GET /api/v1/defects/{id}/validate-evidence reports valid evidence without state mutation."""
    reporter = make_user(username="inspect_rep_valid", role=UserRole.REPORTER)
    qa_user = make_user(username="inspect_qa_valid", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter)

    headers = auth_headers(qa_user)
    response = client.get(f"/api/v1/defects/{defect.id}/validate-evidence", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["is_valid"] is True
    assert data["errors"] == []

    # Verify state was not mutated
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_inspect_defect_evidence_with_deficiencies(client, db_session, make_user, auth_headers):
    """GET /api/v1/defects/{id}/validate-evidence returns is_valid=False and itemized errors without raising 422."""
    reporter = make_user(username="inspect_rep_invalid", role=UserRole.REPORTER)
    qa_user = make_user(username="inspect_qa_invalid", role=UserRole.QA_TRIAGE)
    defect = _create_open_defect(db_session, reporter, steps_to_reproduce="Short unnumbered")

    headers = auth_headers(qa_user)
    response = client.get(f"/api/v1/defects/{defect.id}/validate-evidence", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["is_valid"] is False
    assert len(data["errors"]) >= 1
    assert data["errors"][0]["field"] == "steps_to_reproduce"

    # Status remains Open
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


def test_inspect_defect_evidence_nonexistent_returns_404(client, make_user, auth_headers):
    """GET /api/v1/defects/{id}/validate-evidence returns HTTP 404 for missing defect."""
    qa_user = make_user(username="inspect_qa_404", role=UserRole.QA_TRIAGE)
    headers = auth_headers(qa_user)
    response = client.get("/api/v1/defects/DEF-9999/validate-evidence", headers=headers)
    assert response.status_code == 404


# ==============================================================================
# Direct Unit Tests for EvidenceValidationService
# ==============================================================================

def test_evidence_service_direct_unit_validations():
    """Direct unit tests for EvidenceValidationService helper methods and domain boundaries."""
    # Title validation
    assert len(EvidenceValidationService.validate_title("Short")) > 0
    assert len(EvidenceValidationService.validate_title("1234567890123")) > 0  # Purely numeric
    assert len(EvidenceValidationService.validate_title("A" * 121)) > 0
    assert len(EvidenceValidationService.validate_title("Valid defect title between 10 and 120")) == 0

    # Description validation
    assert len(EvidenceValidationService.validate_description("Too short")) > 0
    assert len(EvidenceValidationService.validate_description("A" * 30)) == 0

    # Module validation
    assert len(EvidenceValidationService.validate_module("")) > 0
    assert len(EvidenceValidationService.validate_module("M" * 101)) > 0
    assert len(EvidenceValidationService.validate_module("AuthenticationModule")) == 0

    # Enums validation
    assert len(EvidenceValidationService.validate_enums("InvalidSeverity", "P1-Immediate")) > 0
    assert len(EvidenceValidationService.validate_enums("Major", "InvalidPriority")) > 0
    assert len(EvidenceValidationService.validate_enums("Major", "P3-Medium")) == 0

    # Result helpers
    res = EvidenceValidationService.evaluate_evidence({
        "title": "Valid defect title for unit test",
        "description": "This is a detailed description meeting thirty characters.",
        "steps_to_reproduce": "1. First valid numbered step.\n2. Second valid numbered step.",
        "expected_result": "Application behaves properly per SRS specification.",
        "actual_result": "Application crashes with an unexpected exception.",
        "environment": "Ubuntu 22.04 / Chrome 120.0 / Staging",
        "module": "AuthCore",
        "severity": "Major",
        "priority": "P3-Medium",
    })
    assert res.is_valid is True
    assert res.errors == []
    assert res.has_error_for("steps_to_reproduce") is False
    assert res.get_errors_for("steps_to_reproduce") == []

    # validate_or_raise passes without error
    passed_res = EvidenceValidationService.validate_or_raise({
        "title": "Valid defect title for unit test",
        "description": "This is a detailed description meeting thirty characters.",
        "steps_to_reproduce": "1. First valid numbered step.\n2. Second valid numbered step.",
        "expected_result": "Application behaves properly per SRS specification.",
        "actual_result": "Application crashes with an unexpected exception.",
        "environment": "Ubuntu 22.04 / Chrome 120.0 / Staging",
        "module": "AuthCore",
        "severity": "Major",
        "priority": "P3-Medium",
    })
    assert passed_res.is_valid is True

    # validate_or_raise raises EvidenceQualityError on invalid payload
    with pytest.raises(EvidenceQualityError) as exc_info:
        EvidenceValidationService.validate_or_raise({
            "title": "Short",
            "description": "Short",
            "steps_to_reproduce": "Short",
            "expected_result": "Short",
            "actual_result": "Short",
            "environment": "",
            "module": "",
            "severity": "Bad",
            "priority": "Bad",
        })
    assert exc_info.value.status_code == 422
    assert len(exc_info.value.errors) > 0
