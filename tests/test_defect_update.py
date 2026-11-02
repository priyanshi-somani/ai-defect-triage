"""Automated tests for Defect Updating and Reporter Edit Governance.

Addresses Requirements:
- FR-006: Author edit allowed on Title, Description, Steps, Results, Environment in 'Open' status
- FR-007: Reject Reporter update attempts on defects authored by another user (HTTP 403)
- FR-008: Reject Reporter update attempts on defects transitioned past 'Open' status (HTTP 403)
- RISK-V1-002: Mitigation of unauthorized operation and privilege escalation

Test Cases:
- TC-DEF-007: Reporter updates own defect in Open status (200 OK, version increment, audit log)
- TC-DEF-008: Reporter rejected when editing another user's defect (403 Forbidden)
- TC-DEF-009: Reporter rejected when editing own defect past Open status (403 Forbidden)
"""

import pytest
from backend.models import Defect, DefectHistory, UserRole, DefectStatus, DefectSeverity, DefectPriority, AuditActionType


def _create_test_defect(client, auth_headers, user, **overrides):
    """Helper to create a defect via API and return response payload."""
    payload = {
        "title": "Initial defect title for update tests",
        "description": "Initial defect description with more than thirty characters.",
        "steps_to_reproduce": "1. Initial step reproduction.\n2. Observe result.",
        "expected_result": "Initial expected behavior.",
        "actual_result": "Initial observed failure.",
        "environment": "Ubuntu 22.04 / Chrome 120.0 / Dev",
        "module": "Checkout",
        "severity": DefectSeverity.MAJOR.value,
        "priority": DefectPriority.P3.value,
    }
    payload.update(overrides)
    res = client.post("/api/v1/defects", json=payload, headers=auth_headers(user))
    assert res.status_code == 201, res.text
    return res.json()


def test_tc_def_007_reporter_updates_own_defect_in_open_status(client, db_session, make_user, auth_headers):
    """TC-DEF-007: Reporter updates own defect while in Open status.
    
    Verifies:
        - HTTP 200 OK
        - Modified fields are persisted
        - Concurrency version token increments from 1 to 2
        - DefectHistory records audit deltas with action_type='UPDATED'
    """
    reporter = make_user(username="author_reporter_007", role=UserRole.REPORTER)
    headers = auth_headers(reporter)
    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    assert defect_data["version"] == 1
    assert defect_data["status"] == DefectStatus.OPEN.value

    # Update title, steps_to_reproduce, and environment
    update_payload = {
        "title": "Rectified defect title after further investigation",
        "steps_to_reproduce": "1. Updated step one.\n2. Updated step two.\n3. Updated step three.",
        "environment": "macOS Sonoma / Safari 17.4 / Staging",
    }
    update_res = client.put(f"/api/v1/defects/{defect_id}", json=update_payload, headers=headers)
    assert update_res.status_code == 200, update_res.text
    updated = update_res.json()

    # Verify updated values and version increment
    assert updated["id"] == defect_id
    assert updated["title"] == update_payload["title"]
    assert updated["steps_to_reproduce"] == update_payload["steps_to_reproduce"]
    assert updated["environment"] == update_payload["environment"]
    assert updated["description"] == defect_data["description"]  # Unmodified field preserved
    assert updated["version"] == 2

    # Verify audit history records in DB
    history_records = (
        db_session.query(DefectHistory)
        .filter(DefectHistory.defect_id == defect_id, DefectHistory.action_type == AuditActionType.UPDATED.value)
        .order_by(DefectHistory.field_name.asc())
        .all()
    )
    assert len(history_records) == 3

    field_map = {h.field_name: h for h in history_records}
    assert "title" in field_map
    assert field_map["title"].old_value == defect_data["title"]
    assert field_map["title"].new_value == update_payload["title"]
    assert field_map["title"].version_snapshot == 2
    assert field_map["title"].changed_by_user_id == reporter.id

    assert "steps_to_reproduce" in field_map
    assert field_map["steps_to_reproduce"].old_value == defect_data["steps_to_reproduce"]
    assert field_map["steps_to_reproduce"].new_value == update_payload["steps_to_reproduce"]

    assert "environment" in field_map
    assert field_map["environment"].old_value == defect_data["environment"]
    assert field_map["environment"].new_value == update_payload["environment"]


def test_tc_def_008_reporter_rejected_when_editing_another_users_defect(client, db_session, make_user, auth_headers):
    """TC-DEF-008: Reporter rejected with HTTP 403 when updating a defect authored by someone else (FR-007)."""
    reporter_a = make_user(username="author_user_a", role=UserRole.REPORTER)
    reporter_b = make_user(username="attacker_user_b", role=UserRole.REPORTER)

    defect_data = _create_test_defect(client, auth_headers, reporter_a)
    defect_id = defect_data["id"]

    # Reporter B attempts to update Reporter A's defect
    update_payload = {
        "title": "Malicious unauthorized title overwrite attempt",
        "description": "Unauthorized description alteration by non-author user.",
    }
    update_res = client.put(f"/api/v1/defects/{defect_id}", json=update_payload, headers=auth_headers(reporter_b))
    assert update_res.status_code == 403
    assert "another user" in update_res.json()["detail"].lower()

    # Verify database state was NOT modified
    defect_in_db = db_session.query(Defect).filter(Defect.id == defect_id).first()
    assert defect_in_db.title == defect_data["title"]
    assert defect_in_db.description == defect_data["description"]
    assert defect_in_db.version == 1

    # Verify no update audit history was recorded
    updates_count = (
        db_session.query(DefectHistory)
        .filter(DefectHistory.defect_id == defect_id, DefectHistory.action_type == AuditActionType.UPDATED.value)
        .count()
    )
    assert updates_count == 0


def test_tc_def_009_reporter_rejected_when_editing_own_defect_past_open(client, db_session, make_user, auth_headers):
    """TC-DEF-009: Reporter rejected with HTTP 403 when editing own defect that has moved past 'Open' (FR-008)."""
    reporter = make_user(username="author_past_open", role=UserRole.REPORTER)
    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    # Transition defect status to 'Triaged' directly in database
    defect_in_db = db_session.query(Defect).filter(Defect.id == defect_id).first()
    defect_in_db.status = DefectStatus.TRIAGED.value
    db_session.commit()

    # Reporter attempts to update their own defect now that it is Triaged
    update_payload = {
        "title": "Attempt to rectify description after triage has begun",
    }
    update_res = client.put(f"/api/v1/defects/{defect_id}", json=update_payload, headers=auth_headers(reporter))
    assert update_res.status_code == 403
    assert "updates only permitted in 'open' status" in update_res.json()["detail"].lower()

    # Verify unchanged
    db_session.refresh(defect_in_db)
    assert defect_in_db.title == defect_data["title"]
    assert defect_in_db.status == DefectStatus.TRIAGED.value


def test_developer_role_edit_governance(client, db_session, make_user, auth_headers):
    """Developer role follows same author governance and Open status restrictions as Reporter."""
    dev_a = make_user(username="dev_author", role=UserRole.DEVELOPER)
    dev_b = make_user(username="dev_other", role=UserRole.DEVELOPER)

    defect_data = _create_test_defect(client, auth_headers, dev_a)
    defect_id = defect_data["id"]

    # Dev B attempts to update Dev A's defect -> 403
    res_other = client.put(
        f"/api/v1/defects/{defect_id}",
        json={"title": "Dev B trying to edit Dev A defect"},
        headers=auth_headers(dev_b),
    )
    assert res_other.status_code == 403

    # Dev A updates own defect in Open status -> 200
    res_author = client.put(
        f"/api/v1/defects/{defect_id}",
        json={"title": "Dev A successfully updating own defect"},
        headers=auth_headers(dev_a),
    )
    assert res_author.status_code == 200
    assert res_author.json()["title"] == "Dev A successfully updating own defect"


def test_reporter_cannot_modify_severity_or_priority(client, make_user, auth_headers):
    """Reporters cannot alter severity or priority (OP_CHANGE_SEVERITY / OP_CHANGE_PRIORITY)."""
    reporter = make_user(username="reporter_priv_test", role=UserRole.REPORTER)
    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    # Attempt to elevate severity
    res_sev = client.put(
        f"/api/v1/defects/{defect_id}",
        json={"severity": DefectSeverity.BLOCKER.value},
        headers=auth_headers(reporter),
    )
    assert res_sev.status_code == 403
    assert "severity" in res_sev.json()["detail"].lower()

    # Attempt to elevate priority
    res_prio = client.put(
        f"/api/v1/defects/{defect_id}",
        json={"priority": DefectPriority.P1.value},
        headers=auth_headers(reporter),
    )
    assert res_prio.status_code == 403
    assert "priority" in res_prio.json()["detail"].lower()


def test_qa_triage_and_admin_permitted_to_update_any_defect(client, db_session, make_user, auth_headers):
    """QA/Triage and Admin users can update any defect, including severity and priority."""
    reporter = make_user(username="origin_reporter", role=UserRole.REPORTER)
    qa_user = make_user(username="qa_lead_user", role=UserRole.QA_TRIAGE)
    admin_user = make_user(username="sysadmin_user", role=UserRole.ADMIN)

    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    # QA updates module, severity, and priority on reporter's defect
    qa_update = {
        "module": "AuthenticationGateway",
        "severity": DefectSeverity.CRITICAL.value,
        "priority": DefectPriority.P1.value,
    }
    qa_res = client.put(f"/api/v1/defects/{defect_id}", json=qa_update, headers=auth_headers(qa_user))
    assert qa_res.status_code == 200, qa_res.text
    qa_data = qa_res.json()
    assert qa_data["module"] == qa_update["module"]
    assert qa_data["severity"] == DefectSeverity.CRITICAL.value
    assert qa_data["priority"] == DefectPriority.P1.value
    assert qa_data["version"] == 2

    # Admin updates environment
    admin_update = {"environment": "Production / AWS us-east-1"}
    admin_res = client.put(f"/api/v1/defects/{defect_id}", json=admin_update, headers=auth_headers(admin_user))
    assert admin_res.status_code == 200
    assert admin_res.json()["environment"] == admin_update["environment"]
    assert admin_res.json()["version"] == 3


def test_update_validation_boundaries(client, make_user, auth_headers):
    """Update endpoint validates boundaries for title, description, steps, results, environment, and module."""
    reporter = make_user(username="validator_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)
    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    # Title < 10 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"title": "Short"}, headers=headers).status_code == 422
    # Title > 120 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"title": "X" * 121}, headers=headers).status_code == 422
    # Title purely numeric
    assert client.put(f"/api/v1/defects/{defect_id}", json={"title": "1234567890123"}, headers=headers).status_code == 422
    # Description < 30 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"description": "Short description"}, headers=headers).status_code == 422
    # Steps < 20 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"steps_to_reproduce": "Step 1"}, headers=headers).status_code == 422
    # Expected result < 10 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"expected_result": "Tiny"}, headers=headers).status_code == 422
    # Actual result < 10 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"actual_result": "Broken"}, headers=headers).status_code == 422
    # Environment empty
    assert client.put(f"/api/v1/defects/{defect_id}", json={"environment": "   "}, headers=headers).status_code == 422
    # Environment > 255 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"environment": "E" * 256}, headers=headers).status_code == 422
    # Module empty
    assert client.put(f"/api/v1/defects/{defect_id}", json={"module": "   "}, headers=headers).status_code == 422
    # Module > 100 chars
    assert client.put(f"/api/v1/defects/{defect_id}", json={"module": "M" * 101}, headers=headers).status_code == 422
    # Non-string types
    assert client.put(f"/api/v1/defects/{defect_id}", json={"title": 123456789}, headers=headers).status_code == 422
    assert client.put(f"/api/v1/defects/{defect_id}", json={"description": ["desc"]}, headers=headers).status_code == 422
    assert client.put(f"/api/v1/defects/{defect_id}", json={"steps_to_reproduce": {"step": 1}}, headers=headers).status_code == 422
    assert client.put(f"/api/v1/defects/{defect_id}", json={"expected_result": True}, headers=headers).status_code == 422
    assert client.put(f"/api/v1/defects/{defect_id}", json={"environment": ["env"]}, headers=headers).status_code == 422
    assert client.put(f"/api/v1/defects/{defect_id}", json={"module": {"m": 1}}, headers=headers).status_code == 422


def test_update_nonexistent_defect_returns_404(client, make_user, auth_headers):
    """PUT /api/v1/defects/{id} returns HTTP 404 for non-existent defect."""
    reporter = make_user(username="missing_defect_user", role=UserRole.REPORTER)
    res = client.put(
        "/api/v1/defects/DEF-9999",
        json={"title": "Attempt to update missing defect"},
        headers=auth_headers(reporter),
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_unauthenticated_update_rejected_with_401(client):
    """PUT /api/v1/defects/{id} without authorization header returns HTTP 401."""
    res = client.put(
        "/api/v1/defects/DEF-1001",
        json={"title": "Unauthenticated update attempt"},
    )
    assert res.status_code == 401


def test_update_with_no_changes_preserves_version(client, make_user, auth_headers):
    """Updating a defect with empty or identical fields preserves version and creates no deltas."""
    reporter = make_user(username="noop_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)
    defect_data = _create_test_defect(client, auth_headers, reporter)
    defect_id = defect_data["id"]

    # Send identical title
    res = client.put(f"/api/v1/defects/{defect_id}", json={"title": defect_data["title"]}, headers=headers)
    assert res.status_code == 200
    assert res.json()["version"] == 1

    # Send empty payload
    res_empty = client.put(f"/api/v1/defects/{defect_id}", json={}, headers=headers)
    assert res_empty.status_code == 200
    assert res_empty.json()["version"] == 1
