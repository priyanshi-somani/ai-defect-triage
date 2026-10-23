# Role-Based Access Control (RBAC) & Permission Matrix

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Document Reference:** `docs/roles-permissions.md`  
**Version:** 1.0 (Baseline for Version 1)  

---

## 1. Document Purpose

This document establishes the formal Role-Based Access Control (RBAC) model and authorization rules for the defect management system. 

In accordance with course engineering standards, authorization boundaries must not be implicit in implementation code. Instead, every operation, permission check, and role restriction is specified deterministically in this document to enable comprehensive unit, integration, and security testing.

---

## 2. User Roles

The system defines four discrete user roles for Version 1:

| Role | Role Identifier | Description & System Scope |
| :--- | :--- | :--- |
| **Reporter** | `ROLE_REPORTER` | Frontline tester, external contributor, customer support agent, or product user who discovers and reports anomalies. Permitted to submit defects, view defects, and update their own defects while in draft/open status. Cannot perform triage, approve fixes, or close defects. |
| **Developer** | `ROLE_DEVELOPER` | Software engineer responsible for investigating, debugging, and resolving defects. Permitted to assign defects to themselves, transition assigned defects to `In Progress`, record resolution details (root cause, fix commit), and mark defects `Fixed`. Cannot triage incoming defects, sign off on retests, or close defects. |
| **QA / Triage User** | `ROLE_QA_TRIAGE` | Quality assurance engineer, defect manager, or triage lead responsible for defect evidence validation, severity/priority governance, assignment coordination, retesting, and defect closure. Serves as the primary gatekeeper for the defect lifecycle. |
| **Admin** | `ROLE_ADMIN` | System administrator with global operational authority. Permitted to perform all defect operations, override assignments, manage user accounts, and resolve deadlocked workflows. Subject to finite-state machine integrity rules (cannot bypass workflow rules without formal history audit). |

---

## 3. Operations Catalog

The system defines the following controlled defect operations:

1. **`OP_CREATE_DEFECT`**: Submit a new defect report into the system.
2. **`OP_VIEW_DEFECT`**: Retrieve and view defect details, evidence, and history.
3. **`OP_UPDATE_OWN_DEFECT`**: Edit description, steps, or environment of a defect authored by the requesting user while the defect is in `Open` state.
4. **`OP_UPDATE_ANY_DEFECT`**: Modify defect core fields regardless of reporter identity.
5. **`OP_CHANGE_SEVERITY`**: Alter the technical impact classification (`Blocker`, `Critical`, `Major`, `Minor`, `Trivial`).
6. **`OP_CHANGE_PRIORITY`**: Alter the scheduling urgency classification (`P1-Immediate`, `P2-High`, `P3-Medium`, `P4-Low`).
7. **`OP_VALIDATE_EVIDENCE`**: Evaluate defect evidence against completeness criteria.
8. **`OP_TRIAGE_DEFECT`**: Move a defect from `Open` to `Triaged` upon satisfying evidence thresholds.
9. **`OP_ASSIGN_DEFECT`**: Assign or reassign a defect to a developer.
10. **`OP_START_PROGRESS`**: Move a defect from `Assigned` to `In Progress`.
11. **`OP_RESOLVE_DEFECT`**: Mark a defect `Fixed` and attach mandatory resolution information.
12. **`OP_RETEST_DEFECT`**: Execute verification on a fixed defect (`Fixed` &rarr; `Retest`).
13. **`OP_CLOSE_DEFECT`**: Verify successful fix and mark defect `Closed`.
14. **`OP_REOPEN_DEFECT`**: Transition a defect from `Retest` or `Closed` back to `Reopened` due to failed verification or regression.
15. **`OP_VIEW_AUDIT_LOG`**: Access complete, immutable history deltas for a defect.

---

## 4. RBAC Permission Matrix

The following matrix governs authorization for all defect operations. Every access control check in the service layer must validate against this matrix.

| Operation | Reporter | Developer | QA / Triage User | Admin | Policy Enforcement Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`OP_CREATE_DEFECT`** | **ALLOWED** | **ALLOWED** | **ALLOWED** | **ALLOWED** | Any authenticated user may report a defect. |
| **`OP_VIEW_DEFECT`** | **ALLOWED** | **ALLOWED** | **ALLOWED** | **ALLOWED** | All defects are readable by all authenticated roles. |
| **`OP_UPDATE_OWN_DEFECT`** | **CONDITIONAL** | **CONDITIONAL** | **ALLOWED** | **ALLOWED** | Allowed for Reporter/Developer only if `user_id == reporter_id` AND status is `Open`. |
| **`OP_UPDATE_ANY_DEFECT`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Restricts arbitrary field edits by non-triage roles. |
| **`OP_CHANGE_SEVERITY`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Reporters propose initial severity, but QA/Triage governs final severity. |
| **`OP_CHANGE_PRIORITY`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Priority is a triage scheduling decision owned by QA/Triage/Admin. |
| **`OP_VALIDATE_EVIDENCE`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Evidence gatekeeper check owned by QA/Triage. |
| **`OP_TRIAGE_DEFECT`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Only QA/Triage or Admin can officially promote a defect to `Triaged`. |
| **`OP_ASSIGN_DEFECT`** | **DENIED** | **CONDITIONAL** | **ALLOWED** | **ALLOWED** | Developers may only self-assign unassigned triaged defects. QA/Admin can assign anyone. |
| **`OP_START_PROGRESS`** | **DENIED** | **CONDITIONAL** | **DENIED** | **ALLOWED** | Developer must be the designated assignee to transition to `In Progress`. |
| **`OP_RESOLVE_DEFECT`** | **DENIED** | **CONDITIONAL** | **DENIED** | **ALLOWED** | Must be assigned developer; requires resolution details (root cause, fix notes). |
| **`OP_RETEST_DEFECT`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Developers cannot retest their own code. Requires QA/Triage or Admin. |
| **`OP_CLOSE_DEFECT`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Strict separation of concerns: only QA/Triage or Admin can close defects. |
| **`OP_REOPEN_DEFECT`** | **DENIED** | **DENIED** | **ALLOWED** | **ALLOWED** | Only QA/Triage or Admin can reopen defects after retest failure or regression. |
| **`OP_VIEW_AUDIT_LOG`** | **ALLOWED** | **ALLOWED** | **ALLOWED** | **ALLOWED** | Audit transparency is open to all authenticated roles. |

---

## 5. Security & Authorization Business Rules

To prevent authorization bypass and maintain separation of duties, the system enforces the following explicit rules:

1. **Separation of Duties (No Self-Approval):**  
   A developer who resolves a defect cannot perform `OP_RETEST_DEFECT` or `OP_CLOSE_DEFECT` on that same defect. Closure requires independent verification by `ROLE_QA_TRIAGE` or `ROLE_ADMIN`.

2. **Self-Assignment Boundary:**  
   A developer (`ROLE_DEVELOPER`) can only assign an unassigned defect to themselves. A developer cannot reassign defects away from or between other developers without `ROLE_QA_TRIAGE` or `ROLE_ADMIN` privileges.

3. **Immutability of Author Identity:**  
   The `reporter_id` field is set automatically by the authentication context upon creation and cannot be modified by any role, including `ROLE_ADMIN`, ensuring audit integrity.

4. **Status-Dependent Update Permissions:**  
   Reporters may edit their own defect descriptions and steps to reproduce while the defect is in `Open` status to rectify evidence deficiencies. Once a defect moves to `Triaged` or beyond, only `ROLE_QA_TRIAGE` or `ROLE_ADMIN` can edit core report fields.

5. **Auditing of Authorization Failures:**  
   Any attempt to perform an operation not permitted by the RBAC matrix must result in an immediate HTTP `403 Forbidden` response and be logged for security monitoring.
