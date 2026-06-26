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
from src.core.disclaimer import has_acknowledged_current
from src.core.security import (
    _DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from src.core.token_blacklist import (
    TokenConsumeUnavailableError,
    blacklist_token,
    consume_token_once,
)
from src.core.units import GlucoseUnitSource
from src.database import get_db
from src.deployment_check import request_is_insecure_http
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
from src.services.glucose_unit_seed import glucose_unit_for_locale

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


async def _blacklist_current_token(request: Request) -> None:
    """Extract and blacklist the JWT from the current request.

    Best-effort: a token that cannot be revoked here stays valid until
    expiry, so failures are logged at WARNING rather than swallowed.
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

    client_ip = request.client.host if request.client else "unknown"

    payload = decode_access_token(token)
    if not payload:
        logger.warning(
            "Logout: presented token could not be decoded for revocation",
            client_ip=client_ip,
        )
        return

    jti = payload.get("jti")
    if not jti:
        logger.warning(
            "Logout: token has no jti and stays valid until expiry",
            client_ip=client_ip,
        )
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
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserRegistrationResponse:
    """Register a new user account.

    Creates a new user with the provided email and password.
    Password is hashed using bcrypt before storage.
    New users are assigned the 'diabetic' role by default.

    Seeds an overridable glucose display unit from the request's
    ``Accept-Language`` region: an mmol-region locale starts the
    account in mmol/L, everything else in mg/dL (today's default). The seed is
    a display-preference-only best guess marked ``source=seed`` so the manual
    toggle always wins and a one-time notice can offer a correction; canonical
    storage is untouched.

    Args:
        request: Registration request with email and password
        http_request: The HTTP request (for the ``Accept-Language`` locale seed)
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

    # Smart-default the glucose display unit from the request locale. This is a
    # best guess, not a detector -- marked ``source=seed`` so the manual toggle
    # always overrides it and the one-time notice can offer a correction.
    seeded_unit = glucose_unit_for_locale(http_request.headers.get("Accept-Language"))

    # Create new user
    user = User(
        email=request.email.lower(),
        hashed_password=hash_password(request.password),
        role=UserRole.DIABETIC,
        is_active=True,
        email_verified=False,
        disclaimer_acknowledged=False,
        glucose_unit=seeded_unit,
        glucose_unit_source=GlucoseUnitSource.SEED,
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
            disclaimer_required=not has_acknowledged_current(user),
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

    # Constant-time credential check: always run bcrypt even for non-existing
    # users to prevent timing-based user enumeration (CWE-208).
    if not user:
        verify_password(body.password, _DUMMY_HASH)
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
    if not verify_password(body.password, user.hashed_password):
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

    # Loud signal when the browser will silently drop the Secure cookie.
    if (
        settings.cookie_secure
        and not settings.testing
        and request_is_insecure_http(request)
    ):
        logger.warning(
            "Login over plain HTTP with COOKIE_SECURE=true — the browser "
            "will drop the session cookie. Symptom: spinner on Sign In, "
            "/dashboard bounces back to /login. Either serve GlycemicGPT "
            "over HTTPS, or set COOKIE_SECURE=false (development only). "
            "See docs/install/docker.md.",
            request_host=request.url.hostname,
            request_scheme=request.url.scheme,
        )

    logger.info(
        "User logged in successfully",
        user_id=str(user.id),
        email=user.email,
        client_ip=client_ip,
    )

    return LoginResponse(
        message="Login successful",
        user=UserResponse.model_validate(user),
        disclaimer_required=not has_acknowledged_current(user),
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

    # Constant-time credential check (same pattern as web login)
    if not user:
        verify_password(body.password, _DUMMY_HASH)
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
    if not verify_password(body.password, user.hashed_password):
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
        503: {
            "model": ErrorResponse,
            "description": (
                "Token service temporarily unavailable; the refresh token "
                "was not consumed and the client should retry"
            ),
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

    # Atomically consume the refresh token (Story 28.3 -- prevents replay races).
    # A token without a jti cannot be consumed, so it would be infinitely
    # replayable -- reject it outright.
    old_jti = payload.get("jti")
    if not old_jti:
        logger.warning(
            "Refresh token without jti rejected",
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    old_exp = payload.get("exp", 0)
    remaining = int(old_exp - datetime.now(UTC).timestamp())
    # Fail-closed: a Redis outage denies the refresh rather than letting the
    # same token mint unlimited new pairs. The outage maps to 503 (not 401)
    # because mobile clients treat a refresh 401 as revocation and delete
    # their stored token; on 5xx they keep it and retry -- the token was NOT
    # consumed and stays valid.
    try:
        consumed = await consume_token_once(old_jti, max(1, remaining))
    except TokenConsumeUnavailableError:
        logger.warning(
            "Refresh denied: token service unavailable (fail-closed)",
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token service temporarily unavailable. Please retry.",
        ) from None
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
