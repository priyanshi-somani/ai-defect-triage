# Software Requirements Specification (SRS) — Version 1.0 Baseline

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Document Reference:** `docs/requirements.md`  
**Version:** 1.0 (Version 1 Baseline)  

---

## 1. Introduction & Traceability Model

This document specifies the testable Functional Requirements (FR) and Non-Functional Requirements (NFR) for **Version 1** of the Defect Management System.

In alignment with course software engineering standards, requirements are written using the **Actor–Behavior–Constraint (ABC)** structure to ensure unambiguous testability. Every requirement maps directly to capabilities defined in [version-scope.md](version-scope.md), authorization policies in [roles-permissions.md](roles-permissions.md), and state transitions in [defect-workflow.md](defect-workflow.md).

Version 1 is **strictly deterministic and AI-free**.

---

## 2. Functional Requirements (FR)

### 2.1 Capability 1: Defect Ingestion & Updating

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-001** | The system shall allow an authenticated user (Reporter, Developer, QA/Triage, Admin) to create a defect with fields: Title, Description, Steps to Reproduce, Expected Result, Actual Result, Environment, Module, Severity, and Priority. | Integration Test / API |
| **FR-002** | The system shall reject defect creation if Title is missing, whitespace-only, or outside the range of 10 to 120 characters, returning HTTP `422 Unprocessable Entity`. | Unit Test / API Test |
| **FR-003** | The system shall reject defect creation if Description is missing or fewer than 30 characters in length, returning HTTP `422 Unprocessable Entity`. | Unit Test / API Test |
| **FR-004** | The system shall automatically generate a unique, non-repeating identifier (e.g., `DEF-1001` or UUID) and record the creation timestamp (`created_at`) and reporter identifier (`reporter_id`) upon successful creation. | Integration Test / DB |
| **FR-005** | The system shall automatically initialize newly created defects to status `Open` and concurrency version `1`. | Unit Test / API Test |
| **FR-006** | The system shall allow the original reporter to update Title, Description, Steps to Reproduce, Expected Result, Actual Result, and Environment if and only if the defect status is `Open`. | Unit / Integration Test |
| **FR-007** | The system shall reject update attempts by a Reporter to a defect authored by another user, returning HTTP `403 Forbidden`. | Security Test / API |
| **FR-008** | The system shall reject update attempts by a Reporter if the defect has transitioned past `Open` status, returning HTTP `403 Forbidden`. | Security Test / API |
| **FR-009** | The system shall validate that Severity is restricted to: `Blocker`, `Critical`, `Major`, `Minor`, or `Trivial`. | Unit Test |
| **FR-010** | The system shall validate that Priority is restricted to: `P1-Immediate`, `P2-High`, `P3-Medium`, or `P4-Low`. | Unit Test |

---

### 2.2 Capability 2: Defect Evidence Quality Validation

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-011** | The system shall evaluate defect evidence completeness against deterministic quality gate rules prior to allowing state transition to `Triaged`. | Integration Test |
| **FR-012** | The system shall require Steps to Reproduce to contain at least 2 distinct numbered steps and a minimum of 20 total characters before allowing transition to `Triaged`. | Unit / System Test |
| **FR-013** | The system shall require Expected Result and Actual Result to be non-empty, at least 10 characters each, and non-identical before allowing transition to `Triaged`. | Unit / System Test |
| **FR-014** | The system shall require Environment details to specify target OS, client/browser version, and deployment environment (e.g., Dev, Staging, Prod) before allowing transition to `Triaged`. | Unit / System Test |
| **FR-015** | The system shall reject transitions from `Open` to `Triaged` if any evidence quality gate rule fails, returning HTTP `422 Unprocessable Entity` with an itemized array of missing or defective evidence fields. | API / System Test |
| **FR-016** | The system shall retain the defect in `Open` status and prevent assignment or progress until all evidence deficiencies are resolved. | System Test |

---

### 2.3 Capability 3: Defect Lifecycle & State Machine

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-021** | The system shall enforce the finite-state machine transitions specified in `docs/defect-workflow.md`: `Open` &rarr; `Triaged` &rarr; `Assigned` &rarr; `In Progress` &rarr; `Fixed` &rarr; `Retest` &rarr; `Closed`. | State Transition Test |
| **FR-022** | The system shall reject any direct transition from `Open` to `Closed`, returning HTTP `400 Bad Request`. | System Test |
| **FR-023** | The system shall reject any transition from `Triaged` to `In Progress` if `assignee_id` is null or empty, returning HTTP `422 Unprocessable Entity`. | System Test |
| **FR-024** | The system shall require non-empty `resolution_notes`, `root_cause`, and fix reference before allowing a transition from `In Progress` to `Fixed`. | Integration Test |
| **FR-025** | The system shall reject any transition from `Fixed` directly to `Closed` bypassing `Retest`, returning HTTP `400 Bad Request`. | State Transition Test |
| **FR-026** | The system shall permit transition from `Retest` to `Closed` only when QA verification passes and non-empty `verification_notes` are supplied. | Integration Test |
| **FR-027** | The system shall permit transition from `Retest` to `Reopened` when verification fails, requiring non-empty `reopen_reason` (minimum 20 characters) and incrementing `reopen_count` by 1. | System Test |
| **FR-028** | The system shall permit a `Closed` defect to transition to `Reopened` upon documented regression, requiring mandatory regression justification notes. | System Test |
| **FR-029** | The system shall permit an assigned defect to be returned to `Triaged` (unassigned) by QA/Triage or Admin. | Integration Test |
| **FR-030** | The system shall reject all undefined or illegal state transitions with HTTP `400 Bad Request` and descriptive error metadata. | Negative System Test |

---

### 2.4 Capability 4: Role-Based Access Control (RBAC) & Separation of Duties

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-031** | The system shall enforce the RBAC permission matrix defined in `docs/roles-permissions.md` across all API endpoints. | Security / API Test |
| **FR-032** | The system shall permit only users with `ROLE_QA_TRIAGE` or `ROLE_ADMIN` to execute `OP_TRIAGE_DEFECT`, `OP_CHANGE_SEVERITY`, and `OP_CHANGE_PRIORITY`. | Security Test |
| **FR-033** | The system shall permit users with `ROLE_DEVELOPER` to self-assign unassigned triaged defects, but reject attempts by a Developer to reassign defects assigned to other users. | Security Test |
| **FR-034** | The system shall permit only the designated `assignee_id` (or `ROLE_ADMIN`) to transition a defect from `Assigned` to `In Progress` and `In Progress` to `Fixed`. | Security Test |
| **FR-035** | The system shall strictly forbid developers from retesting (`OP_RETEST_DEFECT`) or closing (`OP_CLOSE_DEFECT`) defects they resolved, enforcing separation of duties. | Security / System Test |
| **FR-036** | The system shall permit only users with `ROLE_QA_TRIAGE` or `ROLE_ADMIN` to close defects (`OP_CLOSE_DEFECT`) or reopen defects (`OP_REOPEN_DEFECT`). | Security Test |
| **FR-037** | The system shall reject unauthorized operations with HTTP `403 Forbidden` and log the attempted violation. | Security Audit Test |

---

### 2.5 Capability 5: Search & Multi-Attribute Filtering

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-041** | The system shall allow users to search defects by exact Defect ID and case-insensitive substring match on Title and Description. | Search Test |
| **FR-042** | The system shall allow users to filter defect results by any combination of: Status, Severity, Priority, Module, Assignee, Reporter, and Creation Date Range. | Multi-filter Test |
| **FR-043** | The system shall return search and filter results paginated with default page size of 20 and customizable page size up to 100 records. | API Pagination Test |
| **FR-044** | The system shall support sorting search results by `created_at`, `updated_at`, `severity`, and `priority` in ascending or descending order. | Query Sorting Test |

---

### 2.6 Capability 6: Audit History & Traceability

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-049** | The system shall generate an immutable audit log entry for every status transition, assignee change, severity change, priority change, and field update. | Database / Audit Test |
| **FR-050** | The audit log entry shall record: `defect_id`, `changed_by_user_id`, `timestamp`, `action_type`, `field_name`, `old_value`, and `new_value`. | Integration Test |
| **FR-051** | The system shall expose a chronological audit history endpoint for any defect accessible to all authenticated roles. | API Test |
| **FR-052** | The system shall forbid mutation, editing, or deletion of existing audit log records through any API or role. | Security Test |

---

### 2.7 Capability 7: Concurrency Control (Optimistic Locking)

| Req ID | Requirement Statement (Actor – Behavior – Constraint) | Verification Method |
| :--- | :--- | :--- |
| **FR-056** | The system shall maintain an integer `version` field on each defect record, incremented by 1 on every successful mutation. | Concurrency Test |
| **FR-057** | The system shall require clients submitting updates or status transitions to include the current `version` token in the request payload or `If-Match` header. | API / Integration Test |
| **FR-058** | The system shall compare the submitted `version` token against the stored database version within an atomic database transaction. | Concurrency Test |
| **FR-059** | The system shall reject the mutation with HTTP `409 Conflict` if the submitted version is less than the current database version, preventing silent overwriting of concurrent changes. | Stale Update Test |
| **FR-060** | Upon receiving HTTP `409 Conflict`, the system shall return the latest defect representation so the user can review concurrent changes before reapplying edits. | System Test |

---

## 3. Non-Functional Requirements (NFR)

### 3.1 Security & Authentication

| Req ID | Requirement Statement | Verification Metric / Method |
| :--- | :--- | :--- |
| **NFR-001** | The system shall authenticate all API requests via secure session tokens or signed bearer tokens; unauthenticated requests shall be rejected with HTTP `401 Unauthorized`. | Automated Security Test |
| **NFR-002** | User passwords shall be salted and hashed using industry-standard algorithms (e.g., BCrypt with work factor &ge; 12 or Argon2id) before persistence. | Code & Security Review |
| **NFR-003** | The system shall sanitize all text inputs to protect against Cross-Site Scripting (XSS) and SQL Injection vulnerabilities. | Security Vulnerability Test |

---

### 3.2 Reliability, Data Integrity & Concurrency

| Req ID | Requirement Statement | Verification Metric / Method |
| :--- | :--- | :--- |
| **NFR-004** | All multi-table mutations (e.g., defect update + audit history insert) shall execute within atomic database transactions ensuring zero partial commits on failure. | Transaction Rollback Test |
| **NFR-005** | The system shall enforce database-level foreign key constraints to prevent orphaned defect history or assignment records. | Schema Integrity Test |
| **NFR-006** | Under simulated concurrent updates by multiple users to the same defect, the system shall guarantee 0% silent data overwrites (100% detection of stale updates). | Concurrency Simulation Test |

---

### 3.3 Performance & Responsiveness

| Req ID | Requirement Statement | Verification Metric / Method |
| :--- | :--- | :--- |
| **NFR-007** | The API shall process standard single-defect CRUD and transition requests in under 200 ms (95th percentile) under a normal local test load. | Performance Benchmark |
| **NFR-008** | Search and filter queries across a test database of up to 5,000 defects shall return responses in under 500 ms. | Query Benchmark Test |

---

### 3.4 Testability, Maintainability & Modularity

| Req ID | Requirement Statement | Verification Metric / Method |
| :--- | :--- | :--- |
| **NFR-009** | Business logic (workflow state transitions, evidence validation, RBAC checks) shall be decoupled from HTTP delivery mechanisms to allow 100% deterministic unit testing. | Architectural Review |
| **NFR-010** | The automated unit and integration test suite for Version 1 shall achieve minimum 85% statement coverage across core service and validation modules. | Code Coverage Report |
| **NFR-011** | The codebase shall have zero dependency on external AI services, third-party LLMs, or embedding services for all Version 1 workflows. | Dependency Audit |
| **NFR-012** | Database schema changes shall be managed through version-controlled migration scripts to ensure reproducible test environment setup. | Migration Test |

---

## 4. Traceability Summary Matrix

| Capability Name | Requirements Covered | Governing Workflow / RBAC Ref | Planned Test Suite |
| :--- | :--- | :--- | :--- |
| Defect Ingestion & Update | `FR-001` – `FR-010` | [roles-permissions.md](roles-permissions.md) §3 | `TC-DEF-001` – `TC-DEF-010` |
| Evidence Quality Validation | `FR-011` – `FR-016` | [defect-workflow.md](defect-workflow.md) §4 | `TC-EVID-001` – `TC-EVID-007` |
| Defect Lifecycle Workflow | `FR-021` – `FR-030` | [defect-workflow.md](defect-workflow.md) §3, §5 | `TC-WF-001` – `TC-WF-012` |
| Role-Based Access Control | `FR-031` – `FR-037` | [roles-permissions.md](roles-permissions.md) §4, §5 | `TC-AUTH-001` – `TC-AUTH-010` |
| Search & Filtering | `FR-041` – `FR-044` | [version-scope.md](version-scope.md) §2 | `TC-SRCH-001` – `TC-SRCH-006` |
| Audit History & Traceability | `FR-049` – `FR-052` | [defect-workflow.md](defect-workflow.md) §8 | `TC-HIST-001` – `TC-HIST-005` |
| Concurrency & Optimistic Lock | `FR-056` – `FR-060` | [defect-workflow.md](defect-workflow.md) §8 | `TC-CONC-001` – `TC-CONC-004` |
| Security & Data Integrity | `NFR-001` – `NFR-006` | System-wide policy | `TC-SEC-001` – `TC-SEC-003` |
| Performance & Testability | `NFR-007` – `NFR-012` | Quality gates | `TC-SYS-001` – `TC-SYS-004` |
