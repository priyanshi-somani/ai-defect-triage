# Project Risk Register & Traceability Matrix

**Course:** CISC 594 – Software Testing Principles & Techniques (Harrisburg University)  
**Project Name:** AI-Assisted Bug Triage & Defect Management System  
**Document Reference:** `docs/risk-register.md`  
**Version:** 1.0 (Version 1 Baseline with Version 2 Risk Catalog)  

---

## 1. Risk Engineering Methodology

This document maintains the project Risk Register in accordance with course software testing and quality assurance principles. 

For every major system capability, risks are analyzed and managed using a five-stage engineering traceability model:

$$\text{Capability} \longrightarrow \text{Undesired Event} \longrightarrow \text{Risk Analysis} \longrightarrow \text{Mitigation Requirement} \longrightarrow \text{Verification Test}$$

### Qualitative Risk Matrix Scoring
- **Likelihood:** Low (1), Medium (2), High (3)
- **Impact:** Low (1), Medium (2), High (3), Critical (4)
- **Risk Level:**  
  - **High:** $\ge 8$  
  - **Medium:** $4 - 6$  
  - **Low:** $\le 3$

---

## 2. Version 1 Risk Register

The following risks pertain directly to the core deterministic defect management and evidence validation foundation in Version 1.

| Risk ID | Capability | Undesired Event | Risk Description & Consequence | Likelihood | Impact | Risk Level | Mitigation Requirement | Linked Verification Test | Status |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- | :---: |
| **RISK-V1-001** | Defect Lifecycle Management | Invalid or illegal state transition | Defect bypasses triage (e.g., `Open` &rarr; `Closed`), moves to `Fixed` without progress, or bypasses QA retest. Unverified code reaches production. | Medium (2) | Critical (4) | **High (8)** | `FR-021`, `FR-022`, `FR-025`, `FR-030` | `TC-WF-001` to `TC-WF-006` | Mitigated by FSM Design |
| **RISK-V1-002** | Role-Based Access Control | Unauthorized operation & privilege escalation | Developer or Reporter closes a defect, self-approves a fix, alters triage priority, or modifies another user's defect. Breaks separation of duties. | High (3) | Critical (4) | **High (12)** | `FR-031`, `FR-032`, `FR-035`, `FR-036`, `FR-037` | `TC-AUTH-001` to `TC-AUTH-008` | Mitigated by RBAC Policy |
| **RISK-V1-003** | Evidence Quality Validation | Missing or poor evidence admitted to triage | Defect with empty reproduction steps, missing environment, or vague symptoms is promoted to development. Causes severe engineering delays and unreproducible bug reports. | High (3) | High (3) | **High (9)** | `FR-011`, `FR-012`, `FR-013`, `FR-014`, `FR-015` | `TC-EVID-001` to `TC-EVID-006` | Mitigated by Quality Gate |
| **RISK-V1-004** | Concurrency Control | Silent data overwrites during concurrent edits | User A and User B open the same defect concurrently; User A saves edits, and User B unknowingly overwrites them with stale data. Data loss and inconsistent state. | Medium (2) | High (3) | **Medium (6)** | `FR-056`, `FR-057`, `FR-058`, `FR-059`, `FR-060` | `TC-CONC-001` to `TC-CONC-004` | Mitigated by Optimistic Locking |
| **RISK-V1-005** | Audit & Traceability | Lost or tampered defect history | Critical mutations (status change, reassignment, severity alteration) occur without an audit entry, or history is altered. Prevents auditability and professor evaluation. | Low (1) | High (3) | **Low (3)** | `FR-049`, `FR-050`, `FR-051`, `FR-052`, `NFR-004` | `TC-HIST-001` to `TC-HIST-004` | Mitigated by Immutable DB Log |
| **RISK-V1-006** | Defect Assignment | Unaccountable development progress | Defect moves to `In Progress` without an assignee, or developer works on another developer's task without coordination. Leads to orphaned work or race conditions. | Medium (2) | Medium (2) | **Medium (4)** | `FR-023`, `FR-033`, `FR-034` | `TC-WF-003`, `TC-AUTH-005`, `TC-AUTH-006` | Mitigated by Assignee Guard |
| **RISK-V1-007** | Defect Resolution | Fix submitted without diagnostic details | Defect is marked `Fixed` without root-cause documentation or fix commit reference. QA cannot verify fix mechanics or prepare regression tests. | Medium (2) | Medium (2) | **Medium (4)** | `FR-024` | `TC-WF-004` | Mitigated by Field Precondition |
| **RISK-V1-008** | Verification & Retest | Unverified defect closure | Defect is closed directly after fix submission without staging retest by QA. High likelihood of defect recurrence or regression in production. | Medium (2) | Critical (4) | **High (8)** | `FR-025`, `FR-026`, `FR-035` | `TC-WF-005`, `TC-WF-006`, `TC-AUTH-007`, `TC-AUTH-008` | Mitigated by Retest Gate |

---

## 3. Version 2 Planned Risk Catalog (AI Decision Support)

The following risks are formally documented now to govern the design of Version 2 guardrails and evaluation harnesses once Version 1 is complete.

| Risk ID | Capability | Undesired Event | Risk Description & Consequence | Likelihood | Impact | Risk Level | Planned Mitigation Requirement | Planned Verification Test | Status |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- | :---: |
| **RISK-V2-001** | Duplicate Detection | False Positive duplicate match | Unrelated defect is misidentified as a duplicate and suppressed. A critical bug goes unaddressed in production. | High (3) | Critical (4) | **High (12)** | System **never** automatically suppresses defects; duplicate status requires explicit human confirmation. | `TC-AI-DUP-001` (known non-duplicate pair with similar terms) | Cataloged for V2 |
| **RISK-V2-002** | Duplicate Detection | False Negative duplicate match | Legitimate duplicate is missed by similarity model. Results in redundant developer debugging effort. | Medium (2) | Low (1) | **Low (2)** | Hybrid lexical + semantic ranking; similarity threshold optimization against evaluation dataset. | `TC-AI-DUP-002` (known duplicate pair with differing phrasing) | Cataloged for V2 |
| **RISK-V2-003** | AI Triage Verification | Over-reliance on inaccurate AI recommendation | AI recommends incorrect severity (e.g., marks Blocker as Trivial). Critical defect is deprioritized. | Medium (2) | High (3) | **Medium (6)** | AI output labeled strictly advisory; human Accept/Modify/Reject workflow; override telemetry recorded. | `TC-AI-TRI-001` to `TC-AI-TRI-003` (user override test) | Cataloged for V2 |
| **RISK-V2-004** | AI Service Integration | Malformed / hallucinated AI response payload | External LLM returns non-JSON text or schema-violating field values, causing runtime parsing crashes. | Medium (2) | High (3) | **Medium (6)** | Strict Pydantic / JSON schema validation; discard malformed AI response and fail open to human triage. | `TC-AI-GRD-001` (schema violation test) | Cataloged for V2 |
| **RISK-V2-005** | Service Availability | AI service outage / timeout blocks defect workflow | External AI provider is down, rate-limited, or timing out. Testers are blocked from logging or triaging bugs. | Medium (2) | High (3) | **Medium (6)** | Circuit breaker and timeout fallback: core defect CRUD and manual triage operate with 0% AI dependency. | `TC-AI-GRD-002` (AI outage simulation) | Cataloged for V2 |
| **RISK-V2-006** | Data Privacy & Security | Transmission of sensitive credentials / PII to LLM | Defect description or logs contain API keys, passwords, or customer PII that leak to third-party AI provider. | Medium (2) | Critical (4) | **High (8)** | Pre-transmission regex and heuristic sanitization filter to redact tokens, emails, and secrets before AI call. | `TC-AI-PRIV-001` (secret redaction test) | Cataloged for V2 |

---

## 4. Risk Mitigation Lifecycle & Verification Strategy

1. **Pre-Implementation Verification:**  
   Every Version 1 risk in Section 2 is tied to a specific Functional Requirement (`FR-xxx`) that dictates backend architectural enforcement.
2. **Implementation Verification:**  
   As each feature is implemented, the corresponding verification tests (`TC-xxx`) will be executed in automated CI test suites.
3. **Formal System Test Verification:**  
   Prior to tagging `v1.0.0`, all high and medium risks must show verified test execution in [testing/v1-system-test-results.md](testing/v1-system-test-results.md) with zero unresolved failures.
