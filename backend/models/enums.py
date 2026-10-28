"""Domain model enumerations."""

from enum import Enum


class UserRole(str, Enum):
    """User roles defining system authorization boundaries."""
    REPORTER = "ROLE_REPORTER"
    DEVELOPER = "ROLE_DEVELOPER"
    QA_TRIAGE = "ROLE_QA_TRIAGE"
    ADMIN = "ROLE_ADMIN"


class DefectStatus(str, Enum):
    """Defect lifecycle workflow statuses."""
    OPEN = "Open"
    TRIAGED = "Triaged"
    ASSIGNED = "Assigned"
    IN_PROGRESS = "In Progress"
    FIXED = "Fixed"
    RETEST = "Retest"
    CLOSED = "Closed"
    REOPENED = "Reopened"


class DefectSeverity(str, Enum):
    """Defect technical and impact severity levels."""
    BLOCKER = "Blocker"
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    TRIVIAL = "Trivial"


class DefectPriority(str, Enum):
    """Defect scheduling and resolution priority levels."""
    P1 = "P1-Immediate"
    P2 = "P2-High"
    P3 = "P3-Medium"
    P4 = "P4-Low"


class AuditActionType(str, Enum):
    """Audit history mutation action types."""
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    ASSIGNED = "ASSIGNED"
    REOPENED = "REOPENED"
