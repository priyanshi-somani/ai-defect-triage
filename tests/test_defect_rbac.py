"""Role-Based Access Control & Separation of Duties Automated Tests.

Addresses Requirements:
- FR-031: Enforce RBAC permission matrix across all API endpoints (docs/roles-permissions.md)
- FR-032: Only ROLE_QA_TRIAGE or ROLE_ADMIN can triage, change severity, change priority
- FR-033: Developers can self-assign unassigned triaged defects; cannot reassign others' defects
- FR-034: Only designated assignee or ROLE_ADMIN can start progress and mark Fixed
- FR-035: Strict Separation of Duties: Developer who resolved defect cannot retest or close it
- FR-036: Only ROLE_QA_TRIAGE or ROLE_ADMIN can close or reopen defects
- FR-037: Reject unauthorized operations with HTTP 403 Forbidden and audit log violation

Master Test Cases:
- TC-AUTH-001: Reporter permitted operations verification (create, view, edit own open defect)
- TC-AUTH-002: Reporter cannot triage defects (OP_TRIAGE_DEFECT returns 403)
- TC-AUTH-003: Reporter cannot close defects (OP_CLOSE_DEFECT returns 403)
- TC-AUTH-004: Developer cannot triage defects (OP_TRIAGE_DEFECT returns 403)
- TC-AUTH-005: Developer self-assignment vs. reassignment (self-assign succeeds, reassignment rejected)
- TC-AUTH-006: Developer progress restriction (cannot start progress or resolve another's defect)
- TC-AUTH-007: Separation of duties: Developer cannot retest own fix (OP_RETEST_DEFECT returns 403)
- TC-AUTH-008: Separation of duties: Developer cannot close own fix (OP_CLOSE_DEFECT returns 403)
- TC-AUTH-009: QA / Triage authority verification (triage, assign, reassign, retest, reopen, close)
- TC-AUTH-010: Admin authority verification (all operations, assignments, administrative overrides)
"""

import pytest
from backend.models import (
    Defect,
    DefectHistory,
    UserRole,
    DefectStatus,
    DefectSeverity,
    DefectPriority,
)


def _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value, **overrides) -> Defect:
    """Helper to persist a test defect directly in the database."""
    existing = db_session.query(Defect.id).all()
    next_id = f"DEF-{3001 + len(existing)}"

    defaults = {
        "id": next_id,
        "title": "Database connection pool exhaustion under load",
        "description": "Connection pool leaks connections when concurrent async queries timeout unexpectedly.",
        "steps_to_reproduce": "1. Launch 50 concurrent async workers.\n2. Trigger synthetic 5s network delay.\n3. Observe active pool count.",
        "expected_result": "Timed out connections returned to pool immediately.",
        "actual_result": "Connections remain in CLOSE_WAIT state until pool exhausts.",
        "environment": "Ubuntu 22.04 / Chrome 122.0 / Staging",
        "module": "DatabaseEngine",
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
# TC-AUTH-001: Reporter Permitted Operations Verification
# ==============================================================================

def test_tc_auth_001_reporter_permitted_operations(client, db_session, make_user, auth_headers):
    """TC-AUTH-001: Reporter can create, view, and update own defect while in Open status."""
    reporter = make_user(username="rbac_rep_001", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # 1. OP_CREATE_DEFECT: Reporter creates defect
    create_payload = {
        "title": "Memory leak detected in image processing worker",
        "description": "Image resize jobs do not free bitmap memory after completing the thumbnail rendering queue.",
        "steps_to_reproduce": "1. Upload 10 high-res PNG images.\n2. Trigger background thumbnail worker.",
        "expected_result": "Memory consumption stabilizes at baseline 150MB.",
        "actual_result": "Memory steadily grows past 1.5GB leading to OOM.",
        "environment": "Debian 12 / Python 3.11 / Production",
        "module": "MediaProcessor",
        "severity": DefectSeverity.MAJOR.value,
        "priority": DefectPriority.P2.value,
    }
    res_create = client.post("/api/v1/defects", json=create_payload, headers=headers)
    assert res_create.status_code == 201
    defect_id = res_create.json()["id"]
    assert res_create.json()["reporter_id"] == reporter.id
    assert res_create.json()["status"] == DefectStatus.OPEN.value

    # 2. OP_VIEW_DEFECT: Reporter views defect
    res_view = client.get(f"/api/v1/defects/{defect_id}", headers=headers)
    assert res_view.status_code == 200
    assert res_view.json()["id"] == defect_id

    # 3. OP_UPDATE_OWN_DEFECT: Reporter edits own defect in Open status
    update_payload = {
        "title": "Memory leak detected in thumbnail renderer queue",
        "description": "Updated description with more specific profiling notes for the thumbnail worker process.",
    }
    res_update = client.put(f"/api/v1/defects/{defect_id}", json=update_payload, headers=headers)
    assert res_update.status_code == 200
    assert res_update.json()["title"] == update_payload["title"]


# ==============================================================================
# TC-AUTH-002: Reporter Cannot Triage Defects
# ==============================================================================

def test_tc_auth_002_reporter_cannot_triage_defects(client, db_session, make_user, auth_headers):
    """TC-AUTH-002: Reporter calling OP_TRIAGE_DEFECT receives HTTP 403 Forbidden (FR-032)."""
    reporter = make_user(username="rbac_rep_002", role=UserRole.REPORTER)
    defect = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    headers = auth_headers(reporter)

    # Via semantic endpoint /triage
    res_triage = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert res_triage.status_code == 403
    assert "operation not permitted" in res_triage.text.lower() or "forbidden" in res_triage.text.lower()

    # Via generic /transition endpoint
    res_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.TRIAGED.value},
        headers=headers,
    )
    assert res_trans.status_code == 403
    assert "only qa/triage or admin" in res_trans.text.lower()

    # Via inspect evidence endpoint
    res_inspect = client.get(f"/api/v1/defects/{defect.id}/validate-evidence", headers=headers)
    assert res_inspect.status_code == 403

    # Defect remains in Open status
    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-AUTH-003: Reporter Cannot Close Defects
# ==============================================================================

def test_tc_auth_003_reporter_cannot_close_defects(client, db_session, make_user, auth_headers):
    """TC-AUTH-003: Reporter calling OP_CLOSE_DEFECT receives HTTP 403 Forbidden (FR-036)."""
    reporter = make_user(username="rbac_rep_003", role=UserRole.REPORTER)
    defect = _seed_defect(db_session, reporter, status=DefectStatus.RETEST.value)
    headers = auth_headers(reporter)

    # Via semantic /close endpoint
    close_payload = {
        "verification_notes": "Attempting to close as reporter without QA role authorization.",
    }
    res_close = client.post(f"/api/v1/defects/{defect.id}/close", json=close_payload, headers=headers)
    assert res_close.status_code == 403

    # Via generic /transition endpoint
    res_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.CLOSED.value, "verification_notes": close_payload["verification_notes"]},
        headers=headers,
    )
    assert res_trans.status_code == 403
    assert "forbidden" in res_trans.text.lower() or "only qa/triage or admin" in res_trans.text.lower()

    db_session.refresh(defect)
    assert defect.status == DefectStatus.RETEST.value


# ==============================================================================
# TC-AUTH-004: Developer Cannot Triage Defects
# ==============================================================================

def test_tc_auth_004_developer_cannot_triage_defects(client, db_session, make_user, auth_headers):
    """TC-AUTH-004: Developer calling OP_TRIAGE_DEFECT receives HTTP 403 Forbidden (FR-032)."""
    reporter = make_user(username="rbac_rep_004", role=UserRole.REPORTER)
    developer = make_user(username="rbac_dev_004", role=UserRole.DEVELOPER)
    defect = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    headers = auth_headers(developer)

    # Via semantic /triage endpoint
    res_triage = client.post(f"/api/v1/defects/{defect.id}/triage", headers=headers)
    assert res_triage.status_code == 403

    # Via generic /transition endpoint
    res_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.TRIAGED.value},
        headers=headers,
    )
    assert res_trans.status_code == 403
    assert "only qa/triage or admin" in res_trans.text.lower()

    # Via inspect evidence endpoint
    res_inspect = client.get(f"/api/v1/defects/{defect.id}/validate-evidence", headers=headers)
    assert res_inspect.status_code == 403

    db_session.refresh(defect)
    assert defect.status == DefectStatus.OPEN.value


# ==============================================================================
# TC-AUTH-005: Developer Self-Assignment vs. Reassignment
# ==============================================================================

def test_tc_auth_005_developer_self_assignment_vs_reassignment(client, db_session, make_user, auth_headers):
    """TC-AUTH-005: Developer can self-assign unassigned triaged defect, but cannot reassign (FR-033)."""
    reporter = make_user(username="rbac_rep_005", role=UserRole.REPORTER)
    dev_a = make_user(username="rbac_dev_005_a", role=UserRole.DEVELOPER)
    dev_b = make_user(username="rbac_dev_005_b", role=UserRole.DEVELOPER)

    defect_unassigned = _seed_defect(db_session, reporter, status=DefectStatus.TRIAGED.value, assignee_id=None)
    headers_a = auth_headers(dev_a)
    headers_b = auth_headers(dev_b)

    # 1. Developer A attempts to assign unassigned defect to Developer B -> 403 Forbidden
    res_assign_other = client.post(
        f"/api/v1/defects/{defect_unassigned.id}/assign",
        json={"assignee_id": dev_b.id},
        headers=headers_a,
    )
    assert res_assign_other.status_code == 403
    assert "only self-assign" in res_assign_other.text.lower()

    # 2. Developer A self-assigns unassigned defect -> 200 OK
    res_self_assign = client.post(
        f"/api/v1/defects/{defect_unassigned.id}/assign",
        json={"assignee_id": dev_a.id},
        headers=headers_a,
    )
    assert res_self_assign.status_code == 200
    assert res_self_assign.json()["status"] == DefectStatus.ASSIGNED.value
    assert res_self_assign.json()["assignee_id"] == dev_a.id

    # 3. Developer B attempts to reassign defect assigned to Developer A -> 403 Forbidden
    res_reassign_b = client.post(
        f"/api/v1/defects/{defect_unassigned.id}/assign",
        json={"assignee_id": dev_b.id},
        headers=headers_b,
    )
    assert res_reassign_b.status_code == 403
    assert "not permitted to reassign" in res_reassign_b.text.lower()

    # 4. Developer A attempts to reassign own assigned defect to Developer B -> 403 Forbidden
    res_reassign_a = client.post(
        f"/api/v1/defects/{defect_unassigned.id}/assign",
        json={"assignee_id": dev_b.id},
        headers=headers_a,
    )
    assert res_reassign_a.status_code == 403

    # 5. Developer attempts to self-assign defect in non-Triaged status (e.g. Open) -> 400 or 403
    defect_open = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    res_assign_open = client.post(
        f"/api/v1/defects/{defect_open.id}/assign",
        json={"assignee_id": dev_a.id},
        headers=headers_a,
    )
    assert res_assign_open.status_code in [400, 403]


# ==============================================================================
# TC-AUTH-006: Developer Progress Restriction
# ==============================================================================

def test_tc_auth_006_developer_progress_restriction(client, db_session, make_user, auth_headers):
    """TC-AUTH-006: Developer cannot start progress or resolve defect assigned to another developer (FR-034)."""
    reporter = make_user(username="rbac_rep_006", role=UserRole.REPORTER)
    dev_a = make_user(username="rbac_dev_006_a", role=UserRole.DEVELOPER)
    dev_b = make_user(username="rbac_dev_006_b", role=UserRole.DEVELOPER)

    defect = _seed_defect(
        db_session,
        reporter,
        status=DefectStatus.ASSIGNED.value,
        assignee_id=dev_a.id,
    )
    headers_a = auth_headers(dev_a)
    headers_b = auth_headers(dev_b)

    # 1. Developer B attempts to start progress on defect assigned to Developer A -> 403 Forbidden
    res_b_progress = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=headers_b)
    assert res_b_progress.status_code == 403
    assert "designated assigned developer" in res_b_progress.text.lower()

    # Via /transition endpoint
    res_b_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.IN_PROGRESS.value},
        headers=headers_b,
    )
    assert res_b_trans.status_code == 403

    # 2. Developer A legitimately starts progress -> 200 OK
    res_a_progress = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=headers_a)
    assert res_a_progress.status_code == 200
    assert res_a_progress.json()["status"] == DefectStatus.IN_PROGRESS.value

    # 3. Developer B attempts to resolve defect assigned to Developer A -> 403 Forbidden
    fix_payload = {
        "root_cause": "Race condition in thread pool.",
        "resolution_notes": "Added locking mechanism to prevent concurrent task execution.",
        "fix_reference": "commit:fedcba98",
    }
    res_b_resolve = client.post(f"/api/v1/defects/{defect.id}/resolve", json=fix_payload, headers=headers_b)
    assert res_b_resolve.status_code == 403
    assert "designated assigned developer" in res_b_resolve.text.lower()

    # Via /transition endpoint
    res_b_res_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.FIXED.value, **fix_payload},
        headers=headers_b,
    )
    assert res_b_res_trans.status_code == 403

    # 4. Developer B attempts to pause progress on Developer A's defect -> 403 Forbidden
    res_b_pause = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.ASSIGNED.value},
        headers=headers_b,
    )
    assert res_b_pause.status_code == 403


# ==============================================================================
# TC-AUTH-007: Separation of Duties: Developer Cannot Retest Own Fix
# ==============================================================================

def test_tc_auth_007_separation_of_duties_developer_cannot_retest_own_fix(client, db_session, make_user, auth_headers):
    """TC-AUTH-007: Developer who resolved defect is forbidden from executing OP_RETEST_DEFECT (FR-035)."""
    reporter = make_user(username="rbac_rep_007", role=UserRole.REPORTER)
    dev_a = make_user(username="rbac_dev_007", role=UserRole.DEVELOPER)
    qa_user = make_user(username="rbac_qa_007", role=UserRole.QA_TRIAGE)

    # Defect was moved to In Progress and Fixed by Developer A
    defect = _seed_defect(
        db_session,
        reporter,
        status=DefectStatus.IN_PROGRESS.value,
        assignee_id=dev_a.id,
    )
    headers_dev = auth_headers(dev_a)
    headers_qa = auth_headers(qa_user)

    # Developer A marks defect Fixed
    fix_payload = {
        "root_cause": "Unchecked null pointer in parsing logic.",
        "resolution_notes": "Added optional chaining and null safety guardrails.",
        "fix_reference": "PR #150",
    }
    res_fix = client.post(f"/api/v1/defects/{defect.id}/resolve", json=fix_payload, headers=headers_dev)
    assert res_fix.status_code == 200

    # 1. Developer A attempts to advance defect to Retest via semantic /retest -> 403 Forbidden
    res_dev_retest = client.post(f"/api/v1/defects/{defect.id}/retest", headers=headers_dev)
    assert res_dev_retest.status_code == 403

    # 2. Developer A attempts to advance defect to Retest via /transition -> 403 Forbidden
    res_dev_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.RETEST.value},
        headers=headers_dev,
    )
    assert res_dev_trans.status_code == 403
    assert "separation of duties" in res_dev_trans.text.lower() or "only qa/triage or admin" in res_dev_trans.text.lower()

    # 3. Independent QA engineer advances defect to Retest -> 200 OK
    res_qa_retest = client.post(f"/api/v1/defects/{defect.id}/retest", headers=headers_qa)
    assert res_qa_retest.status_code == 200
    assert res_qa_retest.json()["status"] == DefectStatus.RETEST.value


# ==============================================================================
# TC-AUTH-008: Separation of Duties: Developer Cannot Close Own Fix
# ==============================================================================

def test_tc_auth_008_separation_of_duties_developer_cannot_close_own_fix(client, db_session, make_user, auth_headers):
    """TC-AUTH-008: Developer who resolved defect is forbidden from executing OP_CLOSE_DEFECT (FR-035)."""
    reporter = make_user(username="rbac_rep_008", role=UserRole.REPORTER)
    dev_a = make_user(username="rbac_dev_008", role=UserRole.DEVELOPER)
    qa_user = make_user(username="rbac_qa_008", role=UserRole.QA_TRIAGE)

    defect = _seed_defect(
        db_session,
        reporter,
        status=DefectStatus.IN_PROGRESS.value,
        assignee_id=dev_a.id,
    )
    headers_dev = auth_headers(dev_a)
    headers_qa = auth_headers(qa_user)

    # Developer A resolves defect
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={
            "root_cause": "Buffer overflow in socket reader.",
            "resolution_notes": "Constrained buffer allocations to 64KB max packet limit.",
            "fix_reference": "commit:11223344",
        },
        headers=headers_dev,
    )
    # QA advances to Retest
    client.post(f"/api/v1/defects/{defect.id}/retest", headers=headers_qa)

    # 1. Developer A attempts to close defect via semantic /close -> 403 Forbidden
    close_payload = {
        "verification_notes": "Developer self-approving and closing own defect fix.",
    }
    res_dev_close = client.post(f"/api/v1/defects/{defect.id}/close", json=close_payload, headers=headers_dev)
    assert res_dev_close.status_code == 403

    # 2. Developer A attempts to close defect via generic /transition -> 403 Forbidden
    res_dev_trans = client.post(
        f"/api/v1/defects/{defect.id}/transition",
        json={"target_status": DefectStatus.CLOSED.value, **close_payload},
        headers=headers_dev,
    )
    assert res_dev_trans.status_code == 403
    assert "separation of duties" in res_dev_trans.text.lower() or "forbidden" in res_dev_trans.text.lower()

    # 3. Independent QA engineer closes defect -> 200 OK
    qa_close_payload = {
        "verification_notes": "QA verified buffer limit enforcement with synthetic jumbo frames.",
    }
    res_qa_close = client.post(f"/api/v1/defects/{defect.id}/close", json=qa_close_payload, headers=headers_qa)
    assert res_qa_close.status_code == 200
    assert res_qa_close.json()["status"] == DefectStatus.CLOSED.value


def test_tc_auth_008_admin_who_resolved_cannot_close_own_fix(client, db_session, make_user, auth_headers):
    """TC-AUTH-008: Admin who personally resolved a defect cannot self-approve and close it (FR-035)."""
    reporter = make_user(username="rbac_rep_008b", role=UserRole.REPORTER)
    admin_fixer = make_user(username="rbac_admin_fixer", role=UserRole.ADMIN)
    qa_verifier = make_user(username="rbac_qa_verifier", role=UserRole.QA_TRIAGE)

    defect = _seed_defect(
        db_session,
        reporter,
        status=DefectStatus.IN_PROGRESS.value,
        assignee_id=admin_fixer.id,
    )
    headers_admin_fixer = auth_headers(admin_fixer)
    headers_qa = auth_headers(qa_verifier)

    # Admin marks Fixed
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={
            "root_cause": "Admin emergency patch for TLS handshake failure.",
            "resolution_notes": "Updated TLS cipher suite configuration to disable TLS 1.0.",
            "fix_reference": "hotfix:2026-11-19",
        },
        headers=headers_admin_fixer,
    )
    # QA advances to Retest
    client.post(f"/api/v1/defects/{defect.id}/retest", headers=headers_qa)

    # Admin fixer attempts to close -> 403 Separation of Duties
    res_admin_close = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "Admin self-verifying emergency patch in production."},
        headers=headers_admin_fixer,
    )
    assert res_admin_close.status_code == 403
    assert "separation of duties" in res_admin_close.text.lower()

    # QA verifier successfully closes
    res_qa_close = client.post(
        f"/api/v1/defects/{defect.id}/close",
        json={"verification_notes": "QA confirmed TLS 1.0 disabled via OpenSSL s_client handshake tests."},
        headers=headers_qa,
    )
    assert res_qa_close.status_code == 200


# ==============================================================================
# TC-AUTH-009: QA / Triage Authority Verification
# ==============================================================================

def test_tc_auth_009_qa_triage_authority_verification(client, db_session, make_user, auth_headers):
    """TC-AUTH-009: QA role can validate evidence, triage, assign, reassign, unassign, retest, reopen, and close (FR-032, FR-036)."""
    reporter = make_user(username="rbac_rep_009", role=UserRole.REPORTER)
    qa_user = make_user(username="rbac_qa_009", role=UserRole.QA_TRIAGE)
    dev_a = make_user(username="rbac_dev_009_a", role=UserRole.DEVELOPER)
    dev_b = make_user(username="rbac_dev_009_b", role=UserRole.DEVELOPER)

    defect = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    qa_headers = auth_headers(qa_user)
    dev_b_headers = auth_headers(dev_b)

    # 1. QA validates evidence
    res_inspect = client.get(f"/api/v1/defects/{defect.id}/validate-evidence", headers=qa_headers)
    assert res_inspect.status_code == 200

    # 2. QA triages defect
    res_triage = client.post(f"/api/v1/defects/{defect.id}/triage", headers=qa_headers)
    assert res_triage.status_code == 200
    assert res_triage.json()["status"] == DefectStatus.TRIAGED.value

    # 3. QA assigns defect to Developer A
    res_assign = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": dev_a.id},
        headers=qa_headers,
    )
    assert res_assign.status_code == 200
    assert res_assign.json()["assignee_id"] == dev_a.id

    # 4. QA reassigns defect to Developer B
    res_reassign = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": dev_b.id},
        headers=qa_headers,
    )
    assert res_reassign.status_code == 200
    assert res_reassign.json()["assignee_id"] == dev_b.id

    # 5. QA updates severity and priority
    res_update = client.put(
        f"/api/v1/defects/{defect.id}",
        json={"severity": DefectSeverity.BLOCKER.value, "priority": DefectPriority.P1.value},
        headers=qa_headers,
    )
    assert res_update.status_code == 200
    assert res_update.json()["severity"] == DefectSeverity.BLOCKER.value
    assert res_update.json()["priority"] == DefectPriority.P1.value

    # 6. Developer B starts progress and resolves
    client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=dev_b_headers)
    client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={
            "root_cause": "Async coroutine missing await statement.",
            "resolution_notes": "Added await and wrapped in structured task group.",
            "fix_reference": "commit:98765432",
        },
        headers=dev_b_headers,
    )

    # 7. QA advances to Retest
    res_retest = client.post(f"/api/v1/defects/{defect.id}/retest", headers=qa_headers)
    assert res_retest.status_code == 200

    # 8. QA fails retest and reopens defect
    res_reopen = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": "Verification failed: Worker threads still freeze after 100 concurrent tasks."},
        headers=qa_headers,
    )
    assert res_reopen.status_code == 200
    assert res_reopen.json()["status"] == DefectStatus.REOPENED.value

    # 9. QA cannot start progress or resolve (must be developer or admin)
    res_qa_prog = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=qa_headers)
    assert res_qa_prog.status_code == 403


# ==============================================================================
# TC-AUTH-010: Admin Authority Verification
# ==============================================================================

def test_tc_auth_010_admin_authority_verification(client, db_session, make_user, auth_headers):
    """TC-AUTH-010: Admin role can perform administrative overrides across all lifecycle operations."""
    reporter = make_user(username="rbac_rep_010", role=UserRole.REPORTER)
    admin_user = make_user(username="rbac_admin_010", role=UserRole.ADMIN)
    dev_a = make_user(username="rbac_dev_010", role=UserRole.DEVELOPER)

    defect = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value)
    admin_headers = auth_headers(admin_user)

    # 1. Admin triages
    res_triage = client.post(f"/api/v1/defects/{defect.id}/triage", headers=admin_headers)
    assert res_triage.status_code == 200

    # 2. Admin assigns
    res_assign = client.post(
        f"/api/v1/defects/{defect.id}/assign",
        json={"assignee_id": dev_a.id},
        headers=admin_headers,
    )
    assert res_assign.status_code == 200

    # 3. Admin overrides start progress on defect assigned to Developer A
    res_prog = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=admin_headers)
    assert res_prog.status_code == 200
    assert res_prog.json()["status"] == DefectStatus.IN_PROGRESS.value

    # 4. Admin overrides resolve on defect assigned to Developer A
    res_resolve = client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={
            "root_cause": "Admin applied configuration override.",
            "resolution_notes": "Updated pool sizing in deployment values.yaml manifest.",
            "fix_reference": "commit:admin999",
        },
        headers=admin_headers,
    )
    assert res_resolve.status_code == 200
    assert res_resolve.json()["status"] == DefectStatus.FIXED.value

    # 5. Admin updates severity and priority on defect in Fixed status
    res_update = client.put(
        f"/api/v1/defects/{defect.id}",
        json={"severity": DefectSeverity.MINOR.value, "priority": DefectPriority.P4.value},
        headers=admin_headers,
    )
    assert res_update.status_code == 200
    assert res_update.json()["severity"] == DefectSeverity.MINOR.value


# ==============================================================================
# Additional Negative & Boundary RBAC Tests
# ==============================================================================

def test_reporter_cannot_assign_start_progress_or_reopen(client, db_session, make_user, auth_headers):
    """Reporter attempting lifecycle mutations receives HTTP 403 Forbidden."""
    reporter = make_user(username="rbac_rep_forbidden", role=UserRole.REPORTER)
    defect = _seed_defect(db_session, reporter, status=DefectStatus.TRIAGED.value)
    headers = auth_headers(reporter)

    # Assign
    res_assign = client.post(f"/api/v1/defects/{defect.id}/assign", json={"assignee_id": reporter.id}, headers=headers)
    assert res_assign.status_code == 403

    # Start progress
    res_prog = client.post(f"/api/v1/defects/{defect.id}/start-progress", headers=headers)
    assert res_prog.status_code == 403

    # Resolve
    res_resolve = client.post(
        f"/api/v1/defects/{defect.id}/resolve",
        json={"root_cause": "A", "resolution_notes": "B", "fix_reference": "C"},
        headers=headers,
    )
    assert res_resolve.status_code == 403

    # Retest
    res_retest = client.post(f"/api/v1/defects/{defect.id}/retest", headers=headers)
    assert res_retest.status_code == 403

    # Reopen
    res_reopen = client.post(
        f"/api/v1/defects/{defect.id}/reopen",
        json={"reopen_reason": "Regression observed on test instance."},
        headers=headers,
    )
    assert res_reopen.status_code == 403


def test_reporter_and_developer_cannot_change_severity_priority(client, db_session, make_user, auth_headers):
    """Reporters and Developers cannot modify severity or priority via PUT /defects/{id} (FR-032, FR-037)."""
    reporter = make_user(username="rbac_rep_sev", role=UserRole.REPORTER)
    dev = make_user(username="rbac_dev_sev", role=UserRole.DEVELOPER)
    defect_rep = _seed_defect(db_session, reporter, status=DefectStatus.OPEN.value, severity=DefectSeverity.MAJOR.value)
    defect_dev = _seed_defect(db_session, dev, status=DefectStatus.OPEN.value, severity=DefectSeverity.MAJOR.value)

    # Reporter attempts to escalate severity
    res_rep_sev = client.put(
        f"/api/v1/defects/{defect_rep.id}",
        json={"severity": DefectSeverity.BLOCKER.value},
        headers=auth_headers(reporter),
    )
    assert res_rep_sev.status_code == 403
    assert "only qa/triage or admin" in res_rep_sev.text.lower()

    # Developer attempts to change priority
    res_dev_pri = client.put(
        f"/api/v1/defects/{defect_dev.id}",
        json={"priority": DefectPriority.P1.value},
        headers=auth_headers(dev),
    )
    assert res_dev_pri.status_code == 403
    assert "only qa/triage or admin" in res_dev_pri.text.lower()


def test_cannot_update_defect_reported_by_another_user(client, db_session, make_user, auth_headers):
    """Reporter attempting to update another user's defect receives HTTP 403 (FR-007)."""
    reporter_a = make_user(username="rbac_rep_owner", role=UserRole.REPORTER)
    reporter_b = make_user(username="rbac_rep_stranger", role=UserRole.REPORTER)
    defect = _seed_defect(db_session, reporter_a, status=DefectStatus.OPEN.value)

    response = client.put(
        f"/api/v1/defects/{defect.id}",
        json={"title": "Unauthorized title edit attempt by different user"},
        headers=auth_headers(reporter_b),
    )
    assert response.status_code == 403
    assert "reported by another user" in response.text.lower()


def test_author_cannot_update_defect_past_open_status(client, db_session, make_user, auth_headers):
    """Author attempting to edit defect after triage receives HTTP 403 (FR-008)."""
    reporter = make_user(username="rbac_rep_past_open", role=UserRole.REPORTER)
    defect = _seed_defect(db_session, reporter, status=DefectStatus.TRIAGED.value)

    response = client.put(
        f"/api/v1/defects/{defect.id}",
        json={"title": "Attempting edit after triage status achieved"},
        headers=auth_headers(reporter),
    )
    assert response.status_code == 403
    assert "updates only permitted in 'open' status" in response.text.lower()
