"""Authentication request and response schemas."""

from pydantic import BaseModel, Field
from backend.schemas.user import UserResponse


class UserLoginRequest(BaseModel):
    """Payload for user login."""
    username: str = Field(..., min_length=1, description="Username or email")
    password: str = Field(..., min_length=1, description="Account password")


class TokenResponse(BaseModel):
    """JWT bearer token response upon successful authentication."""
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserResponse
