"""Evidence quality validation service.

Enforces deterministic quality gate rules (FR-011 through FR-016) before
defects can transition from 'Open' to 'Triaged'.
"""

import re
import logging
from typing import List, Optional, Dict, Any, Union
from fastapi import HTTPException, status

from backend.models.defect import Defect
from backend.models.enums import DefectSeverity, DefectPriority
from backend.schemas.defect import EvidenceValidationError, EvidenceValidationResponse

logger = logging.getLogger("evidence.validation")


class EvidenceValidationResult:
    """Aggregate result of evidence quality evaluation."""

    def __init__(self, is_valid: bool, errors: Optional[List[EvidenceValidationError]] = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def has_error_for(self, field: str) -> bool:
        """Check if a specific field has a validation error."""
        return any(e.field == field for e in self.errors)

    def get_errors_for(self, field: str) -> List[EvidenceValidationError]:
        """Get all validation errors for a specific field."""
        return [e for e in self.errors if e.field == field]

    def to_dict_list(self) -> List[Dict[str, str]]:
        """Convert errors to itemized dictionary representation."""
        return [err.model_dump() for err in self.errors]


class EvidenceQualityError(HTTPException):
    """HTTP 422 exception raised when defect evidence fails quality gate rules.
    
    Requirements:
        FR-015: Rejected with HTTP 422 Unprocessable Entity with itemized array.
    """

    def __init__(self, errors: List[Dict[str, Any]]):
        super().__init__(
            status_code=422,
            detail=errors,
        )
        self.errors = errors


class EvidenceValidationService:
    """Service evaluating deterministic defect evidence quality gate rules.

    Requirements Addressed:
        FR-011: Complete deterministic quality evaluation prior to 'Triaged'.
        FR-012: Steps to Reproduce >= 2 numbered steps and >= 20 total chars.
        FR-013: Expected and Actual results >= 10 chars each and non-identical.
        FR-014: Environment specifies target OS, client/browser version, and tier.
        FR-015: Reject transitions with HTTP 422 containing itemized error array.
        FR-016: Defect retained in 'Open' until all evidence is resolved.
    """

    # Structured step pattern: numbers followed by dot/paren/hyphen or 'Step N' followed by punctuation/space
    STEP_PATTERN = re.compile(
        r'(?:^|[\n\r]|(?<=[.!?;\s]))\s*(?:(?:Step\s*(\d+))|(\d+)[\.\)\-\]])(?:\s*[:\.\-]?\s+)',
        re.IGNORECASE,
    )

    # Environment component detection patterns
    OS_PATTERN = re.compile(
        r'\b(windows|macos|mac\s*os|osx|os\s*x|linux|ubuntu|debian|fedora|centos|redhat|red\s*hat|rhel|android|ios|unix|arch|suse|alpine)\b|(?:\bos\s*[:=])',
        re.IGNORECASE,
    )
    CLIENT_PATTERN = re.compile(
        r'\b(chrome|firefox|safari|edge|opera|brave|chromium|postman|curl|browser|client|app|cli)\b|(?:\b(?:browser|client)\s*[:=])',
        re.IGNORECASE,
    )
    TIER_PATTERN = re.compile(
        r'\b(dev|development|staging|stage|prod|production|qa|test|testing|uat|local|sandbox)\b|(?:\b(?:env|environment|tier)\s*[:=])',
        re.IGNORECASE,
    )

    @classmethod
    def validate_steps_to_reproduce(cls, steps: Optional[str]) -> List[EvidenceValidationError]:
        """Validate steps to reproduce against FR-012.

        Rules:
            1. Non-empty text.
            2. Minimum 20 total characters.
            3. At least 2 distinct numbered steps.
        """
        errors: List[EvidenceValidationError] = []

        if not steps or not steps.strip():
            errors.append(
                EvidenceValidationError(
                    field="steps_to_reproduce",
                    message="Steps to reproduce cannot be empty and must contain at least 2 distinct numbered steps (minimum 20 characters).",
                    rule="FR-012",
                )
            )
            return errors

        stripped = steps.strip()
        if len(stripped) < 20:
            errors.append(
                EvidenceValidationError(
                    field="steps_to_reproduce",
                    message="Steps to reproduce must be at least 20 characters in length.",
                    rule="FR-012",
                )
            )

        matches = cls.STEP_PATTERN.findall(stripped)
        distinct_steps = {m[0] or m[1] for m in matches if m[0] or m[1]}
        if len(distinct_steps) < 2:
            errors.append(
                EvidenceValidationError(
                    field="steps_to_reproduce",
                    message="Steps to reproduce must contain at least 2 distinct numbered steps (e.g., '1. ... 2. ...').",
                    rule="FR-012",
                )
            )

        return errors

    @classmethod
    def validate_results(cls, expected: Optional[str], actual: Optional[str]) -> List[EvidenceValidationError]:
        """Validate expected and actual results against FR-013.

        Rules:
            1. Expected result non-empty and >= 10 characters.
            2. Actual result non-empty and >= 10 characters.
            3. Expected result and actual result must not be identical.
        """
        errors: List[EvidenceValidationError] = []
        expected_clean = (expected or "").strip()
        actual_clean = (actual or "").strip()

        if not expected_clean or len(expected_clean) < 10:
            errors.append(
                EvidenceValidationError(
                    field="expected_result",
                    message="Expected result must be non-empty and at least 10 characters in length.",
                    rule="FR-013",
                )
            )

        if not actual_clean or len(actual_clean) < 10:
            errors.append(
                EvidenceValidationError(
                    field="actual_result",
                    message="Actual result must be non-empty and at least 10 characters in length.",
                    rule="FR-013",
                )
            )

        if expected_clean and actual_clean and len(expected_clean) >= 10 and len(actual_clean) >= 10:
            if expected_clean.lower() == actual_clean.lower():
                errors.append(
                    EvidenceValidationError(
                        field="actual_result",
                        message="Actual result and expected result must not be identical.",
                        rule="FR-013",
                    )
                )

        return errors

    @classmethod
    def validate_environment(cls, environment: Optional[str]) -> List[EvidenceValidationError]:
        """Validate environment details against FR-014.

        Rules:
            1. Non-empty string.
            2. Specifies target OS.
            3. Specifies client/browser version.
            4. Specifies deployment environment (Dev, Staging, Prod, etc.).
        """
        errors: List[EvidenceValidationError] = []

        if not environment or not environment.strip():
            errors.append(
                EvidenceValidationError(
                    field="environment",
                    message="Environment details cannot be empty and must specify target OS, client/browser version, and deployment environment.",
                    rule="FR-014",
                )
            )
            return errors

        env_str = environment.strip()
        missing_parts: List[str] = []

        if not cls.OS_PATTERN.search(env_str):
            missing_parts.append("target OS")
        if not cls.CLIENT_PATTERN.search(env_str):
            missing_parts.append("client/browser version")
        if not cls.TIER_PATTERN.search(env_str):
            missing_parts.append("deployment environment (e.g., Dev, Staging, Prod)")

        if missing_parts:
            errors.append(
                EvidenceValidationError(
                    field="environment",
                    message=f"Environment details missing required specifications: {', '.join(missing_parts)}.",
                    rule="FR-014",
                )
            )

        return errors

    @classmethod
    def validate_title(cls, title: Optional[str]) -> List[EvidenceValidationError]:
        """Validate title boundaries and content rules per FR-002."""
        errors: List[EvidenceValidationError] = []
        title_clean = (title or "").strip()

        if not title_clean or len(title_clean) < 10 or len(title_clean) > 120:
            errors.append(
                EvidenceValidationError(
                    field="title",
                    message="Title must be between 10 and 120 characters in length.",
                    rule="FR-002",
                )
            )
        elif title_clean.isdigit():
            errors.append(
                EvidenceValidationError(
                    field="title",
                    message="Title cannot be purely numeric.",
                    rule="FR-002",
                )
            )

        return errors

    @classmethod
    def validate_description(cls, description: Optional[str]) -> List[EvidenceValidationError]:
        """Validate description minimum length per FR-003."""
        errors: List[EvidenceValidationError] = []
        desc_clean = (description or "").strip()

        if not desc_clean or len(desc_clean) < 30:
            errors.append(
                EvidenceValidationError(
                    field="description",
                    message="Description must be at least 30 characters in length.",
                    rule="FR-003",
                )
            )

        return errors

    @classmethod
    def validate_module(cls, module: Optional[str]) -> List[EvidenceValidationError]:
        """Validate module specification per FR-001."""
        errors: List[EvidenceValidationError] = []
        mod_clean = (module or "").strip()

        if not mod_clean or len(mod_clean) > 100:
            errors.append(
                EvidenceValidationError(
                    field="module",
                    message="Module must be specified and not exceed 100 characters.",
                    rule="FR-001",
                )
            )

        return errors

    @classmethod
    def validate_enums(cls, severity: Any, priority: Any) -> List[EvidenceValidationError]:
        """Validate severity and priority domain enumerations per FR-009 and FR-010."""
        errors: List[EvidenceValidationError] = []

        valid_severities = {s.value for s in DefectSeverity}
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        if sev_val not in valid_severities:
            errors.append(
                EvidenceValidationError(
                    field="severity",
                    message=f"Severity must be one of: {', '.join(sorted(valid_severities))}.",
                    rule="FR-009",
                )
            )

        valid_priorities = {p.value for p in DefectPriority}
        prio_val = priority.value if hasattr(priority, "value") else str(priority)
        if prio_val not in valid_priorities:
            errors.append(
                EvidenceValidationError(
                    field="priority",
                    message=f"Priority must be one of: {', '.join(sorted(valid_priorities))}.",
                    rule="FR-010",
                )
            )

        return errors

    @classmethod
    def evaluate_evidence(cls, defect: Union[Defect, Dict[str, Any]]) -> EvidenceValidationResult:
        """Evaluate all evidence quality gate rules deterministically.

        Accepts either a Defect ORM model or a dictionary containing defect fields.
        """
        if isinstance(defect, dict):
            title = defect.get("title")
            description = defect.get("description")
            steps = defect.get("steps_to_reproduce")
            expected = defect.get("expected_result")
            actual = defect.get("actual_result")
            environment = defect.get("environment")
            module = defect.get("module")
            severity = defect.get("severity")
            priority = defect.get("priority")
        else:
            title = defect.title
            description = defect.description
            steps = defect.steps_to_reproduce
            expected = defect.expected_result
            actual = defect.actual_result
            environment = defect.environment
            module = defect.module
            severity = defect.severity
            priority = defect.priority

        errors: List[EvidenceValidationError] = []

        # Core Evidence Requirements (FR-012, FR-013, FR-014)
        errors.extend(cls.validate_steps_to_reproduce(steps))
        errors.extend(cls.validate_results(expected, actual))
        errors.extend(cls.validate_environment(environment))

        # Additional Defect Validity Rules (FR-001, FR-002, FR-003, FR-009, FR-010)
        errors.extend(cls.validate_title(title))
        errors.extend(cls.validate_description(description))
        errors.extend(cls.validate_module(module))
        errors.extend(cls.validate_enums(severity, priority))

        is_valid = len(errors) == 0
        return EvidenceValidationResult(is_valid=is_valid, errors=errors)

    @classmethod
    def validate_or_raise(cls, defect: Union[Defect, Dict[str, Any]]) -> EvidenceValidationResult:
        """Evaluate evidence quality and raise EvidenceQualityError (HTTP 422) on failure.
        
        Requirements:
            FR-015: Reject transitions with HTTP 422 Unprocessable Entity with itemized errors.
        """
        result = cls.evaluate_evidence(defect)
        if not result.is_valid:
            error_dicts = result.to_dict_list()
            logger.warning(
                "EVIDENCE_GATE_REJECTED: Evidence validation failed with %d defect(s): %s",
                len(error_dicts),
                error_dicts,
            )
            raise EvidenceQualityError(errors=error_dicts)
        return result
