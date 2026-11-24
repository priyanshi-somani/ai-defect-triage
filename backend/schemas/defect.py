"""Defect Pydantic validation schemas.

Addresses Requirements:
- FR-001: Authenticated defect ingestion with domain fields
- FR-002: Title boundary validation (10-120 chars, non-empty, non-numeric)
- FR-003: Description boundary validation (minimum 30 chars)
- FR-004: ID, timestamp, and reporter_id assignment
- FR-005: Initial status 'Open' and version 1
- FR-006: Defect update boundary validation
- FR-009: Severity enum validation
- FR-010: Priority enum validation
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.models.enums import DefectStatus, DefectSeverity, DefectPriority


class DefectCreate(BaseModel):
    """Request payload for creating a new defect report."""
    title: str = Field(
        ...,
        description="Concise summary of the defect (10-120 characters, non-numeric, non-empty)",
    )
    description: str = Field(
        ...,
        description="Detailed description of defect symptoms and observed anomaly (min 30 characters)",
    )
    steps_to_reproduce: str = Field(
        ...,
        description="Ordered sequence of steps to reproduce the defect (min 20 characters)",
    )
    expected_result: str = Field(
        ...,
        description="Expected application behavior when following reproduction steps (min 10 characters)",
    )
    actual_result: str = Field(
        ...,
        description="Observed incorrect application behavior (min 10 characters)",
    )
    environment: str = Field(
        ...,
        description="Client/server environment details (OS, browser, build target)",
    )
    module: str = Field(
        ...,
        description="Subsystem or architectural component impacted (1-100 characters)",
    )
    severity: DefectSeverity = Field(
        default=DefectSeverity.MAJOR,
        description="Technical impact severity level",
    )
    priority: DefectPriority = Field(
        default=DefectPriority.P3,
        description="Resolution scheduling priority level",
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """Validate title length boundaries and content rules per FR-002."""
        if not isinstance(v, str):
            raise ValueError("Title must be a string.")
        v = v.strip()
        if len(v) < 10 or len(v) > 120:
            raise ValueError("Title must be between 10 and 120 characters in length.")
        if v.isdigit():
            raise ValueError("Title cannot be purely numeric.")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """Validate description minimum length per FR-003."""
        if not isinstance(v, str):
            raise ValueError("Description must be a string.")
        v = v.strip()
        if len(v) < 30:
            raise ValueError("Description must be at least 30 characters in length.")
        return v

    @field_validator("steps_to_reproduce", mode="before")
    @classmethod
    def validate_steps_to_reproduce(cls, v: str) -> str:
        """Validate reproduction steps minimum length."""
        if not isinstance(v, str):
            raise ValueError("Steps to reproduce must be a string.")
        v = v.strip()
        if len(v) < 20:
            raise ValueError("Steps to reproduce must be at least 20 characters in length.")
        return v

    @field_validator("expected_result", "actual_result", mode="before")
    @classmethod
    def validate_result_fields(cls, v: str, info) -> str:
        """Validate expected and actual result minimum lengths."""
        if not isinstance(v, str):
            raise ValueError(f"{info.field_name} must be a string.")
        v = v.strip()
        if len(v) < 10:
            field_display = info.field_name.replace("_", " ").capitalize()
            raise ValueError(f"{field_display} must be at least 10 characters in length.")
        return v

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment non-empty and max length."""
        if not isinstance(v, str):
            raise ValueError("Environment must be a string.")
        v = v.strip()
        if len(v) < 1:
            raise ValueError("Environment cannot be empty or whitespace-only.")
        if len(v) > 255:
            raise ValueError("Environment must not exceed 255 characters.")
        return v

    @field_validator("module", mode="before")
    @classmethod
    def validate_module(cls, v: str) -> str:
        """Validate module non-empty and max length."""
        if not isinstance(v, str):
            raise ValueError("Module must be a string.")
        v = v.strip()
        if len(v) < 1:
            raise ValueError("Module cannot be empty or whitespace-only.")
        if len(v) > 100:
            raise ValueError("Module must not exceed 100 characters.")
        return v


class DefectUpdate(BaseModel):
    """Request payload for updating an existing defect report."""
    title: Optional[str] = Field(
        default=None,
        description="Updated summary of the defect (10-120 characters, non-numeric, non-empty)",
    )
    description: Optional[str] = Field(
        default=None,
        description="Updated description of symptoms (min 30 characters)",
    )
    steps_to_reproduce: Optional[str] = Field(
        default=None,
        description="Updated sequence of reproduction steps (min 20 characters)",
    )
    expected_result: Optional[str] = Field(
        default=None,
        description="Updated expected behavior (min 10 characters)",
    )
    actual_result: Optional[str] = Field(
        default=None,
        description="Updated observed behavior (min 10 characters)",
    )
    environment: Optional[str] = Field(
        default=None,
        description="Updated client/server environment details (1-255 characters)",
    )
    module: Optional[str] = Field(
        default=None,
        description="Updated subsystem or architectural component (1-100 characters)",
    )
    severity: Optional[DefectSeverity] = Field(
        default=None,
        description="Updated technical severity level (governed by QA/Admin)",
    )
    priority: Optional[DefectPriority] = Field(
        default=None,
        description="Updated priority level (governed by QA/Admin)",
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Title must be a string.")
        v = v.strip()
        if len(v) < 10 or len(v) > 120:
            raise ValueError("Title must be between 10 and 120 characters in length.")
        if v.isdigit():
            raise ValueError("Title cannot be purely numeric.")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Description must be a string.")
        v = v.strip()
        if len(v) < 30:
            raise ValueError("Description must be at least 30 characters in length.")
        return v

    @field_validator("steps_to_reproduce", mode="before")
    @classmethod
    def validate_steps_to_reproduce(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Steps to reproduce must be a string.")
        v = v.strip()
        if len(v) < 20:
            raise ValueError("Steps to reproduce must be at least 20 characters in length.")
        return v

    @field_validator("expected_result", "actual_result", mode="before")
    @classmethod
    def validate_result_fields(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"{info.field_name} must be a string.")
        v = v.strip()
        if len(v) < 10:
            field_display = info.field_name.replace("_", " ").capitalize()
            raise ValueError(f"{field_display} must be at least 10 characters in length.")
        return v

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Environment must be a string.")
        v = v.strip()
        if len(v) < 1:
            raise ValueError("Environment cannot be empty or whitespace-only.")
        if len(v) > 255:
            raise ValueError("Environment must not exceed 255 characters.")
        return v

    @field_validator("module", mode="before")
    @classmethod
    def validate_module(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Module must be a string.")
        v = v.strip()
        if len(v) < 1:
            raise ValueError("Module cannot be empty or whitespace-only.")
        if len(v) > 100:
            raise ValueError("Module must not exceed 100 characters.")
        return v


class DefectResponse(BaseModel):
    """Complete defect domain representation returned by API endpoints."""
    id: str
    title: str
    description: str
    steps_to_reproduce: str
    expected_result: str
    actual_result: str
    environment: str
    module: str
    severity: DefectSeverity
    priority: DefectPriority
    status: DefectStatus
    reporter_id: int
    assignee_id: Optional[int] = None
    root_cause: Optional[str] = None
    resolution_notes: Optional[str] = None
    fix_reference: Optional[str] = None
    verification_notes: Optional[str] = None
    reopen_reason: Optional[str] = None
    reopen_count: int = 0
    version: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedDefectResponse(BaseModel):
    """Paginated defect query response schema.

    Requirements Addressed:
        FR-041: Substring search & ID lookup results.
        FR-042: Compound attribute filter results.
        FR-043: Paginated payload with total, page, page_size, total_pages.
        FR-044: Sorted defect collection.
    """
    items: List[DefectResponse] = Field(
        ...,
        description="Defect records in the current page slice",
    )
    total: int = Field(
        ...,
        description="Total number of matching defect records",
    )
    page: int = Field(
        ...,
        description="Current 1-based page number",
    )
    page_size: int = Field(
        ...,
        description="Requested number of items per page (default 20, max 100)",
    )
    total_pages: int = Field(
        ...,
        description="Total number of available pages",
    )
    defects: Optional[List[DefectResponse]] = Field(
        default=None,
        description="Alias for items collection",
    )

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_defects(self) -> "PaginatedDefectResponse":
        if self.defects is None:
            self.defects = self.items
        return self


class DefectHistoryResponse(BaseModel):
    """Immutable audit trail response schema."""
    id: int
    defect_id: str
    changed_by_user_id: int
    action_type: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    version_snapshot: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class DefectTriageRequest(BaseModel):
    """Request payload for triaging a defect through the quality gate."""
    severity: Optional[DefectSeverity] = Field(
        default=None,
        description="Confirmed or adjusted technical severity level",
    )
    priority: Optional[DefectPriority] = Field(
        default=None,
        description="Confirmed or adjusted resolution priority level",
    )


class EvidenceValidationError(BaseModel):
    """Itemized defect evidence validation error representation."""
    field: str = Field(..., description="Name of the defective field")
    message: str = Field(..., description="Description of the deficiency")
    rule: str = Field(..., description="Requirement rule ID (e.g., FR-012)")


class EvidenceValidationResponse(BaseModel):
    """Response payload for evidence inspection check."""
    is_valid: bool = Field(..., description="True if all evidence quality criteria pass")
    errors: List[EvidenceValidationError] = Field(
        default_factory=list,
        description="Itemized array of evidence deficiencies",
    )


class DefectTransitionRequest(BaseModel):
    """Unified request payload for executing a defect lifecycle state transition."""
    target_status: DefectStatus = Field(
        ...,
        description="Target lifecycle state to transition into",
    )
    assignee_id: Optional[int] = Field(
        default=None,
        description="Target developer user ID (mandatory for Assigned, optional for In Progress)",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Root cause analysis (mandatory for Fixed)",
    )
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Remediation details and resolution summary (mandatory for Fixed)",
    )
    fix_reference: Optional[str] = Field(
        default=None,
        description="Commit hash, PR URL, or build identifier containing the fix (mandatory for Fixed)",
    )
    verification_notes: Optional[str] = Field(
        default=None,
        description="QA verification notes and test build info (mandatory for Closed, min 15 chars)",
    )
    reopen_reason: Optional[str] = Field(
        default=None,
        description="Failure evidence or regression explanation (mandatory for Reopened, min 20 chars)",
    )


class DefectAssignRequest(BaseModel):
    """Request payload for assigning a defect to a developer."""
    assignee_id: int = Field(
        ...,
        description="User ID of the assigned developer",
    )


class DefectResolveRequest(BaseModel):
    """Request payload for marking a defect Fixed."""
    root_cause: str = Field(
        ...,
        description="Root cause analysis description",
    )
    resolution_notes: str = Field(
        ...,
        description="Remediation actions taken and fix summary",
    )
    fix_reference: str = Field(
        ...,
        description="Commit hash, PR link, or build artifact reference",
    )


class DefectCloseRequest(BaseModel):
    """Request payload for closing a verified defect."""
    verification_notes: str = Field(
        ...,
        description="QA verification procedure, test environment, and pass evidence (min 15 chars)",
    )


class DefectReopenRequest(BaseModel):
    """Request payload for reopening a failed retest or regressed defect."""
    reopen_reason: str = Field(
        ...,
        description="Detailed failure evidence or regression context (min 20 chars)",
    )


