"""SentinelAI Auth Service.

Handles user authentication, JWT token management, API keys,
and role-based access control.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
)
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, SecretStr

from sentinelai.config import settings
from sentinelai.database import db_manager
from sentinelai.logging import get_logger, setup_logging
from sentinelai.metrics import metrics
from sentinelai.models import (
    APIKey,
    RefreshToken,
    User,
    UserRole,
    generate_uuid,
)
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)

# Initialize
setup_logging("auth-service")
init_tracing("auth-service")

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
security = HTTPBearer(auto_error=False)

# Router
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


# =============================================================================
# Password Utilities
# =============================================================================


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# =============================================================================
# JWT Token Management
# =============================================================================


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    """Get current authenticated user from token."""
    if not credentials and not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_value = credentials.credentials if credentials else token
    payload = decode_token(token_value)

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Get user from database
    async with db_manager.session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    return current_user


def require_role(allowed_roles: list[UserRole]):
    """Dependency to check user role."""
    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return role_checker


# =============================================================================
# Request/Response Models
# =============================================================================


class UserCreate(BaseModel):
    """User creation request."""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    full_name: str | None = None
    role: UserRole = UserRole.VIEWER


class UserResponse(BaseModel):
    """User response."""
    id: str
    email: str
    username: str
    full_name: str | None
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefreshRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str


class PasswordResetRequest(BaseModel):
    """Password reset request."""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation."""
    token: str
    new_password: str = Field(..., min_length=8)


class APIKeyCreate(BaseModel):
    """API key creation request."""
    name: str = Field(..., min_length=1, max_length=100)
    expires_at: datetime | None = None


class APIKeyResponse(BaseModel):
    """API key response."""
    id: str
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class APIKeyCreateResponse(BaseModel):
    """API key creation response with the actual key."""
    id: str
    name: str
    key: str  # Only returned once
    prefix: str
    created_at: datetime
    expires_at: datetime | None


# =============================================================================
# Authentication Endpoints
# =============================================================================


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@traced
async def register(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
):
    """Register a new user account."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        # Check if email already exists
        result = await session.execute(
            select(User).where(User.email == user_data.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Check if username already exists
        result = await session.execute(
            select(User).where(User.username == user_data.username)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Create user
        user = User(
            id=generate_uuid(),
            email=user_data.email,
            username=user_data.username,
            hashed_password=hash_password(user_data.password),
            full_name=user_data.full_name,
            role=user_data.role,
            is_active=True,
            is_verified=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # TODO: Send verification email in background
        # background_tasks.add_task(send_verification_email, user)

        metrics.requests_total.labels(
            method="POST",
            endpoint="/auth/register",
            status="success",
        ).inc()

        return user


@router.post("/login", response_model=TokenResponse)
@traced
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Authenticate user and return JWT tokens."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        # Find user by username
        result = await session.execute(
            select(User).where(User.username == form_data.username)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(form_data.password, user.hashed_password):
            metrics.requests_total.labels(
                method="POST",
                endpoint="/auth/login",
                status="error",
            ).inc()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

        # Update last login
        user.last_login = datetime.now(timezone.utc)
        await session.commit()

        # Create tokens
        token_data = {"sub": user.id, "username": user.username}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Store refresh token
        refresh_token_obj = RefreshToken(
            id=generate_uuid(),
            token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.jwt_refresh_token_expire_days
            ),
            user_id=user.id,
        )
        session.add(refresh_token_obj)
        await session.commit()

        metrics.requests_total.labels(
            method="POST",
            endpoint="/auth/login",
            status="success",
        ).inc()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )


@router.post("/refresh", response_model=TokenResponse)
@traced
async def refresh_token(
    request: TokenRefreshRequest,
):
    """Refresh access token using refresh token."""
    # Decode refresh token
    payload = decode_token(request.refresh_token)
    token_type = payload.get("type")

    if token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload.get("sub")

    # Verify refresh token exists in database
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.token == request.refresh_token,
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked == False,
                )
            )
        )
        stored_token = result.scalar_one_or_none()

        if not stored_token or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        # Get user
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
            )

        # Revoke old refresh token
        stored_token.is_revoked = True

        # Create new tokens
        token_data = {"sub": user.id, "username": user.username}
        access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        # Store new refresh token
        new_refresh_token_obj = RefreshToken(
            id=generate_uuid(),
            token=new_refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.jwt_refresh_token_expire_days
            ),
            user_id=user.id,
        )
        session.add(new_refresh_token_obj)
        await session.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )


@router.post("/logout")
@traced
async def logout(
    current_user: User = Depends(get_current_active_user),
    authorization: str = Header(None),
):
    """Logout user and revoke refresh token."""
    # Extract token from Authorization header
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

        async with db_manager.session() as session:
            from sqlalchemy import update

            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.token == token)
                .values(is_revoked=True)
            )
            await session.commit()

    return {"message": "Successfully logged out"}


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
@traced
async def request_password_reset(
    request: PasswordResetRequest,
    background_tasks: BackgroundTasks,
):
    """Request password reset email."""
    # TODO: Implement password reset
    # 1. Find user by email
    # 2. Generate reset token
    # 3. Send reset email

    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/password-reset/confirm")
@traced
async def confirm_password_reset(
    request: PasswordResetConfirm,
):
    """Confirm password reset with token."""
    # TODO: Implement password reset confirmation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset not implemented",
    )


# =============================================================================
# User Endpoints
# =============================================================================


@router.get("/me", response_model=UserResponse)
@traced
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Get current user information."""
    return current_user


@router.patch("/me", response_model=UserResponse)
@traced
async def update_current_user(
    full_name: str | None = Body(None),
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Update current user information."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.id == current_user.id)
        )
        user = result.scalar_one()

        if full_name is not None:
            user.full_name = full_name

        await session.commit()
        await session.refresh(user)
        return user


@router.post("/me/password")
@traced
async def change_password(
    current_password: str = Body(...),
    new_password: str = Body(..., min_length=8),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Change current user's password."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.id == current_user.id)
        )
        user = result.scalar_one()

        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        user.hashed_password = hash_password(new_password)
        await session.commit()

    return {"message": "Password changed successfully"}


# =============================================================================
# API Key Endpoints
# =============================================================================


@router.post("/api-keys", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
@traced
async def create_api_key(
    api_key_data: APIKeyCreate,
    current_user: User = Depends(get_current_active_user),
) -> APIKeyCreateResponse:
    """Create a new API key."""
    # Generate API key
    key = f"sk_{secrets.token_urlsafe(32)}"
    prefix = key[:8]
    key_hash = hash_password(key)

    async with db_manager.session() as session:
        api_key = APIKey(
            id=generate_uuid(),
            name=api_key_data.name,
            key_hash=key_hash,
            prefix=prefix,
            expires_at=api_key_data.expires_at,
            user_id=current_user.id,
        )
        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=key,  # Only returned once
        prefix=api_key.prefix,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("/api-keys", response_model=list[APIKeyResponse])
@traced
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
) -> list[APIKeyResponse]:
    """List all API keys for current user."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(APIKey)
            .where(APIKey.user_id == current_user.id)
            .order_by(APIKey.created_at.desc())
        )
        return list(result.scalars().all())


@router.delete("/api-keys/{key_id}")
@traced
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Delete an API key."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, delete, select

        result = await session.execute(
            select(APIKey).where(
                and_(
                    APIKey.id == key_id,
                    APIKey.user_id == current_user.id,
                )
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        await session.execute(
            delete(APIKey).where(APIKey.id == key_id)
        )
        await session.commit()

    return {"message": "API key deleted successfully"}


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Auth Service",
        description="Authentication and authorization service",
        version=settings.app_version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sentinelai.auth_service.main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.app_debug,
    )
