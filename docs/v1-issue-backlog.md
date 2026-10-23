# Version 1 GitHub Issue Backlog & Execution Plan

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Document Reference:** `docs/v1-issue-backlog.md`  
**Version:** 1.0 (Version 1 Baseline)  

---

## 1. Overview & Issue Strategy

In accordance with course guidelines (§14), large monolithic tasks (e.g., "Build Version 1") are strictly prohibited. 

This document defines the **12 discrete, testable GitHub Issues** that form the implementation roadmap for Version 1. Each issue is traced to functional requirements, quality risks, acceptance criteria, and verification test suites.

---

## 2. Granular Issue Specifications

### Issue #1: Project Skeleton, Dependency Manifest & Test Harness Setup
- **Branch:** `feature/1-project-skeleton`
- **Purpose:** Establish the foundational backend directory structure, FastAPI application gateway, dependency definitions (`requirements.txt`), SQLite database connection factory, and `pytest` execution framework.
- **Requirements Addressed:** `NFR-009`, `NFR-010`, `NFR-012`
- **Acceptance Criteria:**
  1. Backend runs locally (`uvicorn main:app`).
  2. Health check endpoint `GET /api/v1/health` returns `{"status": "healthy", "version": "1.0.0-dev"}` with HTTP 200.
  3. `pytest` runs cleanly and reports 100% passing tests.
- **Expected Tests:** `test_health_check.py`
- **Dependencies:** None

---

### Issue #2: User Domain Model, Authentication & RBAC Middleware
- **Branch:** `feature/2-auth-and-rbac`
- **Purpose:** Implement the `User` entity, password hashing (BCrypt), JWT token issuance/verification, and declarative RBAC dependency injection guards for `ROLE_REPORTER`, `ROLE_DEVELOPER`, `ROLE_QA_TRIAGE`, and `ROLE_ADMIN`.
- **Requirements Addressed:** `FR-031`, `NFR-001`, `NFR-002`, `NFR-003`
- **Risk Mitigated:** `RISK-V1-002`
- **Acceptance Criteria:**
  1. Endpoint `POST /api/v1/auth/register` creates user with salted password hash.
  2. Endpoint `POST /api/v1/auth/login` returns valid JWT access token.
  3. Secured routes reject unauthenticated requests with HTTP `401 Unauthorized`.
  4. Role mismatch triggers HTTP `403 Forbidden` with audit logging.
- **Expected Tests:** `TC-SEC-001`, `TC-SEC-002`, `TC-AUTH-001`, `TC-AUTH-010`
- **Dependencies:** Issue #1

---

### Issue #3: Defect Domain Model & Database Migrations
- **Branch:** `feature/3-defect-domain-model`
- **Purpose:** Define the SQLAlchemy 2.0 `Defect` and `DefectHistory` ORM entities and generate initial Alembic migration scripts.
- **Requirements Addressed:** `FR-004`, `FR-005`, `NFR-004`, `NFR-005`
- **Acceptance Criteria:**
  1. Relational schema created with foreign keys linking `reporter_id` and `assignee_id` to `User.id`.
  2. Defect entity includes all 17 standard engineering fields plus `version` token initialized to `1`.
  3. Database migration executes and rolls back cleanly without data corruption.
- **Expected Tests:** `TC-SYS-003`, schema migration verification tests.
- **Dependencies:** Issue #1, #2

---

### Issue #4: Defect Ingestion & Creation Service
- **Branch:** `feature/4-defect-creation`
- **Purpose:** Implement `POST /api/v1/defects` with Pydantic boundary validation for title, description, and enum domains (Severity, Priority).
- **Requirements Addressed:** `FR-001`, `FR-002`, `FR-003`, `FR-004`, `FR-005`, `FR-009`, `FR-010`
- **Acceptance Criteria:**
  1. Valid submission returns HTTP `201 Created` with unique Defect ID (e.g. `DEF-1001`) and initial status `Open`.
  2. Title < 10 or > 120 chars, or empty/whitespace, rejected with HTTP `422`.
  3. Description < 30 chars rejected with HTTP `422`.
  4. Invalid severity/priority enums rejected with HTTP `422`.
- **Expected Tests:** `TC-DEF-001` through `TC-DEF-006`, `TC-DEF-010`
- **Dependencies:** Issue #3

---

### Issue #5: Defect Updating & Reporter Edit Governance
- **Branch:** `feature/5-defect-update`
- **Purpose:** Implement `PUT /api/v1/defects/{id}` allowing reporters to rectify their own defect reports while strictly in `Open` status.
- **Requirements Addressed:** `FR-006`, `FR-007`, `FR-008`
- **Risk Mitigated:** `RISK-V1-002`
- **Acceptance Criteria:**
  1. Author can update description, steps, and environment while status is `Open`.
  2. Non-author update attempt rejected with HTTP `403 Forbidden`.
  3. Author update attempt past `Open` status rejected with HTTP `403 Forbidden`.
  4. Successful update increments `version` token.
- **Expected Tests:** `TC-DEF-007`, `TC-DEF-008`, `TC-DEF-009`
- **Dependencies:** Issue #4

---

### Issue #6: Deterministic Evidence Quality Gate Validation
- **Branch:** `feature/6-evidence-validation`
- **Purpose:** Implement `EvidenceValidationService` to enforce evidence thresholds before defects can transition to `Triaged`.
- **Requirements Addressed:** `FR-011` through `FR-016`
- **Risk Mitigated:** `RISK-V1-003`
- **Acceptance Criteria:**
  1. Validates: Steps to Reproduce &ge; 2 numbered steps and &ge; 20 chars; Expected and Actual results &ge; 10 chars and non-identical; Environment non-empty.
  2. Attempting to triage a defect lacking required evidence returns HTTP `422 Unprocessable Entity` containing an itemized error array.
  3. Defect remains in `Open` until all evidence rules pass.
- **Expected Tests:** `TC-EVID-001` through `TC-EVID-007`
- **Dependencies:** Issue #4, #5

---

### Issue #7: Defect Lifecycle State Transitions & FSM Engine
- **Branch:** `feature/7-defect-lifecycle-fsm`
- **Purpose:** Implement the finite-state machine transitions: `Open` &rarr; `Triaged` &rarr; `Assigned` &rarr; `In Progress` &rarr; `Fixed` &rarr; `Retest` &rarr; `Closed` (and `Reopened`).
- **Requirements Addressed:** `FR-021` through `FR-030`
- **Risk Mitigated:** `RISK-V1-001`, `RISK-V1-007`, `RISK-V1-008`
- **Acceptance Criteria:**
  1. Enforces all permitted transitions defined in `docs/defect-workflow.md`.
  2. Rejects illegal transitions (e.g. `Open` &rarr; `Closed`, `Fixed` &rarr; `Closed`) with HTTP `400 Bad Request`.
  3. Moving to `In Progress` requires non-null assignee.
  4. Moving to `Fixed` requires resolution notes, root cause, and fix reference.
  5. Retest failure increments `reopen_count` and moves to `Reopened`.
- **Expected Tests:** `TC-WF-001` through `TC-WF-012`
- **Dependencies:** Issue #6

---

### Issue #8: Assignment & Role-Based Authorization Enforcement
- **Branch:** `feature/8-assignment-and-rbac`
- **Purpose:** Enforce role-based boundaries on triage, assignment, progress, retesting, and defect closure.
- **Requirements Addressed:** `FR-032` through `FR-037`
- **Risk Mitigated:** `RISK-V1-002`, `RISK-V1-006`
- **Acceptance Criteria:**
  1. Only `ROLE_QA_TRIAGE` and `ROLE_ADMIN` can triage, change severity, change priority, close, or reopen.
  2. Developers can self-assign unassigned triaged defects, but cannot reassign others' defects.
  3. Strict Separation of Duties: Developer who marked defect `Fixed` cannot perform `Retest` or `Close` on that defect.
- **Expected Tests:** `TC-AUTH-002` through `TC-AUTH-009`
- **Dependencies:** Issue #7

---

### Issue #9: Multi-Attribute Search, Filter & Pagination Service
- **Branch:** `feature/9-search-and-filtering`
- **Purpose:** Implement `GET /api/v1/defects` with query filtering, full-text substring search, sorting, and pagination.
- **Requirements Addressed:** `FR-041`, `FR-042`, `FR-043`, `FR-044`
- **Acceptance Criteria:**
  1. Search by exact ID and keyword substring in title/description.
  2. Filter by status, severity, priority, module, assignee, and reporter.
  3. Paginated responses with configurable page size (default 20, max 100).
  4. Sort by `created_at`, `updated_at`, `severity`, and `priority`.
- **Expected Tests:** `TC-SRCH-001` through `TC-SRCH-006`
- **Dependencies:** Issue #4, #7

---

### Issue #10: Immutable Defect Audit History & Traceability
- **Branch:** `feature/10-defect-history`
- **Purpose:** Implement automatic audit logging of all state transitions, field mutations, and assignments to `DefectHistory`. Expose `GET /api/v1/defects/{id}/history`.
- **Requirements Addressed:** `FR-049`, `FR-050`, `FR-051`, `FR-052`
- **Risk Mitigated:** `RISK-V1-005`
- **Acceptance Criteria:**
  1. Every mutation automatically inserts an audit entry with user ID, timestamp, old value, and new value.
  2. Audit log endpoint returns chronological sequence.
  3. Audit records cannot be modified or deleted via API.
- **Expected Tests:** `TC-HIST-001` through `TC-HIST-005`
- **Dependencies:** Issue #7, #8

---

### Issue #11: Optimistic Concurrency Control & Stale Update Protection
- **Branch:** `feature/11-concurrency-protection`
- **Purpose:** Integrate optimistic locking via SQLAlchemy `version_id_col` and reject concurrent stale mutations with HTTP `409 Conflict`.
- **Requirements Addressed:** `FR-056` through `FR-060`
- **Risk Mitigated:** `RISK-V1-004`
- **Acceptance Criteria:**
  1. Every update or status change verifies submitted `version` token matches database version.
  2. If version is stale, transaction aborts and returns HTTP `409 Conflict` containing the latest defect snapshot.
  3. Simulated race conditions guarantee 0% silent data overwrites.
- **Expected Tests:** `TC-CONC-001` through `TC-CONC-004`
- **Dependencies:** Issue #5, #7, #10

---

### Issue #12: Complete Version 1 System Testing, Regression & Baseline Sign-Off
- **Branch:** `test/12-v1-system-testing`
- **Purpose:** Execute the comprehensive Version 1 system test suite, verify all 58 test cases, compile evidence into `docs/testing/v1-system-test-results.md`, and prepare release tag `v1.0.0`.
- **Requirements Addressed:** All V1 Functional and Non-Functional Requirements (`FR-001` through `FR-060`, `NFR-001` through `NFR-012`).
- **Risks Mitigated:** All Version 1 Risks (`RISK-V1-001` through `RISK-V1-008`).
- **Acceptance Criteria:**
  1. 100% of unit, integration, and system tests pass.
  2. Statement coverage &ge; 85%.
  3. All system test results documented in `docs/testing/v1-system-test-results.md`.
  4. Repository is ready for Git baseline tagging: **`v1.0.0`**.
- **Expected Tests:** Complete Master Test Suite (`TC-DEF`, `TC-EVID`, `TC-WF`, `TC-AUTH`, `TC-SRCH`, `TC-HIST`, `TC-CONC`, `TC-SEC`, `TC-SYS`).
- **Dependencies:** Issues #1 through #11
