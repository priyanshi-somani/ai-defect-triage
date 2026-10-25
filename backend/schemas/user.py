"""User Pydantic validation schemas."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from backend.models.enums import UserRole


class UserRegisterRequest(BaseModel):
    """Payload for registering a new user."""
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_.-]+$",
        description="Alphanumeric username (3-50 characters)"
    )
    email: EmailStr = Field(..., description="Valid contact email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="Password must contain at least 8 characters"
    )
    role: UserRole = Field(default=UserRole.REPORTER, description="Assigned system role")


class UserResponse(BaseModel):
    """Public user profile response."""
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
