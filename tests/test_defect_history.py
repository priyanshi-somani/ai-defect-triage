"""Automated test suite for Defect History and Audit Traceability.

Addresses Requirements:
- FR-049: Generate immutable audit log entry for every status transition, assignee change, severity change, priority change, and field update.
- FR-050: Audit log entry records: defect_id, changed_by_user_id, timestamp, action_type, field_name, old_value, new_value, and version_snapshot.
- FR-051: Expose chronological audit history endpoint for any defect accessible to all authenticated roles.
- FR-052: Direct modification or deletion of audit records rejected / not permitted.
- OP_VIEW_AUDIT_LOG: Permitted for Reporter, Developer, QA/Triage, and Admin.

Test Cases:
- TC-HIST-001: Status transition generates audit log (Open -> Triaged captures old_value, new_value, actor, timestamp).
- TC-HIST-002: Field edit generates audit delta (Title updated captures field=title, old_value, new_value).
- TC-HIST-003: Assignee change generates audit entry (unassigned -> dev A -> dev B logs transitions).
- TC-HIST-004: History endpoint exposes complete sequence (transitions through 5 states returned in chronological order).
- TC-HIST-005: Audit log immutability check (direct API update/delete rejected; direct DB mutation restricted).
- Additional: Defect not found returns HTTP 404.
- Additional: Unauthenticated access returns HTTP 401.
- Additional: Authorization matrix (Reporter, Developer, QA, Admin all permitted to view audit history).
"""

import pytest
from backend.models.enums import UserRole, DefectStatus, DefectSeverity, DefectPriority, AuditActionType
from backend.models.history import DefectHistory


def _sample_valid_defect_payload(**overrides):
    """Helper returning a standard defect creation payload."""
    payload = {
        "title": "Corrupted invoice generation on checkout",
        "description": "Invoice PDF generator outputs zero-byte corrupted files for multi-currency orders.",
        "steps_to_reproduce": "1. Navigate to billing.\n2. Select EUR payment.\n3. Click generate invoice button.",
        "expected_result": "PDF invoice downloads with formatted layout.",
        "actual_result": "Zero-byte file generated with error code 500.",
        "environment": "Ubuntu 22.04 / Chrome 124 / Staging",
        "module": "BillingService",
        "severity": DefectSeverity.MAJOR.value,
        "priority": DefectPriority.P3.value,
    }
    payload.update(overrides)
    return payload


# ==============================================================================
# TC-HIST-001: Status transition generates audit log
# ==============================================================================

def test_tc_hist_001_status_transition_generates_audit_log(client, make_user, auth_headers):
    """TC-HIST-001: Status transition Open -> Triaged creates an audit record with old_value=Open, new_value=Triaged."""
    reporter = make_user(username="rep_hist_001", role=UserRole.REPORTER)
    qa_user = make_user(username="qa_hist_001", role=UserRole.QA_TRIAGE)

    # 1. Create defect (initial status Open)
    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=auth_headers(reporter))
    assert res_create.status_code == 201
    defect_id = res_create.json()["id"]

    # 2. Triage defect (Open -> Triaged)
    res_triage = client.post(f"/api/v1/defects/{defect_id}/triage", headers=auth_headers(qa_user))
    assert res_triage.status_code == 200

    # 3. Inspect audit history via GET /api/v1/defects/{defect_id}/history
    res_hist = client.get(f"/api/v1/defects/{defect_id}/history", headers=auth_headers(reporter))
    assert res_hist.status_code == 200
    history = res_hist.json()

    # Must contain initial CREATED and the status transition to Triaged
    status_entries = [h for h in history if h["field_name"] == "status"]
    assert len(status_entries) >= 1

    triage_entry = status_entries[-1]
    assert triage_entry["defect_id"] == defect_id
    assert triage_entry["changed_by_user_id"] == qa_user.id
    assert triage_entry["action_type"] == AuditActionType.STATUS_CHANGED.value
    assert triage_entry["old_value"] == DefectStatus.OPEN.value
    assert triage_entry["new_value"] == DefectStatus.TRIAGED.value
    assert triage_entry["timestamp"] is not None
    assert triage_entry["version_snapshot"] >= 2


# ==============================================================================
# TC-HIST-002: Field edit generates audit delta
# ==============================================================================

def test_tc_hist_002_field_edit_generates_audit_delta(client, make_user, auth_headers):
    """TC-HIST-002: Updating title from Old Title to New Title captures field=title delta."""
    reporter = make_user(username="rep_hist_002", role=UserRole.REPORTER)
    old_title = "Initial Corrupted invoice generation title"
    new_title = "Updated and corrected invoice generation anomaly"

    # 1. Create defect
    res_create = client.post(
        "/api/v1/defects",
        json=_sample_valid_defect_payload(title=old_title),
        headers=auth_headers(reporter),
    )
    assert res_create.status_code == 201
    defect_id = res_create.json()["id"]

    # 2. Update title while still in Open status
    res_update = client.put(
        f"/api/v1/defects/{defect_id}",
        json={"title": new_title},
        headers=auth_headers(reporter),
    )
    assert res_update.status_code == 200

    # 3. Retrieve audit history
    res_hist = client.get(f"/api/v1/defects/{defect_id}/history", headers=auth_headers(reporter))
    assert res_hist.status_code == 200
    history = res_hist.json()

    # Find the title update entry
    title_entries = [h for h in history if h["field_name"] == "title"]
    assert len(title_entries) == 1
    entry = title_entries[0]
    assert entry["action_type"] == AuditActionType.UPDATED.value
    assert entry["old_value"] == old_title
    assert entry["new_value"] == new_title
    assert entry["changed_by_user_id"] == reporter.id
    assert entry["defect_id"] == defect_id


# ==============================================================================
# TC-HIST-003: Assignee change generates audit entry
# ==============================================================================

def test_tc_hist_003_assignee_change_generates_audit_entry(client, make_user, auth_headers):
    """TC-HIST-003: Defect assigned to Developer A, then Developer B logs both assignment transitions."""
    reporter = make_user(username="rep_hist_003", role=UserRole.REPORTER)
    qa_user = make_user(username="qa_hist_003", role=UserRole.QA_TRIAGE)
    dev_a = make_user(username="dev_hist_003a", role=UserRole.DEVELOPER)
    dev_b = make_user(username="dev_hist_003b", role=UserRole.DEVELOPER)

    # 1. Create & triage defect
    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=auth_headers(reporter))
    defect_id = res_create.json()["id"]
    client.post(f"/api/v1/defects/{defect_id}/triage", headers=auth_headers(qa_user))

    # 2. Assign to Developer A via QA coordinator
    res_assign_a = client.post(
        f"/api/v1/defects/{defect_id}/assign",
        json={"assignee_id": dev_a.id},
        headers=auth_headers(qa_user),
    )
    assert res_assign_a.status_code == 200

    # 3. Reassign to Developer B via QA coordinator
    res_assign_b = client.post(
        f"/api/v1/defects/{defect_id}/assign",
        json={"assignee_id": dev_b.id},
        headers=auth_headers(qa_user),
    )
    assert res_assign_b.status_code == 200

    # 4. Fetch history and verify assignment entries
    res_hist = client.get(f"/api/v1/defects/{defect_id}/history", headers=auth_headers(qa_user))
    assert res_hist.status_code == 200
    history = res_hist.json()

    assign_entries = [h for h in history if h["field_name"] == "assignee_id"]
    assert len(assign_entries) == 2

    # First assignment: None -> dev_a
    assert assign_entries[0]["action_type"] == AuditActionType.ASSIGNED.value
    assert assign_entries[0]["old_value"] is None
    assert assign_entries[0]["new_value"] == str(dev_a.id)

    # Second assignment: dev_a -> dev_b
    assert assign_entries[1]["action_type"] == AuditActionType.ASSIGNED.value
    assert assign_entries[1]["old_value"] == str(dev_a.id)
    assert assign_entries[1]["new_value"] == str(dev_b.id)


# ==============================================================================
# TC-HIST-004: History endpoint exposes complete sequence
# ==============================================================================

def test_tc_hist_004_complete_lifecycle_history_sequence(client, make_user, auth_headers):
    """TC-HIST-004: Defect transitions through 5 states; history returns complete chronological sequence."""
    reporter = make_user(username="rep_hist_004", role=UserRole.REPORTER)
    qa_user = make_user(username="qa_hist_004", role=UserRole.QA_TRIAGE)
    dev = make_user(username="dev_hist_004", role=UserRole.DEVELOPER)

    # State 1: Open (Created)
    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=auth_headers(reporter))
    assert res_create.status_code == 201
    defect_id = res_create.json()["id"]

    # State 2: Triaged
    res_triage = client.post(f"/api/v1/defects/{defect_id}/triage", headers=auth_headers(qa_user))
    assert res_triage.status_code == 200

    # State 3: Assigned (to dev)
    res_assign = client.post(
        f"/api/v1/defects/{defect_id}/assign",
        json={"assignee_id": dev.id},
        headers=auth_headers(qa_user),
    )
    assert res_assign.status_code == 200

    # State 4: In Progress (by dev)
    res_progress = client.post(
        f"/api/v1/defects/{defect_id}/transition",
        json={"target_status": DefectStatus.IN_PROGRESS.value},
        headers=auth_headers(dev),
    )
    assert res_progress.status_code == 200

    # State 5: Fixed (by dev)
    res_fixed = client.post(
        f"/api/v1/defects/{defect_id}/resolve",
        json={
            "root_cause": "Buffer overflow in currency format parsing routine.",
            "resolution_notes": "Patched buffer sizing to dynamic allocation and added bounds checking.",
            "fix_reference": "git commit 3a4f89b",
        },
        headers=auth_headers(dev),
    )
    assert res_fixed.status_code == 200

    # Retrieve complete history
    res_hist = client.get(f"/api/v1/defects/{defect_id}/history", headers=auth_headers(reporter))
    assert res_hist.status_code == 200
    history = res_hist.json()

    # Verify chronological sequence: IDs must be strictly monotonically increasing
    history_ids = [h["id"] for h in history]
    assert history_ids == sorted(history_ids)

    # Verify timestamps are monotonically non-decreasing
    timestamps = [h["timestamp"] for h in history]
    assert timestamps == sorted(timestamps)

    # Verify all FR-050 mandatory fields are present on every entry
    for entry in history:
        assert entry["id"] is not None
        assert entry["defect_id"] == defect_id
        assert entry["changed_by_user_id"] is not None
        assert entry["action_type"] in [
            AuditActionType.CREATED.value,
            AuditActionType.STATUS_CHANGED.value,
            AuditActionType.ASSIGNED.value,
            AuditActionType.UPDATED.value,
        ]
        assert entry["version_snapshot"] >= 1
        assert entry["timestamp"] is not None

    # Verify the sequential status progression in history
    status_seq = [h["new_value"] for h in history if h["field_name"] == "status" or h["action_type"] == "CREATED"]
    assert status_seq == [
        DefectStatus.OPEN.value,
        DefectStatus.TRIAGED.value,
        DefectStatus.ASSIGNED.value,
        DefectStatus.IN_PROGRESS.value,
        DefectStatus.FIXED.value,
    ]


# ==============================================================================
# TC-HIST-005: Audit log immutability check
# ==============================================================================

def test_tc_hist_005_audit_immutability(client, db_session, make_user, auth_headers):
    """TC-HIST-005: Direct API attempts to edit or delete audit records are rejected; direct DB update restricted."""
    reporter = make_user(username="rep_hist_005", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=headers)
    defect_id = res_create.json()["id"]

    # 1. API: PUT /api/v1/defects/{defect_id}/history must be rejected with 405 Method Not Allowed
    res_put = client.put(f"/api/v1/defects/{defect_id}/history", json={"field_name": "tampered"}, headers=headers)
    assert res_put.status_code == 405

    # 2. API: DELETE /api/v1/defects/{defect_id}/history must be rejected with 405 Method Not Allowed
    res_del = client.delete(f"/api/v1/defects/{defect_id}/history", headers=headers)
    assert res_del.status_code == 405

    # 3. API: POST /api/v1/defects/{defect_id}/history must be rejected with 405 Method Not Allowed
    res_post = client.post(f"/api/v1/defects/{defect_id}/history", json={"action": "inject"}, headers=headers)
    assert res_post.status_code == 405

    # 4. DB Layer Immutability: SQLAlchemy event listener blocks direct update on DefectHistory
    first_history = db_session.query(DefectHistory).filter(DefectHistory.defect_id == defect_id).first()
    assert first_history is not None
    first_history.new_value = "TamperedValue"
    with pytest.raises(ValueError, match="strictly immutable"):
        db_session.flush()


# ==============================================================================
# Additional Tests: Not Found, Auth, and Multi-Role Access
# ==============================================================================

def test_tc_hist_defect_not_found(client, make_user, auth_headers):
    """GET /api/v1/defects/DEF-9999/history returns HTTP 404 Not Found."""
    reporter = make_user(username="rep_hist_404", role=UserRole.REPORTER)
    res = client.get("/api/v1/defects/DEF-9999/history", headers=auth_headers(reporter))
    assert res.status_code == 404
    assert "Defect 'DEF-9999' not found" in res.json()["detail"]


def test_tc_hist_unauthenticated_rejected(client, make_user, auth_headers):
    """Unauthenticated access to history endpoint is rejected with HTTP 401."""
    reporter = make_user(username="rep_hist_401", role=UserRole.REPORTER)
    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=auth_headers(reporter))
    defect_id = res_create.json()["id"]

    res_no_auth = client.get(f"/api/v1/defects/{defect_id}/history")
    assert res_no_auth.status_code == 401


def test_tc_hist_all_roles_authorized(client, make_user, auth_headers):
    """All authenticated roles (Reporter, Developer, QA, Admin) are authorized to view defect history."""
    reporter = make_user(username="rep_hist_roles", role=UserRole.REPORTER)
    dev = make_user(username="dev_hist_roles", role=UserRole.DEVELOPER)
    qa = make_user(username="qa_hist_roles", role=UserRole.QA_TRIAGE)
    admin = make_user(username="admin_hist_roles", role=UserRole.ADMIN)

    res_create = client.post("/api/v1/defects", json=_sample_valid_defect_payload(), headers=auth_headers(reporter))
    defect_id = res_create.json()["id"]

    for user in [reporter, dev, qa, admin]:
        res = client.get(f"/api/v1/defects/{defect_id}/history", headers=auth_headers(user))
        assert res.status_code == 200
        assert len(res.json()) >= 1
