"""Automated test suite for Defect Search, Filtering, Sorting, and Pagination.

Addresses Requirements:
- FR-041: Exact Defect ID search and case-insensitive Title/Description substring search.
- FR-042: Compound multi-attribute filtering by Status, Severity, Priority, Module, Assignee, Reporter, and Creation Date Range.
- FR-043: Paginated responses with default page size 20, customizable up to 100 records.
- FR-044: Sorting results by created_at, updated_at, severity, and priority in ascending or descending order.
- OP_VIEW_DEFECT: Search and defect list access permitted for all authenticated roles (Reporter, Developer, QA/Triage, Admin).

Test Cases:
- TC-SRCH-001: Search by exact Defect ID (found, alternate param, not found).
- TC-SRCH-002: Search by keyword substring (title match, description match, case-insensitivity, no match).
- TC-SRCH-003: Multi-attribute compound filtering (status, severity, priority combinations).
- TC-SRCH-004: Filter by Assignee, Reporter, and Module (subsets and combinations).
- TC-SRCH-005: Pagination behavior and boundaries (default 20, page 2 navigation, max 100, boundary violations >100, <1).
- TC-SRCH-006: Sorting results (created_at DESC/ASC, severity ASC/DESC, priority ASC, compound sorting, invalid field/order).
- Additional: Creation date range filtering (created_after, created_before).
- Additional: Authentication and role-based access checks (unauthenticated 401, all roles 200).
"""

from datetime import datetime, timezone, timedelta
import pytest
from backend.models.enums import UserRole, DefectStatus, DefectSeverity, DefectPriority
from backend.models.defect import Defect


def _create_defect_record(
    db_session,
    defect_id: str,
    title: str,
    description: str,
    module: str,
    severity: DefectSeverity,
    priority: DefectPriority,
    status: DefectStatus,
    reporter_id: int,
    assignee_id: int = None,
    created_at: datetime = None,
    updated_at: datetime = None,
) -> Defect:
    """Helper to insert a fully configured Defect entity directly into db_session."""
    now = datetime.now(timezone.utc)
    defect = Defect(
        id=defect_id,
        title=title,
        description=description,
        steps_to_reproduce="1. Step one reproduction\n2. Step two reproduction",
        expected_result="Operation completes with valid state",
        actual_result="Operation terminates with observed anomaly",
        environment="Ubuntu 22.04 / Chrome 124 / Staging",
        module=module,
        severity=severity.value if isinstance(severity, DefectSeverity) else str(severity),
        priority=priority.value if isinstance(priority, DefectPriority) else str(priority),
        status=status.value if isinstance(status, DefectStatus) else str(status),
        reporter_id=reporter_id,
        assignee_id=assignee_id,
        version=1,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )
    db_session.add(defect)
    db_session.flush()
    return defect


@pytest.fixture
def seeded_defects(db_session, make_user):
    """Seed a representative corpus of defects with diverse attributes for search/filter tests."""
    reporter1 = make_user(username="reporter_alpha", email="rep_alpha@example.com", role=UserRole.REPORTER)
    reporter2 = make_user(username="reporter_beta", email="rep_beta@example.com", role=UserRole.REPORTER)
    dev1 = make_user(username="dev_alpha", email="dev_alpha@example.com", role=UserRole.DEVELOPER)
    dev2 = make_user(username="dev_beta", email="dev_beta@example.com", role=UserRole.DEVELOPER)

    t0 = datetime(2026, 1, 1, 10, 0, 0)
    t1 = datetime(2026, 1, 2, 10, 0, 0)
    t2 = datetime(2026, 1, 3, 10, 0, 0)
    t3 = datetime(2026, 1, 4, 10, 0, 0)
    t4 = datetime(2026, 1, 5, 10, 0, 0)

    # Defect 1: Blocker / P1 / Open / Billing / reporter1 / unassigned
    d1 = _create_defect_record(
        db_session,
        defect_id="DEF-1001",
        title="NullPointerException in Payment Gateway",
        description="When processing refund transactions exceeding $1000, null pointer occurs.",
        module="Billing",
        severity=DefectSeverity.BLOCKER,
        priority=DefectPriority.P1,
        status=DefectStatus.OPEN,
        reporter_id=reporter1.id,
        assignee_id=None,
        created_at=t0,
        updated_at=t0,
    )

    # Defect 2: Critical / P2 / Triaged / Checkout / reporter1 / dev1
    d2 = _create_defect_record(
        db_session,
        defect_id="DEF-1002",
        title="Database deadlock during concurrent checkout",
        description="High volume concurrent checkouts cause database lock timeout and HTTP 500 error.",
        module="Checkout",
        severity=DefectSeverity.CRITICAL,
        priority=DefectPriority.P2,
        status=DefectStatus.TRIAGED,
        reporter_id=reporter1.id,
        assignee_id=dev1.id,
        created_at=t1,
        updated_at=t1,
    )

    # Defect 3: Minor / P3 / Open / Frontend / reporter2 / unassigned
    d3 = _create_defect_record(
        db_session,
        defect_id="DEF-1003",
        title="CSS layout shift on user profile page",
        description="Navbar shifts downward by 20px on mobile screen refresh.",
        module="Frontend",
        severity=DefectSeverity.MINOR,
        priority=DefectPriority.P3,
        status=DefectStatus.OPEN,
        reporter_id=reporter2.id,
        assignee_id=None,
        created_at=t2,
        updated_at=t2,
    )

    # Defect 4: Trivial / P4 / Closed / Frontend / reporter2 / dev2
    d4 = _create_defect_record(
        db_session,
        defect_id="DEF-1004",
        title="Typo in landing page footer disclaimer",
        description="Spelling error in legal copyright notice text on main landing footer.",
        module="Frontend",
        severity=DefectSeverity.TRIVIAL,
        priority=DefectPriority.P4,
        status=DefectStatus.CLOSED,
        reporter_id=reporter2.id,
        assignee_id=dev2.id,
        created_at=t3,
        updated_at=t3,
    )

    # Defect 5: Blocker / P1 / Open / Storage / reporter1 / dev1
    d5 = _create_defect_record(
        db_session,
        defect_id="DEF-1005",
        title="Memory leak during batch file export loop",
        description="Garbage collector fails to reclaim socket buffers during bulk file export operations.",
        module="Storage",
        severity=DefectSeverity.BLOCKER,
        priority=DefectPriority.P1,
        status=DefectStatus.OPEN,
        reporter_id=reporter1.id,
        assignee_id=dev1.id,
        created_at=t4,
        updated_at=t4,
    )

    return {
        "reporter1": reporter1,
        "reporter2": reporter2,
        "dev1": dev1,
        "dev2": dev2,
        "d1": d1,
        "d2": d2,
        "d3": d3,
        "d4": d4,
        "d5": d5,
        "dates": [t0, t1, t2, t3, t4],
    }


# ==============================================================================
# TC-SRCH-001: Search by exact Defect ID
# ==============================================================================

def test_tc_srch_001_exact_id_search(client, seeded_defects, auth_headers):
    """TC-SRCH-001: Query parameter id=DEF-1001 returns exactly the matching defect."""
    headers = auth_headers(seeded_defects["reporter1"])

    # 1. Exact match with 'id' parameter
    res = client.get("/api/v1/defects?id=DEF-1001", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "DEF-1001"
    assert data["items"][0]["title"] == "NullPointerException in Payment Gateway"
    assert data["defects"][0]["id"] == "DEF-1001"

    # 2. Exact match with 'defect_id' parameter alias
    res_alias = client.get("/api/v1/defects?defect_id=DEF-1002", headers=headers)
    assert res_alias.status_code == 200
    data_alias = res_alias.json()
    assert data_alias["total"] == 1
    assert data_alias["items"][0]["id"] == "DEF-1002"

    # 3. Non-existent defect ID returns empty items list with total=0
    res_none = client.get("/api/v1/defects?id=DEF-9999", headers=headers)
    assert res_none.status_code == 200
    data_none = res_none.json()
    assert data_none["total"] == 0
    assert len(data_none["items"]) == 0
    assert data_none["total_pages"] == 0


# ==============================================================================
# TC-SRCH-002: Search by keyword substring
# ==============================================================================

def test_tc_srch_002_keyword_substring_search(client, seeded_defects, auth_headers):
    """TC-SRCH-002: Keyword present in Title or Description returns case-insensitive matches."""
    headers = auth_headers(seeded_defects["reporter1"])

    # 1. Match in Title ("Payment")
    res_title = client.get("/api/v1/defects?q=Payment", headers=headers)
    assert res_title.status_code == 200
    data = res_title.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "DEF-1001"

    # 2. Match in Description ("refund")
    res_desc = client.get("/api/v1/defects?q=refund", headers=headers)
    assert res_desc.status_code == 200
    data_desc = res_desc.json()
    assert data_desc["total"] == 1
    assert data_desc["items"][0]["id"] == "DEF-1001"

    # 3. Case-insensitivity verification ("pAyMeNt")
    res_case = client.get("/api/v1/defects?q=pAyMeNt", headers=headers)
    assert res_case.status_code == 200
    assert res_case.json()["total"] == 1
    assert res_case.json()["items"][0]["id"] == "DEF-1001"

    # 4. Multi-match search ("error" appears in DEF-1002 description and DEF-1004 description)
    res_multi = client.get("/api/v1/defects?q=error", headers=headers)
    assert res_multi.status_code == 200
    matched_ids = {item["id"] for item in res_multi.json()["items"]}
    assert "DEF-1002" in matched_ids
    assert "DEF-1004" in matched_ids

    # 5. Non-matching keyword returns total=0
    res_nomatch = client.get("/api/v1/defects?q=NonExistentZebraTerm", headers=headers)
    assert res_nomatch.status_code == 200
    assert res_nomatch.json()["total"] == 0
    assert len(res_nomatch.json()["items"]) == 0


# ==============================================================================
# TC-SRCH-003: Multi-attribute compound filtering
# ==============================================================================

def test_tc_srch_003_compound_filtering(client, seeded_defects, auth_headers):
    """TC-SRCH-003: Filter by status=Open, severity=Blocker, priority=P1."""
    headers = auth_headers(seeded_defects["reporter1"])

    # Matches DEF-1001 and DEF-1005 (both Open, Blocker, P1-Immediate)
    res = client.get(
        "/api/v1/defects?status=Open&severity=Blocker&priority=P1",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    matched_ids = {d["id"] for d in data["items"]}
    assert matched_ids == {"DEF-1001", "DEF-1005"}
    for item in data["items"]:
        assert item["status"] == DefectStatus.OPEN.value
        assert item["severity"] == DefectSeverity.BLOCKER.value
        assert item["priority"] == DefectPriority.P1.value

    # Full priority string variant ("P1-Immediate")
    res_full = client.get(
        "/api/v1/defects?status=Open&severity=Blocker&priority=P1-Immediate",
        headers=headers,
    )
    assert res_full.status_code == 200
    assert res_full.json()["total"] == 2

    # Disjoint combination returns empty set
    res_empty = client.get(
        "/api/v1/defects?status=Open&severity=Blocker&priority=P3",
        headers=headers,
    )
    assert res_empty.status_code == 200
    assert res_empty.json()["total"] == 0
    assert len(res_empty.json()["items"]) == 0


# ==============================================================================
# TC-SRCH-004: Filter by Assignee, Reporter, Module
# ==============================================================================

def test_tc_srch_004_filter_by_assignee_reporter_module(client, seeded_defects, auth_headers):
    """TC-SRCH-004: Filter by combinations of user and module IDs."""
    headers = auth_headers(seeded_defects["reporter1"])
    rep1_id = seeded_defects["reporter1"].id
    rep2_id = seeded_defects["reporter2"].id
    dev1_id = seeded_defects["dev1"].id

    # 1. Filter by Module ("Frontend") -> DEF-1003, DEF-1004
    res_mod = client.get("/api/v1/defects?module=Frontend", headers=headers)
    assert res_mod.status_code == 200
    mod_ids = {d["id"] for d in res_mod.json()["items"]}
    assert mod_ids == {"DEF-1003", "DEF-1004"}

    # Case-insensitive module matching
    res_mod_ci = client.get("/api/v1/defects?module=frontend", headers=headers)
    assert res_mod_ci.status_code == 200
    assert res_mod_ci.json()["total"] == 2

    # 2. Filter by Reporter ID (reporter1 authored DEF-1001, DEF-1002, DEF-1005)
    res_rep = client.get(f"/api/v1/defects?reporter_id={rep1_id}", headers=headers)
    assert res_rep.status_code == 200
    assert res_rep.json()["total"] == 3
    rep_ids = {d["id"] for d in res_rep.json()["items"]}
    assert rep_ids == {"DEF-1001", "DEF-1002", "DEF-1005"}

    # 3. Filter by Assignee ID (dev1 assigned DEF-1002, DEF-1005)
    res_ass = client.get(f"/api/v1/defects?assignee_id={dev1_id}", headers=headers)
    assert res_ass.status_code == 200
    assert res_ass.json()["total"] == 2
    ass_ids = {d["id"] for d in res_ass.json()["items"]}
    assert ass_ids == {"DEF-1002", "DEF-1005"}

    # 4. Compound filter: Module=Storage + Assignee=dev1 + Reporter=rep1 -> DEF-1005
    res_compound = client.get(
        f"/api/v1/defects?module=Storage&assignee_id={dev1_id}&reporter_id={rep1_id}",
        headers=headers,
    )
    assert res_compound.status_code == 200
    assert res_compound.json()["total"] == 1
    assert res_compound.json()["items"][0]["id"] == "DEF-1005"


# ==============================================================================
# TC-SRCH-005: Pagination behavior and boundaries
# ==============================================================================

def test_tc_srch_005_pagination_boundaries(client, db_session, make_user, auth_headers):
    """TC-SRCH-005: Default page_size=20, custom page_size=100, page_size=101 clamped/rejected."""
    reporter = make_user(username="page_reporter", role=UserRole.REPORTER)
    headers = auth_headers(reporter)

    # Seed 25 defects to test page boundaries
    for i in range(1, 26):
        _create_defect_record(
            db_session,
            defect_id=f"DEF-{2000 + i}",
            title=f"Synthetic Defect Number {i:03d} for Pagination Testing",
            description=f"Detailed description for synthetic pagination test record number {i:03d}.",
            module="Core",
            severity=DefectSeverity.MAJOR,
            priority=DefectPriority.P3,
            status=DefectStatus.OPEN,
            reporter_id=reporter.id,
        )

    # 1. Default page_size=20: page 1 returns 20 items, total=25, total_pages=2
    res_def = client.get("/api/v1/defects", headers=headers)
    assert res_def.status_code == 200
    data_def = res_def.json()
    assert data_def["total"] == 25
    assert len(data_def["items"]) == 20
    assert data_def["page"] == 1
    assert data_def["page_size"] == 20
    assert data_def["total_pages"] == 2

    # 2. Page 2 returns the remaining 5 items
    res_p2 = client.get("/api/v1/defects?page=2&page_size=20", headers=headers)
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert data_p2["total"] == 25
    assert len(data_p2["items"]) == 5
    assert data_p2["page"] == 2

    # Items between page 1 and page 2 must be mutually disjoint
    p1_ids = {d["id"] for d in data_def["items"]}
    p2_ids = {d["id"] for d in data_p2["items"]}
    assert p1_ids.isdisjoint(p2_ids)

    # 3. Customizable page size up to 100 records returns all 25 items in single page
    res_100 = client.get("/api/v1/defects?page_size=100", headers=headers)
    assert res_100.status_code == 200
    data_100 = res_100.json()
    assert data_100["total"] == 25
    assert len(data_100["items"]) == 25
    assert data_100["page_size"] == 100
    assert data_100["total_pages"] == 1

    # 4. Boundary violation: page_size = 101 must be rejected with HTTP 422
    res_101 = client.get("/api/v1/defects?page_size=101", headers=headers)
    assert res_101.status_code == 422

    # 5. Boundary violation: page_size = 0 or < 1 rejected with HTTP 422
    res_zero = client.get("/api/v1/defects?page_size=0", headers=headers)
    assert res_zero.status_code == 422

    # 6. Boundary violation: page = 0 rejected with HTTP 422
    res_page_zero = client.get("/api/v1/defects?page=0", headers=headers)
    assert res_page_zero.status_code == 422


# ==============================================================================
# TC-SRCH-006: Sorting results
# ==============================================================================

def test_tc_srch_006_sorting_results(client, seeded_defects, auth_headers):
    """TC-SRCH-006: Sort by created_at DESC, severity ASC."""
    headers = auth_headers(seeded_defects["reporter1"])

    # 1. Sort by created_at DESC (default)
    res_desc = client.get("/api/v1/defects?sort_by=created_at&sort_order=desc", headers=headers)
    assert res_desc.status_code == 200
    items_desc = res_desc.json()["items"]
    created_timestamps = [d["created_at"] for d in items_desc]
    assert created_timestamps == sorted(created_timestamps, reverse=True)

    # 2. Sort by created_at ASC
    res_asc = client.get("/api/v1/defects?sort_by=created_at&sort_order=asc", headers=headers)
    assert res_asc.status_code == 200
    items_asc = res_asc.json()["items"]
    created_timestamps_asc = [d["created_at"] for d in items_asc]
    assert created_timestamps_asc == sorted(created_timestamps_asc)

    # 3. Sort by severity ASC (Blocker -> Critical -> Major -> Minor -> Trivial)
    res_sev = client.get("/api/v1/defects?sort_by=severity&sort_order=asc", headers=headers)
    assert res_sev.status_code == 200
    severities = [d["severity"] for d in res_sev.json()["items"]]
    sev_rank = {
        DefectSeverity.BLOCKER.value: 1,
        DefectSeverity.CRITICAL.value: 2,
        DefectSeverity.MAJOR.value: 3,
        DefectSeverity.MINOR.value: 4,
        DefectSeverity.TRIVIAL.value: 5,
    }
    numeric_sev = [sev_rank[s] for s in severities]
    assert numeric_sev == sorted(numeric_sev)

    # 4. Sort by priority ASC (P1 -> P2 -> P3 -> P4)
    res_pri = client.get("/api/v1/defects?sort_by=priority&sort_order=asc", headers=headers)
    assert res_pri.status_code == 200
    priorities = [d["priority"] for d in res_pri.json()["items"]]
    pri_rank = {
        DefectPriority.P1.value: 1,
        DefectPriority.P2.value: 2,
        DefectPriority.P3.value: 3,
        DefectPriority.P4.value: 4,
    }
    numeric_pri = [pri_rank[p] for p in priorities]
    assert numeric_pri == sorted(numeric_pri)

    # 5. Compound sort via sort expression: "created_at DESC, severity ASC"
    res_compound = client.get("/api/v1/defects?sort=created_at DESC, severity ASC", headers=headers)
    assert res_compound.status_code == 200
    assert len(res_compound.json()["items"]) == 5

    # 6. Invalid sort field rejected with HTTP 400 Bad Request
    res_invalid_field = client.get("/api/v1/defects?sort_by=nonexistent_field", headers=headers)
    assert res_invalid_field.status_code == 400
    assert "Invalid sort field" in res_invalid_field.json()["detail"]

    # 7. Invalid sort order rejected with HTTP 400 Bad Request
    res_invalid_order = client.get("/api/v1/defects?sort_by=created_at&sort_order=sideways", headers=headers)
    assert res_invalid_order.status_code == 400
    assert "Invalid sort order" in res_invalid_order.json()["detail"]

    # 8. Invalid expression in sort string rejected with HTTP 400
    res_invalid_expr = client.get("/api/v1/defects?sort=unknown_col DESC", headers=headers)
    assert res_invalid_expr.status_code == 400
    assert "Invalid sort field" in res_invalid_expr.json()["detail"]


# ==============================================================================
# Additional Tests: Creation Date Range & Authorization Checks
# ==============================================================================

def test_tc_srch_date_range_filtering(client, seeded_defects, auth_headers):
    """Verify creation date range filtering with created_after and created_before."""
    headers = auth_headers(seeded_defects["reporter1"])
    dates = seeded_defects["dates"]

    # t0 = 2026-01-01, t1 = 2026-01-02, t2 = 2026-01-03, t3 = 2026-01-04, t4 = 2026-01-05
    # Filter between t1 (inclusive) and t3 (inclusive) -> DEF-1002, DEF-1003, DEF-1004
    t1_iso = dates[1].isoformat()
    t3_iso = dates[3].isoformat()

    res = client.get(
        f"/api/v1/defects?created_after={t1_iso}&created_before={t3_iso}",
        headers=headers,
    )
    assert res.status_code == 200
    matched_ids = {d["id"] for d in res.json()["items"]}
    assert matched_ids == {"DEF-1002", "DEF-1003", "DEF-1004"}

    # Filter with alias created_from / created_to
    res_alias = client.get(
        f"/api/v1/defects?created_from={t1_iso}&created_to={t3_iso}",
        headers=headers,
    )
    assert res_alias.status_code == 200
    assert res_alias.json()["total"] == 3


def test_tc_srch_auth_and_roles(client, seeded_defects, make_user, auth_headers):
    """Verify OP_VIEW_DEFECT permission across all authenticated roles and rejection of unauthenticated access."""
    # 1. Unauthenticated request rejected with HTTP 401 Unauthorized
    res_unauth = client.get("/api/v1/defects")
    assert res_unauth.status_code == 401

    # 2. Authenticated access permitted for all roles
    qa_user = make_user(username="qa_inspector", role=UserRole.QA_TRIAGE)
    admin_user = make_user(username="admin_inspector", role=UserRole.ADMIN)

    for role_user in [
        seeded_defects["reporter1"],
        seeded_defects["dev1"],
        qa_user,
        admin_user,
    ]:
        res_role = client.get("/api/v1/defects", headers=auth_headers(role_user))
        assert res_role.status_code == 200
        assert res_role.json()["total"] == 5
