"""Defect Pydantic validation schemas.

Addresses Requirements:
- FR-001: Authenticated defect ingestion with domain fields
- FR-002: Title boundary validation (10-120 chars, non-empty, non-numeric)
- FR-003: Description boundary validation (minimum 30 chars)
- FR-004: ID, timestamp, and reporter_id assignment
- FR-005: Initial status 'Open' and version 1
- FR-009: Severity enum validation
- FR-010: Priority enum validation
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
