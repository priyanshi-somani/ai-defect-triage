"""Authentication and user management service layer."""

from datetime import timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.config import settings
from backend.models.user import User
from backend.schemas.user import UserRegisterRequest, UserResponse
from backend.schemas.auth import UserLoginRequest, TokenResponse
from backend.security import hash_password, verify_password, create_access_token


class AuthService:
    """Service handling user registration, authentication, and token issuance."""

    @staticmethod
    def register_user(db: Session, request: UserRegisterRequest) -> User:
        """Register a new user with salted BCrypt password hash.
        
        Raises:
            HTTPException(409): If username or email is already registered.
        """
        # Check uniqueness of username and email
        existing_user = db.query(User).filter(
            or_(User.username == request.username, User.email == request.email)
        ).first()

        if existing_user:
            if existing_user.username == request.username:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Username '{request.username}' is already taken."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Email '{request.email}' is already registered."
                )

        new_user = User(
            username=request.username,
            email=request.email,
            password_hash=hash_password(request.password),
            role=request.role.value,
            is_active=True
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    @staticmethod
    def authenticate_user(db: Session, request: UserLoginRequest) -> TokenResponse:
        """Authenticate user credentials and issue signed JWT access token.
        
        Raises:
            HTTPException(401): If credentials are invalid or user inactive.
        """
        # Allow login via username or email
        user = db.query(User).filter(
            or_(User.username == request.username, User.email == request.username)
        ).first()

        if not user or not verify_password(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive."
            )

        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username, "role": user.role, "user_id": user.id},
            expires_delta=expires_delta
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in_seconds=int(expires_delta.total_seconds()),
            user=UserResponse.model_validate(user)
        )
