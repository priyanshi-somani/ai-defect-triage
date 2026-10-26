"""Authentication and Role-Based Access Control (RBAC) dependencies."""

import logging
from typing import List, Callable, Union
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User
from backend.models.enums import UserRole
from backend.security import decode_access_token

logger = logging.getLogger("security.audit")

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    auto_error=False
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Validate bearer token and resolve current authenticated user.
    
    Raises:
        HTTPException(401): If token is missing, invalid, expired, or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )

    return user


def require_roles(allowed_roles: List[Union[str, UserRole]]) -> Callable:
    """Dependency factory enforcing RBAC permission boundaries.
    
    Args:
        allowed_roles: List of acceptable UserRole enums or string identifiers.
        
    Returns:
        Dependency verifying that the current user possesses an authorized role.
        Raises HTTP 403 Forbidden with security logging if role is unauthorized.
    """
    normalized_roles = [
        role.value if isinstance(role, UserRole) else str(role)
        for role in allowed_roles
    ]

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in normalized_roles:
            logger.warning(
                "SECURITY_VIOLATION: User '%s' (role: %s) denied access. Required one of: %s",
                current_user.username,
                current_user.role,
                normalized_roles
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role: {current_user.role}"
            )
        return current_user

    return role_checker
