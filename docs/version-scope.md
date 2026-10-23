# Project Version Scope & Release Boundaries

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Author / Engineering Lead:** Priyanshi Somani (`psomani@my.harrisburgu.edu`)  

---

## 1. Project Purpose

The purpose of this system is to help software testers, QA engineers, developers, and project leads report, organize, review, triage, and track software defects with an explicit focus on engineering discipline, evidence quality, and safe human-in-the-loop decision support.

Rather than acting as a generic issue tracker with an unconstrained AI integration, the system is engineered around four core principles:
1. **Defect Evidence Quality:** Deterministically ensuring defect reports contain sufficient, verifiable evidence before they can advance through the triage lifecycle.
2. **Safe Duplicate-Defect Detection:** Surfacing ranked potential duplicate candidates with transparent evidence explanations without ever automatically suppressing legitimate defects.
3. **Verification of AI-Assisted Triage Recommendations:** Providing advisory classifications (severity, priority, component) that require human inspection and verification.
4. **Human Control over AI Decisions:** Enforcing strict guardrails where human decisions are authoritative, AI outputs are advisory, and AI failures do not compromise core defect operations.

To demonstrate rigorous software configuration management and testing principles, the project follows a strict multi-version lifecycle. **Version 1 establishes a deterministic, AI-free baseline before any Version 2 functionality is designed or implemented.**

---

## 2. Version 1 Scope: Core Defect Management & Evidence Quality

Version 1 delivers a robust, fully deterministic defect-management foundation. **Version 1 has zero dependency on AI services, machine learning models, or external embeddings.**

### Version 1 Included Functionality

1. **Report and Update Defects (Defect Ingestion & Modification)**
   - Creation and editing of defect reports with standard engineering fields:
     - Defect ID (unique identifier)
     - Title
     - Description
     - Steps to Reproduce
     - Expected Result
     - Actual Result
     - Environment (OS, browser, app version, runtime)
     - Affected Module / Component
     - Severity and Priority
     - Status
     - Reporter and Assignee
     - Timestamps (`created_at`, `updated_at`)
     - Version / Concurrency token (for optimistic locking)
     - Resolution Information (root cause, fix notes, resolution type)
     - Optional supporting attachments/evidence references

2. **Validate Defect Evidence (Deterministic Quality Validation)**
   - Automated boundary and content checks to verify report completeness before state transitions.
   - Defects with missing reproduction steps, actual results, or environment details can be stored as initial drafts/open reports but are blocked from proceeding to `Triaged` until minimum evidence thresholds are satisfied.

3. **Manage Defect Lifecycle (Controlled Workflow State Machine)**
   - Finite state machine enforcing valid transitions:
     - `Open` &rarr; `Triaged` &rarr; `Assigned` &rarr; `In Progress` &rarr; `Fixed` &rarr; `Retest` &rarr; `Closed`
     - Retest failure path: `Retest` &rarr; `Reopened` &rarr; `Assigned` / `In Progress`
   - Enforcement of state pre-conditions (e.g., cannot move to `Assigned` without an assignee, cannot move to `Fixed` without resolution details, cannot bypass triage directly to `Closed`).

4. **Assignment and Role-Based Permissions (RBAC)**
   - Documented permission matrix for standard roles:
     - **Reporter:** Can create defects, view defects, update own defects.
     - **Developer:** Can update status to `In Progress` and `Fixed`, view defects.
     - **QA / Triage User:** Can triage defects, validate evidence, perform retests, reopen defects.
     - **Admin:** Full administrative and user management authority.
   - Rejection of unauthorized state transitions and field mutations.

5. **Search and Filtering (Multi-Attribute Querying)**
   - Search by Defect ID and keyword.
   - Filter by status, severity, priority, module, assignee, reporter, and creation date range.

6. **Defect History (Immutable Audit Log & Traceability)**
   - Immutable audit logging for critical defect mutations (status transitions, assignee changes, severity/priority updates, and resolution notes).
   - Traceability of user ID, timestamp, and field deltas (previous value vs. new value).

7. **Concurrent-Update Protection (Optimistic Concurrency Control)**
   - Optimistic concurrency control using an incremental version field / concurrency token.
   - Detection and controlled rejection of stale updates to prevent silent data loss during concurrent edits.

### Version 1 Exclusions (Strict Non-Goals for V1)

The following capabilities are strictly excluded from Version 1:
- AI API integration (external or local)
- Embeddings and vector representations
- Semantic duplicate detection
- AI severity recommendation
- AI priority recommendation
- AI category / component recommendation
- AI summary generation
- AI tagging
- AI confidence scores
- AI evaluation metrics
- Any database tables or schema fields dedicated to AI recommendations or duplicate scoring

---

## 3. Version 1 Completion Criteria

Version 1 is officially complete and eligible for baseline tagging only when all of the following gates are met:
- [ ] All approved Version 1 functionality and requirements are implemented.
- [ ] Defect workflow rules and lifecycle transitions work correctly.
- [ ] Role-based access control and permission rules work correctly.
- [ ] Evidence validation rules deterministically block incomplete defect promotion.
- [ ] Search and multi-attribute filter functionality works correctly.
- [ ] Defect history tracking records all critical mutations accurately.
- [ ] Concurrent updates are handled safely with stale update rejection (optimistic locking).
- [ ] 100% of automated unit, integration, and end-to-end regression tests pass.
- [ ] The complete Version 1 system test is executed covering all test areas (creation, validation, workflow, permissions, assignment, search, history, persistence, concurrency).
- [ ] Version 1 system test results are formally recorded in `docs/testing/v1-system-test-results.md`.
- [ ] Critical defects or failures discovered during testing are resolved or formally cataloged with justification.
- [ ] Project documentation (`requirements.md`, `defect-workflow.md`, `roles-permissions.md`, `risk-register.md`, `test-plan.md`, `architecture.md`, `scm-plan.md`) is synchronized with the implemented codebase.

### Stable Release Baseline: `v1.0.0`
- Only after all completion criteria are satisfied may the project create the first stable baseline tagged in Git as: **`v1.0.0`**.
- **Rule:** Version 2 development must begin only after the Version 1 baseline is complete and formally tagged.

---

## 4. Version 2 Scope: AI-Assisted Deduplication & Triage Verification

Version 2 introduces advisory decision-support capabilities, augmenting the stable Version 1 foundation with AI assistance and verification workflows.

### Version 2 Included Functionality (Planned)

1. **Potential Duplicate-Defect Detection**
   - Evaluates incoming defect text/evidence against existing defects using similarity modeling.
   - Computes similarity representations and compares defect reports.

2. **Ranked Duplicate Candidates with Evidence Explanations**
   - Returns ranked potential matches with confidence/similarity scores and transparent evidence overlap (e.g., shared error codes, common reproduction steps, matching components).

3. **Human Confirmation of Duplicate Status**
   - Explicit human review is required to declare a defect a duplicate.
   - **Guardrail:** The system must **never** automatically suppress, close, or modify a defect solely because an AI recommendation or similarity score flags it as a duplicate.

4. **AI-Assisted Triage Recommendations**
   - AI-assisted severity recommendation.
   - AI-assisted priority recommendation.
   - AI-assisted category / component recommendation.
   - AI-assisted summary and tag recommendations.

5. **Accept / Modify / Reject Workflow**
   - Triage recommendations are presented as strictly advisory suggestions.
   - The user has complete authority to Accept, Modify, or Reject any recommendation before committing changes.
   - Telemetry is recorded on user decisions to evaluate AI accuracy.

6. **AI Guardrails & Human Control**
   - AI recommendations must never automatically overwrite user values without confirmation.
   - Structured JSON schema validation: Malformed or unverified AI responses are rejected safely.
   - Human decisions remain final at all times.

7. **AI Privacy Handling**
   - Pre-filtering and sanitization of defect data prior to external transmission.
   - Sensitive information, secrets, API tokens, credentials, and internal proprietary URLs are stripped before querying external AI services.

8. **AI-Service Failure Handling & Resiliency**
   - When external AI services are unavailable, experience timeouts, or return errors, the system fails open gracefully to the deterministic Version 1 workflow without disrupting normal defect operations.

9. **Duplicate-Detection & Triage Evaluation**
   - Version-controlled reference evaluation dataset containing known duplicate pairs, known non-duplicate pairs, boundary cases, and verified classifications.
   - Quantitative evaluation measuring True Positives, False Positives, True Negatives, False Negatives, Precision, Recall, and F1 score.
   - Specific analysis on False Positives to ensure legitimate defects are not obscured.
   - Classification accuracy, per-category accuracy, and override rate tracking.

10. **Regression Testing of Version 1**
    - The complete Version 1 automated test suite must run and pass as a regression gate when Version 2 capabilities are integrated.

---

## 5. Version 2 Deferred Capabilities

The following capabilities are **explicitly out of scope for Version 1** and strictly deferred to Version 2:
- Vector embeddings, similarity algorithms, and candidate ranking.
- External LLM / AI API integration (e.g., Google Gemini API, OpenAI).
- AI prompt templates and structured JSON response schemas.
- Duplicate candidate presentation and comparison UI/API endpoints.
- Recommendation acceptance/rejection/modification telemetry and endpoints.
- Sensitive data and secret redaction filters for external AI payloads.
- AI evaluation reference dataset, benchmark test harness, and confusion matrices.
- Database tables or schema fields dedicated to AI recommendations (`ai_recommendations`, `duplicate_candidates`).
