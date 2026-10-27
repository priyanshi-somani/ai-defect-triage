"""Defect SQLAlchemy ORM entity."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.enums import DefectStatus, DefectSeverity, DefectPriority


class Defect(Base):
    """Defect domain entity maintaining defect lifecycle, evidence, and concurrency tokens."""
    __tablename__ = "defects"

    id = Column(String(20), primary_key=True, index=True)
    title = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    steps_to_reproduce = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=False)
    actual_result = Column(Text, nullable=False)
    environment = Column(String(255), nullable=False)
    module = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default=DefectSeverity.MAJOR.value)
    priority = Column(String(20), nullable=False, default=DefectPriority.P3.value)
    status = Column(String(30), nullable=False, default=DefectStatus.OPEN.value, index=True)

    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Resolution Information (Mandatory for 'Fixed')
    root_cause = Column(Text, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    fix_reference = Column(String(255), nullable=True)

    # Verification & Reopen Information
    verification_notes = Column(Text, nullable=True)
    reopen_reason = Column(Text, nullable=True)
    reopen_count = Column(Integer, default=0, nullable=False)

    # Concurrency & Timestamps
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    reporter = relationship("User", foreign_keys=[reporter_id], backref="reported_defects")
    assignee = relationship("User", foreign_keys=[assignee_id], backref="assigned_defects")
    history_entries = relationship(
        "DefectHistory",
        back_populates="defect",
        cascade="all, delete-orphan",
        order_by="DefectHistory.timestamp.asc()",
    )

    __mapper_args__ = {
        "version_id_col": version
    }

    def __repr__(self):
        return f"<Defect id='{self.id}' title='{self.title[:30]}' status='{self.status}' version={self.version}>"
