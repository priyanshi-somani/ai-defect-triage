"""Domain model enumerations."""

from enum import Enum


class UserRole(str, Enum):
    """User roles defining system authorization boundaries."""
    REPORTER = "ROLE_REPORTER"
    DEVELOPER = "ROLE_DEVELOPER"
    QA_TRIAGE = "ROLE_QA_TRIAGE"
    ADMIN = "ROLE_ADMIN"
