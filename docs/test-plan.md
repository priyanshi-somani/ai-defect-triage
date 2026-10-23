# Master Test Plan & Verification Strategy — Version 1.0 Baseline

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Document Reference:** `docs/test-plan.md`  
**Version:** 1.0 (Version 1 Baseline)  

---

## 1. Test Plan Overview & Objectives

This document establishes the comprehensive test plan for **Version 1** of the Defect Management System. In alignment with course objectives, testing is treated as a primary engineering discipline with multi-level verification, explicit requirement traceability, and automated regression testing.

### Objectives:
1. Deterministically verify all functional requirements (`FR-001` through `FR-060`) and non-functional requirements (`NFR-001` through `NFR-012`).
2. Validate that all high- and medium-priority project risks (`RISK-V1-001` through `RISK-V1-008`) are effectively mitigated.
3. Guarantee that Version 1 has zero dependence on AI or external heuristics.
4. Establish the automated regression baseline required prior to tagging **`v1.0.0`**.

---

## 2. Testing Levels & Quality Gates

The verification strategy employs four testing levels:

| Level | Scope | Primary Tools & Approach | Entry / Pass Criteria |
| :--- | :--- | :--- | :--- |
| **Unit Testing** | Individual functions, validation rules, state transition table lookups, password hashing. | `pytest` / test runner; mock DB/storage if applicable. | 100% pass; statement coverage $\ge 85\%$ across service and validation modules. |
| **Integration Testing** | API endpoints, DB transaction atomicity, RBAC middleware, optimistic concurrency checks, audit table deltas. | Test client calling REST endpoints against isolated test database. | 100% pass; 0 unhandled 500 exceptions; schema foreign keys verified. |
| **System Testing** | Full end-to-end multi-user workflows simulating real defect lifecycles (Reporter &rarr; QA &rarr; Dev &rarr; QA). | Automated end-to-end scenario test scripts. | All planned Version 1 system test areas passed and recorded in `v1-system-test-results.md`. |
| **Regression Testing** | Automated rerun of entire unit, integration, and system test suites upon any code mutation or PR. | GitHub Actions CI or local automated test runner. | Zero regression failures allowed before merge to `main`. |

---

## 3. Test Traceability Matrix

This matrix maps Capabilities, Requirements, Risks, and Test Cases:

| Capability | Requirements Addressed | Risk Mitigated | Test Case Range | Focus Area |
| :--- | :--- | :--- | :--- | :--- |
| **Defect Ingestion & Update** | `FR-001` – `FR-010` | `RISK-V1-002` | `TC-DEF-001` – `TC-DEF-010` | Field boundaries, reporter edits, enum validation, persistence |
| **Evidence Quality Gate** | `FR-011` – `FR-016` | `RISK-V1-003` | `TC-EVID-001` – `TC-EVID-007` | Deterministic evidence rules, missing step/result rejection |
| **Lifecycle State Transitions** | `FR-021` – `FR-030` | `RISK-V1-001`, `RISK-V1-007`, `RISK-V1-008` | `TC-WF-001` – `TC-WF-012` | FSM validation, illegal transition guards, reopen/close rules |
| **Role-Based Access Control** | `FR-031` – `FR-037` | `RISK-V1-002`, `RISK-V1-006` | `TC-AUTH-001` – `TC-AUTH-010` | RBAC matrix enforcement, separation of duties, 403 checks |
| **Search & Multi-Filtering** | `FR-041` – `FR-044` | N/A | `TC-SRCH-001` – `TC-SRCH-006` | Exact/substring search, compound multi-filter, pagination, sorting |
| **Audit History & Traceability** | `FR-049` – `FR-052` | `RISK-V1-005` | `TC-HIST-001` – `TC-HIST-005` | Immutable log entries, delta tracking, unmodifiable audit logs |
| **Concurrency & Optimistic Lock** | `FR-056` – `FR-060` | `RISK-V1-004` | `TC-CONC-001` – `TC-CONC-004` | Version token increment, 409 Conflict rejection, race condition safety |
| **Security & Non-Functional** | `NFR-001` – `NFR-012` | System integrity | `TC-SEC-001` – `TC-SEC-003`, `TC-SYS-001` – `TC-SYS-004` | Auth tokens, hashing, latency benchmarks, rollback atomicity |

---

## 4. Master Test Case Catalog (61 Planned Version 1 Test Cases)

### 4.1 Defect Ingestion & Updating (`TC-DEF`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-DEF-001** | Create defect with complete valid fields | Valid payload with Title, Description, Steps, Expected, Actual, Env, Severity, Priority. | HTTP `201 Created`; status is `Open`; version is `1`; unique `id` generated. | Integration |
| **TC-DEF-002** | Defect creation rejects empty or whitespace title | Title is empty string or only spaces. | HTTP `422 Unprocessable Entity`; validation error message returned. | Unit / API |
| **TC-DEF-003** | Defect creation title length boundary test | Title length = 9 chars (fail), 10 chars (pass), 120 chars (pass), 121 chars (fail). | Boundary enforcement: 9 and 121 fail with HTTP `422`; 10 and 120 pass with `201`. | Unit |
| **TC-DEF-004** | Defect creation description boundary test | Description length = 29 chars (fail), 30 chars (pass). | 29 chars fails with HTTP `422`; 30 chars passes. | Unit |
| **TC-DEF-005** | Defect creation handles long text safely | Description and Steps containing 4,000 characters. | HTTP `201 Created`; text persisted and retrieved without truncation. | Integration / DB |
| **TC-DEF-006** | Defect creation rejects invalid enum values | Severity = `Fatal`; Priority = `Urgent`. | HTTP `422 Unprocessable Entity` citing allowable enum domain values. | Unit |
| **TC-DEF-007** | Reporter updates own defect in `Open` status | Authenticated reporter modifies title and steps while defect is in `Open`. | HTTP `200 OK`; updated fields persisted; version increments to `2`. | Integration |
| **TC-DEF-008** | Reporter rejected when editing another user's defect | Reporter B attempts to update defect created by Reporter A. | HTTP `403 Forbidden`; no changes persisted. | Security / API |
| **TC-DEF-009** | Reporter rejected when editing own defect past `Open` | Reporter attempts to edit defect currently in `Triaged` status. | HTTP `403 Forbidden`; edits blocked. | Security / API |
| **TC-DEF-010** | Defect persistence and retrieval consistency | Defect created and re-fetched by ID. | All returned fields match submitted payload byte-for-byte. | System |

---

### 4.2 Evidence Quality Validation (`TC-EVID`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-EVID-001** | Complete evidence passes quality gate | Defect has structured steps (&ge; 2 numbered), expected/actual results (&ge; 10 chars), valid environment. | Transition from `Open` to `Triaged` succeeds (`200 OK`). | Unit / Integration |
| **TC-EVID-002** | Missing reproduction steps blocks triage | Steps to Reproduce field is null or empty. | Transition to `Triaged` rejected with HTTP `422`; defect remains `Open`. | System |
| **TC-EVID-003** | Unstructured reproduction steps blocks triage | Steps to Reproduce contains single unnumbered sentence under 20 chars. | HTTP `422 Unprocessable Entity` requiring at least 2 numbered steps. | Unit / System |
| **TC-EVID-004** | Missing expected or actual result blocks triage | Expected Result is empty; Actual Result is populated. | HTTP `422 Unprocessable Entity`; itemized error identifies Expected Result. | Unit / System |
| **TC-EVID-005** | Identical expected and actual result blocks triage | Expected Result = "Page crashes"; Actual Result = "Page crashes". | HTTP `422 Unprocessable Entity` (results must not be identical). | Unit |
| **TC-EVID-006** | Missing environment details blocks triage | Environment is empty or missing OS/client version. | HTTP `422 Unprocessable Entity` requiring environment specifications. | System |
| **TC-EVID-007** | Quality gate failure payload formatting | Multiple evidence deficiencies present simultaneously. | HTTP `422` response payload returns detailed array of all failing criteria. | API |

---

### 4.3 Lifecycle Workflow Transitions (`TC-WF`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-WF-001** | Standard forward lifecycle progression | Sequential progression: `Open` &rarr; `Triaged` &rarr; `Assigned` &rarr; `In Progress` &rarr; `Fixed` &rarr; `Retest` &rarr; `Closed`. | Each transition succeeds with `200 OK`; status updates correctly. | System |
| **TC-WF-002** | Illegal direct transition: `Open` &rarr; `Closed` | Request to close defect directly from `Open` state. | HTTP `400 Bad Request`; transition rejected. | State Machine |
| **TC-WF-003** | Transition `Triaged` &rarr; `In Progress` without assignee | Attempt to start progress with `assignee_id = null`. | HTTP `422 Unprocessable Entity`; assignee is mandatory. | Integration |
| **TC-WF-004** | Transition `In Progress` &rarr; `Fixed` requires resolution | Attempt to mark fixed without `resolution_notes` or `root_cause`. | HTTP `422 Unprocessable Entity`; fix blocked until details provided. | Integration |
| **TC-WF-005** | Illegal direct transition: `Fixed` &rarr; `Closed` | Attempt to close fixed defect bypassing `Retest`. | HTTP `400 Bad Request`; retest verification is mandatory. | State Machine |
| **TC-WF-006** | Retest verification succeeds and defect closed | QA provides `verification_notes` and target build number. | Transition `Retest` &rarr; `Closed` succeeds (`200 OK`). | System |
| **TC-WF-007** | Retest verification fails and defect reopened | QA provides failure evidence and `reopen_reason`. | Transition `Retest` &rarr; `Reopened`; `reopen_count` increments by 1. | System |
| **TC-WF-008** | Reopened defect resumed by developer | Assigned developer moves `Reopened` defect to `In Progress`. | HTTP `200 OK`; work resumed. | System |
| **TC-WF-009** | Closed defect regressed and reopened | QA/Admin discovers regression; provides regression justification. | Transition `Closed` &rarr; `Reopened` succeeds with audit event. | System |
| **TC-WF-010** | Assigned defect returned to triage queue | Defect in `Assigned` transitioned back to `Triaged` (unassigned). | `assignee_id` cleared; status set to `Triaged`. | Integration |
| **TC-WF-011** | Comprehensive illegal transitions suite | Matrix test attempting all invalid combinations (e.g., `Open` &rarr; `Fixed`, `Triaged` &rarr; `Closed`). | 100% of illegal transitions rejected with HTTP `400 Bad Request`. | Automated Unit |
| **TC-WF-012** | Multi-cycle retest failure endurance | Defect reopened twice (`reopen_count = 2`) before eventual closure. | Audit log captures full sequence; final status is `Closed`. | System |

---

### 4.4 Role-Based Permissions & Separation of Duties (`TC-AUTH`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-AUTH-001** | Reporter permitted operations verification | Authenticated as `ROLE_REPORTER`. | Can create defect, view defects, edit own open defect. | Integration |
| **TC-AUTH-002** | Reporter cannot triage defects | Reporter calls `OP_TRIAGE_DEFECT`. | HTTP `403 Forbidden`. | Security |
| **TC-AUTH-003** | Reporter cannot close defects | Reporter calls `OP_CLOSE_DEFECT`. | HTTP `403 Forbidden`. | Security |
| **TC-AUTH-004** | Developer cannot triage defects | Developer calls `OP_TRIAGE_DEFECT`. | HTTP `403 Forbidden`. | Security |
| **TC-AUTH-005** | Developer self-assignment vs. reassignment | Developer assigns unassigned defect to self vs. reassigning another's defect. | Self-assignment succeeds (`200 OK`); reassignment rejected (`403 Forbidden`). | Security |
| **TC-AUTH-006** | Developer progress restriction | Developer attempts to move defect assigned to Developer B to `In Progress`. | HTTP `403 Forbidden`. | Security |
| **TC-AUTH-007** | Separation of duties: Developer cannot retest own fix | Developer who marked defect `Fixed` attempts to call `OP_RETEST_DEFECT`. | HTTP `403 Forbidden` (independent QA required). | Security / System |
| **TC-AUTH-008** | Separation of duties: Developer cannot close own fix | Developer who marked defect `Fixed` attempts to call `OP_CLOSE_DEFECT`. | HTTP `403 Forbidden`. | Security / System |
| **TC-AUTH-009** | QA / Triage authority verification | Authenticated as `ROLE_QA_TRIAGE`. | Can validate evidence, triage, assign, retest, reopen, and close. | Integration |
| **TC-AUTH-010** | Admin authority verification | Authenticated as `ROLE_ADMIN`. | Can perform all operations, reassignments, and administrative overrides. | Integration |

---

### 4.5 Search & Multi-Attribute Filtering (`TC-SRCH`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-SRCH-001** | Search by exact Defect ID | Query parameter: `id=DEF-1001`. | Returns exactly the matching defect. | Integration |
| **TC-SRCH-002** | Search by keyword substring | Keyword present in Title or Description. | Returns all defects matching substring case-insensitively. | Integration |
| **TC-SRCH-003** | Multi-attribute compound filtering | Filter by: `status=Open`, `severity=Blocker`, `priority=P1`. | Returns only defects matching all three conditions. | Integration |
| **TC-SRCH-004** | Filter by Assignee, Reporter, Module | Filter by combinations of user and module IDs. | Accurate query results matching filter subset. | Integration |
| **TC-SRCH-005** | Pagination behavior and boundaries | Page size = 20, page size = 100, page size = 101. | 20 and 100 return paginated slices; > 100 is clamped or rejected. | Integration |
| **TC-SRCH-006** | Sorting results | Sort by `created_at DESC`, `severity ASC`. | Output correctly ordered according to sort keys. | Integration |

---

### 4.6 Audit History & Traceability (`TC-HIST`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-HIST-001** | Status transition generates audit log | Status moves from `Open` to `Triaged`. | Audit record created with `old_value = Open`, `new_value = Triaged`, actor ID, timestamp. | DB / Integration |
| **TC-HIST-002** | Field edit generates audit delta | Title updated from "Old Title" to "New Title". | Audit record captures `field = title`, `old_value`, `new_value`. | Integration |
| **TC-HIST-003** | Assignee change generates audit entry | Defect assigned to Developer A, then Developer B. | Audit records accurately log both assignment transitions. | Integration |
| **TC-HIST-004** | History endpoint exposes complete sequence | Defect transitions through 5 states. | `GET /api/v1/defects/{id}/history` returns all 5 entries in chronological order. | API |
| **TC-HIST-005** | Audit log immutability check | Direct API attempt to update or delete audit records. | No edit/delete endpoint exists; direct DB mutation restricted. | Security |

---

### 4.7 Concurrency Control & Optimistic Locking (`TC-CONC`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-CONC-001** | Version increment on successful update | Defect created at `version = 1`. Update submitted with `version = 1`. | Update succeeds (`200 OK`); database version increments to `2`. | Integration |
| **TC-CONC-002** | Rejection of stale update with 409 Conflict | Client submits update with stale `version = 1`, but DB is at `version = 2`. | HTTP `409 Conflict`; no database overwrite occurs. | Integration |
| **TC-CONC-003** | 409 Conflict returns latest representation | Stale update rejected. | Response payload contains latest database state for user resolution. | API / Integration |
| **TC-CONC-004** | Concurrent multi-user race condition test | Two simulated concurrent threads attempt conflicting status updates simultaneously. | Exactly one thread succeeds (`200 OK`); second thread receives `409 Conflict`. 0% silent overwrites. | System Concurrency |

---

### 4.8 Security, Reliability & Non-Functional (`TC-SEC`, `TC-SYS`)

| Test ID | Test Description | Inputs / Preconditions | Expected Outcome | Verification Level |
| :--- | :--- | :--- | :--- | :--- |
| **TC-SEC-001** | Unauthenticated request rejected | Request sent without authentication token/session. | HTTP `401 Unauthorized`. | Security |
| **TC-SEC-002** | Password hashing algorithm verification | User registered in system. | Database stores salted hash (BCrypt/Argon2id); plaintext password never stored. | Security Review |
| **TC-SEC-003** | Input sanitization against XSS/SQLi | Malicious scripts and SQL payloads injected into Title and Description. | Input escaped/sanitized; no script execution or SQL syntax injection. | Security |
| **TC-SYS-001** | End-to-end multi-role system test | Complete defect lifecycle executed by 4 distinct role personas. | Full workflow succeeds; audit history complete; zero manual interventions. | System |
| **TC-SYS-002** | Single-request response latency benchmark | 100 consecutive defect CRUD and transition requests. | 95th percentile latency $< 200\text{ ms}$. | Performance |
| **TC-SYS-003** | Database transaction rollback on error | Injected failure during audit log insertion after defect update. | Transaction rolls back completely; defect state remains unchanged. | Reliability |
| **TC-SYS-004** | Zero AI dependency verification | Execute complete Version 1 test suite. | Network inspection confirms 0 calls to external AI providers or ML models. | Architecture Audit |

---

## 5. System Test Execution & Baseline Sign-Off

1. **System Test Execution Script:**  
   The system tests specified above will be compiled into an automated test runner command (e.g., `pytest tests/system/`).
2. **Recording Results:**  
   All test execution outcomes will be formally documented in:  
   [testing/v1-system-test-results.md](testing/v1-system-test-results.md)
3. **Completion Gate:**  
   Every test case (`TC-DEF`, `TC-EVID`, `TC-WF`, `TC-AUTH`, `TC-SRCH`, `TC-HIST`, `TC-CONC`, `TC-SEC`, `TC-SYS`) must record a status of **PASSED** before the repository is tagged **`v1.0.0`**.
