"""Authentication and Authorization REST Endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.models.enums import UserRole
from backend.schemas.user import UserRegisterRequest, UserResponse
from backend.schemas.auth import UserLoginRequest, TokenResponse
from backend.services.auth_service import AuthService
from backend.auth_deps import get_current_user, require_roles

router = APIRouter(prefix="/auth", tags=["Authentication & RBAC"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user"
)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account with salted BCrypt password hash."""
    user = AuthService.register_user(db, request)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive JWT token"
)
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """Validate user credentials and return signed JWT bearer token."""
    return AuthService.authenticate_user(db, request)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile"
)
def get_me(current_user: User = Depends(get_current_user)):
    """Retrieve profile and assigned role of current authenticated user."""
    return UserResponse.model_validate(current_user)


@router.get(
    "/admin-only",
    summary="Verify ADMIN authorization boundary"
)
def admin_only_check(current_user: User = Depends(require_roles([UserRole.ADMIN]))):
    """Restricted endpoint for testing and verifying ROLE_ADMIN RBAC policy."""
    return {
        "message": "Authorized as administrator",
        "user": current_user.username,
        "role": current_user.role
    }


@router.get(
    "/triage-only",
    summary="Verify QA_TRIAGE authorization boundary"
)
def triage_only_check(
    current_user: User = Depends(require_roles([UserRole.QA_TRIAGE, UserRole.ADMIN]))
):
    """Restricted endpoint for testing and verifying QA / Triage RBAC policy."""
    return {
        "message": "Authorized for defect triage operations",
        "user": current_user.username,
        "role": current_user.role
    }
