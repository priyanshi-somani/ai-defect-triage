"""DefectHistory SQLAlchemy ORM entity."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class DefectHistory(Base):
    """Immutable audit trail entry recording mutations to defect attributes."""
    __tablename__ = "defect_history"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    defect_id = Column(String(20), ForeignKey("defects.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)
    field_name = Column(String(50), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    version_snapshot = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    defect = relationship("Defect", back_populates="history_entries")
    changed_by = relationship("User", foreign_keys=[changed_by_user_id])

    def __repr__(self):
        return (
            f"<DefectHistory id={self.id} defect_id='{self.defect_id}' "
            f"action='{self.action_type}' field='{self.field_name}' "
            f"version={self.version_snapshot}>"
        )
