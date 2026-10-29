"""Automated tests for Defect Creation and Input Validation.

Addresses Requirements:
- FR-001: Authenticated defect ingestion across all authorized roles
- FR-002: Title validation boundaries (10-120 chars, non-empty, non-numeric)
- FR-003: Description validation boundary (minimum 30 characters)
- FR-004: Sequential ID generation (DEF-1001), timestamps, reporter linkage
- FR-005: Initial status 'Open' and initial concurrency version 1
- FR-009: Severity enumeration domain validation
- FR-010: Priority enumeration domain validation

Test Cases:
- TC-DEF-001: Valid defect submission, DEF-1001 sequential assignment, status Open, version 1
- TC-DEF-002: Title boundary tests (9 fail, 10 pass, 120 pass, 121 fail)
- TC-DEF-003: Empty, whitespace-only, and purely numeric title rejection
- TC-DEF-004: Description boundary test (29 fail, 30 pass)
- TC-DEF-005: Safe handling of long text (4,000 characters) without truncation
- TC-DEF-005 (Enum): Invalid severity rejected with HTTP 422
- TC-DEF-006: Invalid priority rejected with HTTP 422
- TC-DEF-010: Defect persistence and retrieval consistency
- TC-DEF-010 (Auth): Unauthenticated creation request rejected with HTTP 401
"""

import pytest
from sqlalchemy import select
from backend.models import Defect, DefectHistory, UserRole, DefectStatus, DefectSeverity, DefectPriority, AuditActionType


def _sample_defect_payload(**overrides):
    """Generate a valid base payload for defect creation tests."""
    payload = {
        "title": "Network timeout during large file upload",
        "description": "When uploading files exceeding 50MB, the network socket terminates prematurely.",
        "steps_to_reproduce": "1. Navigate to /upload page.\n2. Select a 60MB payload file.\n3. Click upload button.",
        "expected_result": "Upload completes successfully with HTTP 200.",
        "actual_result": "Connection timed out with HTTP 504 Gateway Timeout.",
        "environment": "Ubuntu 22.04 / Firefox 124.0 / Staging",
        "module": "StorageService",
        "severity": DefectSeverity.MAJOR.value,
        "priority": DefectPriority.P3.value,
    }
    payload.update(overrides)
    return payload


def test_tc_def_001_valid_defect_creation(client, db_session, make_user, auth_headers):
    """TC-DEF-001: Valid defect submission returns HTTP 201, assigns DEF-1001, status Open, version 1."""
    reporter = make_user(username="test_reporter_001", role=UserRole.REPORTER)
    headers = auth_headers(reporter)
    payload = _sample_defect_payload()

    response = client.post("/api/v1/defects", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    data = response.json()

    # Verify FR-004: Unique ID sequence, reporter_id, created_at
    assert data["id"] == "DEF-1001"
    assert data["reporter_id"] == reporter.id
    assert data["created_at"] is not None
    assert data["updated_at"] is not None

    # Verify FR-005: Initial status 'Open' and concurrency version 1
    assert data["status"] == DefectStatus.OPEN.value
    assert data["version"] == 1
    assert data["reopen_count"] == 0
    assert data["assignee_id"] is None

    # Verify submitted payload fields
    assert data["title"] == payload["title"]
    assert data["description"] == payload["description"]
    assert data["steps_to_reproduce"] == payload["steps_to_reproduce"]
    assert data["expected_result"] == payload["expected_result"]
    assert data["actual_result"] == payload["actual_result"]
    assert data["environment"] == payload["environment"]
    assert data["module"] == payload["module"]
    assert data["severity"] == DefectSeverity.MAJOR.value
    assert data["priority"] == DefectPriority.P3.value

    # Verify initial DefectHistory audit record created atomically
    history_records = db_session.query(DefectHistory).filter(DefectHistory.defect_id == "DEF-1001").all()
    assert len(history_records) == 1
    history = history_records[0]
    assert history.action_type == AuditActionType.CREATED.value
    assert history.changed_by_user_id == reporter.id
    assert history.version_snapshot == 1
    assert history.new_value == DefectStatus.OPEN.value
    assert history.old_value is None
    assert history.field_name is None


def test_tc_def_001_sequential_id_generation(client, make_user, auth_headers):
    """TC-DEF-001 (Sequential Sequencing): Consecutive defect creations increment DEF-1001, DEF-1002, DEF-1003."""
    reporter = make_user(username="seq_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    res1 = client.post("/api/v1/defects", json=_sample_defect_payload(title="First defect title for seq"), headers=headers)
    res2 = client.post("/api/v1/defects", json=_sample_defect_payload(title="Second defect title for seq"), headers=headers)
    res3 = client.post("/api/v1/defects", json=_sample_defect_payload(title="Third defect title for seq"), headers=headers)

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res3.status_code == 201

    assert res1.json()["id"] == "DEF-1001"
    assert res2.json()["id"] == "DEF-1002"
    assert res3.json()["id"] == "DEF-1003"


def test_tc_def_001_creation_permitted_for_all_roles(client, make_user, auth_headers):
    """FR-001: All authenticated roles (Reporter, Developer, QA/Triage, Admin) can create defects."""
    roles = [UserRole.REPORTER, UserRole.DEVELOPER, UserRole.QA_TRIAGE, UserRole.ADMIN]

    for role in roles:
        user = make_user(username=f"user_{role.value.lower()}", role=role)
        headers = auth_headers(user)
        payload = _sample_defect_payload(title=f"Defect reported by {role.value}")

        response = client.post("/api/v1/defects", json=payload, headers=headers)
        assert response.status_code == 201, f"Failed for role {role.value}: {response.text}"
        assert response.json()["reporter_id"] == user.id


def test_tc_def_002_title_boundaries(client, make_user, auth_headers):
    """TC-DEF-002: Title boundary enforcement (9 chars fails, 10 passes, 120 passes, 121 fails)."""
    reporter = make_user(username="boundary_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # 9 chars -> HTTP 422
    payload_9 = _sample_defect_payload(title="123456789")
    res_9 = client.post("/api/v1/defects", json=payload_9, headers=headers)
    assert res_9.status_code == 422, "Expected 422 for 9-char title"

    # 10 chars -> HTTP 201
    payload_10 = _sample_defect_payload(title="123456789a")
    res_10 = client.post("/api/v1/defects", json=payload_10, headers=headers)
    assert res_10.status_code == 201, "Expected 201 for 10-char title"

    # 120 chars -> HTTP 201
    payload_120 = _sample_defect_payload(title="A" * 119 + "b")
    res_120 = client.post("/api/v1/defects", json=payload_120, headers=headers)
    assert res_120.status_code == 201, "Expected 201 for 120-char title"

    # 121 chars -> HTTP 422
    payload_121 = _sample_defect_payload(title="A" * 120 + "b")
    res_121 = client.post("/api/v1/defects", json=payload_121, headers=headers)
    assert res_121.status_code == 422, "Expected 422 for 121-char title"


def test_tc_def_003_empty_whitespace_or_numeric_title(client, make_user, auth_headers):
    """TC-DEF-003: Rejects empty, whitespace-only, and purely numeric titles with HTTP 422 (FR-002)."""
    reporter = make_user(username="whitespace_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # Empty title
    res_empty = client.post("/api/v1/defects", json=_sample_defect_payload(title=""), headers=headers)
    assert res_empty.status_code == 422

    # Whitespace only title
    res_ws = client.post("/api/v1/defects", json=_sample_defect_payload(title="          "), headers=headers)
    assert res_ws.status_code == 422

    # Purely numeric title
    res_num = client.post("/api/v1/defects", json=_sample_defect_payload(title="1234567890123"), headers=headers)
    assert res_num.status_code == 422
    assert "numeric" in res_num.text.lower()


def test_tc_def_004_description_length_boundary(client, make_user, auth_headers):
    """TC-DEF-004: Description boundary enforcement (29 chars fails, 30 chars passes) per FR-003."""
    reporter = make_user(username="desc_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # 29 chars -> HTTP 422
    payload_29 = _sample_defect_payload(description="A" * 29)
    res_29 = client.post("/api/v1/defects", json=payload_29, headers=headers)
    assert res_29.status_code == 422

    # 30 chars -> HTTP 201
    payload_30 = _sample_defect_payload(description="A" * 30)
    res_30 = client.post("/api/v1/defects", json=payload_30, headers=headers)
    assert res_30.status_code == 201
    assert res_30.json()["description"] == "A" * 30


def test_tc_def_005_safe_long_text_persistence(client, make_user, auth_headers):
    """TC-DEF-005: Defect creation safely handles long text (4,000 characters) without truncation."""
    reporter = make_user(username="long_text_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    long_description = "Detailed anomaly description: " + ("x" * 3960)
    long_steps = "1. Step reproduction sequence: " + ("y" * 3960)

    payload = _sample_defect_payload(
        description=long_description,
        steps_to_reproduce=long_steps,
    )

    response = client.post("/api/v1/defects", json=payload, headers=headers)
    assert response.status_code == 201
    defect_id = response.json()["id"]

    # Re-fetch via GET and assert full text integrity
    fetch_resp = client.get(f"/api/v1/defects/{defect_id}", headers=headers)
    assert fetch_resp.status_code == 200
    data = fetch_resp.json()
    assert len(data["description"]) == len(long_description)
    assert data["description"] == long_description
    assert len(data["steps_to_reproduce"]) == len(long_steps)
    assert data["steps_to_reproduce"] == long_steps


def test_tc_def_005_invalid_severity_rejected(client, make_user, auth_headers):
    """TC-DEF-005 / FR-009: Defect creation rejects invalid severity enum values with HTTP 422."""
    reporter = make_user(username="invalid_sev_user", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # 'Fatal' is not in DefectSeverity
    res_fatal = client.post("/api/v1/defects", json=_sample_defect_payload(severity="Fatal"), headers=headers)
    assert res_fatal.status_code == 422

    # 'Unknown' is not in DefectSeverity
    res_unknown = client.post("/api/v1/defects", json=_sample_defect_payload(severity="Unknown"), headers=headers)
    assert res_unknown.status_code == 422


def test_tc_def_006_invalid_priority_rejected(client, make_user, auth_headers):
    """TC-DEF-006 / FR-010: Defect creation rejects invalid priority enum values with HTTP 422."""
    reporter = make_user(username="invalid_prio_user", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # 'Urgent' is not in DefectPriority
    res_urgent = client.post("/api/v1/defects", json=_sample_defect_payload(priority="Urgent"), headers=headers)
    assert res_urgent.status_code == 422

    # 'P0' is not in DefectPriority
    res_p0 = client.post("/api/v1/defects", json=_sample_defect_payload(priority="P0"), headers=headers)
    assert res_p0.status_code == 422


def test_tc_def_010_persistence_and_retrieval_consistency(client, make_user, auth_headers):
    """TC-DEF-010: Defect created and re-fetched by ID matches submitted payload byte-for-byte."""
    reporter = make_user(username="persistence_user", role=UserRole.REPORTER)
    headers = auth_headers(reporter)
    payload = _sample_defect_payload(
        title="Exact byte-for-byte defect persistence check",
        description="Comprehensive persistence verification across all relational columns.",
        steps_to_reproduce="1. Perform operation A.\n2. Observe result B.",
        expected_result="Operation completes with success code.",
        actual_result="Operation aborted unexpectedly.",
        environment="macOS 14.5 / Safari 17.5 / Staging",
        module="PaymentGateway",
        severity=DefectSeverity.CRITICAL.value,
        priority=DefectPriority.P1.value,
    )

    create_res = client.post("/api/v1/defects", json=payload, headers=headers)
    assert create_res.status_code == 201
    defect_id = create_res.json()["id"]

    get_res = client.get(f"/api/v1/defects/{defect_id}", headers=headers)
    assert get_res.status_code == 200
    fetched = get_res.json()

    assert fetched["id"] == defect_id
    assert fetched["title"] == payload["title"]
    assert fetched["description"] == payload["description"]
    assert fetched["steps_to_reproduce"] == payload["steps_to_reproduce"]
    assert fetched["expected_result"] == payload["expected_result"]
    assert fetched["actual_result"] == payload["actual_result"]
    assert fetched["environment"] == payload["environment"]
    assert fetched["module"] == payload["module"]
    assert fetched["severity"] == payload["severity"]
    assert fetched["priority"] == payload["priority"]
    assert fetched["status"] == DefectStatus.OPEN.value
    assert fetched["version"] == 1
    assert fetched["reporter_id"] == reporter.id


def test_tc_def_010_unauthenticated_requests_rejected(client):
    """TC-DEF-010 (Security): Unauthenticated creation or fetch requests rejected with HTTP 401."""
    # Attempt POST without token
    res_post = client.post("/api/v1/defects", json=_sample_defect_payload())
    assert res_post.status_code == 401

    # Attempt GET without token
    res_get = client.get("/api/v1/defects/DEF-1001")
    assert res_get.status_code == 401


def test_defect_not_found_returns_404(client, make_user, auth_headers):
    """GET /api/v1/defects/{id} returns HTTP 404 when defect does not exist."""
    reporter = make_user(username="not_found_checker", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    response = client.get("/api/v1/defects/DEF-9999", headers=headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_validation_rules_for_other_evidence_fields(client, make_user, auth_headers):
    """Verify input validation for steps_to_reproduce, results, environment, and module."""
    reporter = make_user(username="field_validator_user", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # Steps to reproduce < 20 chars
    res_steps = client.post("/api/v1/defects", json=_sample_defect_payload(steps_to_reproduce="Short steps"), headers=headers)
    assert res_steps.status_code == 422

    # Expected result < 10 chars
    res_exp = client.post("/api/v1/defects", json=_sample_defect_payload(expected_result="Too short"), headers=headers)
    assert res_exp.status_code == 422

    # Actual result < 10 chars
    res_act = client.post("/api/v1/defects", json=_sample_defect_payload(actual_result="Broken"), headers=headers)
    assert res_act.status_code == 422

    # Environment empty
    res_env = client.post("/api/v1/defects", json=_sample_defect_payload(environment="   "), headers=headers)
    assert res_env.status_code == 422

    # Module empty
    res_mod = client.post("/api/v1/defects", json=_sample_defect_payload(module="   "), headers=headers)
    assert res_mod.status_code == 422


def test_validation_rules_length_caps_and_types(client, make_user, auth_headers):
    """Verify maximum length limits and type safety on defect fields."""
    reporter = make_user(username="cap_tester", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # Environment > 255 characters
    res_env_long = client.post("/api/v1/defects", json=_sample_defect_payload(environment="E" * 256), headers=headers)
    assert res_env_long.status_code == 422

    # Module > 100 characters
    res_mod_long = client.post("/api/v1/defects", json=_sample_defect_payload(module="M" * 101), headers=headers)
    assert res_mod_long.status_code == 422

    # Non-string types for fields
    assert client.post("/api/v1/defects", json=_sample_defect_payload(title={"key": "val"}), headers=headers).status_code == 422
    assert client.post("/api/v1/defects", json=_sample_defect_payload(description=["list", "desc"]), headers=headers).status_code == 422
    assert client.post("/api/v1/defects", json=_sample_defect_payload(steps_to_reproduce=123456789), headers=headers).status_code == 422
    assert client.post("/api/v1/defects", json=_sample_defect_payload(expected_result=True), headers=headers).status_code == 422
    assert client.post("/api/v1/defects", json=_sample_defect_payload(environment={"os": "linux"}), headers=headers).status_code == 422
    assert client.post("/api/v1/defects", json=_sample_defect_payload(module=["mod"]), headers=headers).status_code == 422


def test_sequential_id_generator_with_irregular_existing_ids(db_session, make_user):
    """Verify DefectService.generate_next_defect_id gracefully skips non-numeric suffixes."""
    from backend.services.defect_service import DefectService
    reporter = make_user(username="legacy_defect_user", role=UserRole.REPORTER)

    # Create defect with non-standard string ID
    legacy = Defect(
        id="DEF-LEGACY",
        title="Legacy imported defect without sequence",
        description="Legacy defect description that meets the thirty char requirement.",
        steps_to_reproduce="1. Legacy step one.\n2. Legacy step two.",
        expected_result="Legacy expected behavior.",
        actual_result="Legacy observed failure.",
        environment="Legacy / Windows XP",
        module="LegacyModule",
        reporter_id=reporter.id,
    )
    db_session.add(legacy)
    db_session.flush()

    # When table only has DEF-LEGACY, next ID should still default to DEF-1001
    next_id = DefectService.generate_next_defect_id(db_session)
    assert next_id == "DEF-1001"


def test_defect_history_response_schema_validation():
    """Verify DefectHistoryResponse Pydantic schema validation."""
    from datetime import datetime, timezone
    from backend.schemas.defect import DefectHistoryResponse

    data = {
        "id": 1,
        "defect_id": "DEF-1001",
        "changed_by_user_id": 5,
        "action_type": "CREATED",
        "field_name": None,
        "old_value": None,
        "new_value": "Open",
        "version_snapshot": 1,
        "timestamp": datetime.now(timezone.utc),
    }
    history_resp = DefectHistoryResponse.model_validate(data)
    assert history_resp.defect_id == "DEF-1001"
    assert history_resp.action_type == "CREATED"
