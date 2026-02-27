"""Story 2.1, 2.2 & 2.3: Authentication router.

API endpoints for user registration, login, logout, and authentication.
"""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.auth import CurrentUser
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from src.core.token_blacklist import (
    blacklist_token,
    consume_token_once,
)
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.models.user import User, UserRole
from src.schemas.auth import (
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MobileLoginResponse,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    UserRegistrationRequest,
    UserRegistrationResponse,
    UserResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


async def _blacklist_current_token(request: Request) -> None:
    """Extract and blacklist the JWT from the current request.

    Best-effort: silently does nothing if the token cannot be extracted.
    """
    token = None
    cookie_val = request.cookies.get(settings.jwt_cookie_name)
    if cookie_val:
        token = cookie_val
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        return

    payload = decode_access_token(token)
    if not payload:
        return

    jti = payload.get("jti")
    if not jti:
        return

    # TTL = remaining token lifetime (seconds)
    exp = payload.get("exp", 0)
    remaining = int(exp - datetime.now(UTC).timestamp())
    if remaining > 0:
        await blacklist_token(jti, remaining)


@router.post(
    "/register",
    response_model=UserRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "User registered successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        409: {"model": ErrorResponse, "description": "Email already exists"},
    },
)
async def register_user(
    request: UserRegistrationRequest,
    db: AsyncSession = Depends(get_db),
) -> UserRegistrationResponse:
    """Register a new user account.

    Creates a new user with the provided email and password.
    Password is hashed using bcrypt before storage.
    New users are assigned the 'diabetic' role by default.

    Args:
        request: Registration request with email and password
        db: Database session

    Returns:
        UserRegistrationResponse with user details and success message

    Raises:
        HTTPException 409: If email already exists
        HTTPException 400: If password doesn't meet requirements
    """
    # Check if email already exists (Story 28.10: use generic message to prevent email enumeration)
    existing_user = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    if existing_user.scalar_one_or_none():
        logger.warning(
            "Registration attempt with existing email",
            email=request.email,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed. Please try again or contact support.",
        )

    # Create new user
    user = User(
        email=request.email.lower(),
        hashed_password=hash_password(request.password),
        role=UserRole.DIABETIC,
        is_active=True,
        email_verified=False,
        disclaimer_acknowledged=False,
    )

    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(
            "User registered successfully",
            user_id=str(user.id),
            email=user.email,
        )

        return UserRegistrationResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            message="Registration successful",
            disclaimer_required=not user.disclaimer_acknowledged,
        )

    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Registration failed - integrity error",
            email=request.email,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed. Please try again or contact support.",
        )


# ============================================================================
# Story 2.2: Login Endpoint
# ============================================================================


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        200: {"description": "Login successful"},
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
    },
)
@limiter.limit("10/minute")
async def login(
    body: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate a user and create a session.

    Validates credentials and returns a JWT token in an httpOnly cookie.
    The token expires after the configured session duration (default 24 hours).
    """
    # Get client IP for logging
    client_ip = request.client.host if request.client else "unknown"

    # Find user by email (case-insensitive)
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    # Check if user exists and password is correct
    if not user or not verify_password(body.password, user.hashed_password):
        logger.warning(
            "Failed login attempt",
            email=body.email,
            client_ip=client_ip,
            reason="invalid_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(
            "Failed login attempt",
            email=body.email,
            client_ip=client_ip,
            reason="account_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Create JWT token
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    # Set httpOnly cookie with the token
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_expire_hours * 3600,
        path="/",
    )

    # Update last login timestamp
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "User logged in successfully",
        user_id=str(user.id),
        email=user.email,
        client_ip=client_ip,
    )

    return LoginResponse(
        message="Login successful",
        user=UserResponse.model_validate(user),
        disclaimer_required=not user.disclaimer_acknowledged,
    )


@router.post(
    "/mobile/login",
    response_model=MobileLoginResponse,
    responses={
        200: {"description": "Mobile login successful"},
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
    },
)
@limiter.limit("10/minute")
async def mobile_login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MobileLoginResponse:
    """Authenticate a mobile client and return a JWT in the response body.

    Identical logic to the web login, but returns the token directly
    instead of setting an httpOnly cookie.
    """
    client_ip = request.client.host if request.client else "unknown"

    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        logger.warning(
            "Failed mobile login attempt",
            email=body.email,
            client_ip=client_ip,
            reason="invalid_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        logger.warning(
            "Failed mobile login attempt",
            email=body.email,
            client_ip=client_ip,
            reason="account_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_refresh_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "Mobile user logged in",
        user_id=str(user.id),
        email=user.email,
        client_ip=client_ip,
    )

    return MobileLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/mobile/refresh",
    response_model=MobileLoginResponse,
    responses={
        200: {"description": "Tokens refreshed successfully"},
        401: {
            "model": ErrorResponse,
            "description": "Invalid or expired refresh token",
        },
    },
)
@limiter.limit("30/minute")
async def mobile_refresh(
    body: RefreshTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MobileLoginResponse:
    """Exchange a valid refresh token for new access + refresh tokens.

    Implements token rotation: each refresh invalidates the old refresh token
    by issuing a new one.
    """
    client_ip = request.client.host if request.client else "unknown"

    payload = decode_refresh_token(body.refresh_token)
    if payload is None:
        logger.warning(
            "Invalid refresh token attempt",
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Atomically consume the refresh token (Story 28.3 -- prevents replay races)
    old_jti = payload.get("jti")
    if old_jti:
        old_exp = payload.get("exp", 0)
        remaining = int(old_exp - datetime.now(UTC).timestamp())
        consumed = await consume_token_once(old_jti, max(1, remaining))
        if not consumed:
            logger.warning(
                "Replayed refresh token used",
                client_ip=client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

    # Look up the user to ensure they still exist and are active
    user_id = uuid_mod.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        logger.warning(
            "Refresh token for invalid/inactive user",
            user_id=payload["sub"],
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Note: old refresh token already consumed atomically above via consume_token_once

    # Issue new token pair (rotation)
    new_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    new_refresh_token = create_refresh_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    logger.info(
        "Mobile token refreshed",
        user_id=str(user.id),
        client_ip=client_ip,
    )

    return MobileLoginResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "Current user details"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_current_user_profile(
    current_user: CurrentUser,
) -> UserResponse:
    """Get the current authenticated user's profile.

    Requires a valid session cookie. Returns the user's profile information.

    Args:
        current_user: The authenticated user from the session cookie

    Returns:
        UserResponse with the current user's details
    """
    return UserResponse.model_validate(current_user)


# ============================================================================
# Story 2.3: Logout Endpoint
# ============================================================================


@router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={
        200: {"description": "Logout successful"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser,
) -> LogoutResponse:
    """Log out the current user and terminate their session.

    Clears the session cookie and blacklists the token server-side.
    Requires a valid session to log out.

    Args:
        request: The HTTP request (to extract the token for blacklisting)
        response: FastAPI response object for clearing cookies
        current_user: The authenticated user (validates session is active)

    Returns:
        LogoutResponse with success message
    """
    # Blacklist the token server-side (Story 28.3)
    await _blacklist_current_token(request)

    # Clear the session cookie by setting it to expire immediately
    response.delete_cookie(
        key=settings.jwt_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )

    logger.info(
        "User logged out successfully",
        user_id=str(current_user.id),
        email=current_user.email,
    )

    return LogoutResponse(message="Logout successful")


# ============================================================================
# Story 10.2: Profile Update Endpoints
# ============================================================================


@router.patch(
    "/profile",
    response_model=UserResponse,
    responses={
        200: {"description": "Profile updated successfully"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update the current user's profile.

    Allows updating the display name.

    Args:
        request: Profile update fields
        current_user: The authenticated user
        db: Database session

    Returns:
        Updated UserResponse
    """
    if not request.model_fields_set:
        return UserResponse.model_validate(current_user)

    if "display_name" in request.model_fields_set:
        current_user.display_name = request.display_name

    await db.commit()
    await db.refresh(current_user)

    logger.info(
        "User profile updated",
        user_id=str(current_user.id),
    )

    return UserResponse.model_validate(current_user)


@router.post(
    "/change-password",
    response_model=LogoutResponse,
    responses={
        200: {"description": "Password changed successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def change_password(
    body: PasswordChangeRequest,
    http_request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    """Change the current user's password.

    Verifies the current password before allowing the change.
    Blacklists the current token so the user must re-authenticate.

    Args:
        body: Current and new password
        http_request: The HTTP request (for token blacklisting)
        current_user: The authenticated user
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException 400: If current password is incorrect
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(body.new_password)
    await db.commit()

    # Blacklist the current token to force re-authentication (Story 28.3)
    await _blacklist_current_token(http_request)

    logger.info(
        "User password changed",
        user_id=str(current_user.id),
    )

    return LogoutResponse(message="Password changed successfully")
