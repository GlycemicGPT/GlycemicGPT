"""Authentication, authorization, and scope-checking dependencies.

Supports three auth paths:
1. httpOnly session cookie (web)
2. Authorization Bearer JWT (mobile)
3. X-API-Key header (third-party integrations)
"""

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.security import TokenData, decode_access_token
from src.core.token_blacklist import is_token_blacklisted
from src.database import get_db
from src.logging_config import get_logger
from src.models.user import User, UserRole

logger = get_logger(__name__)

# Key set on request.state when auth came via API key
_API_KEY_SCOPES_ATTR = "_api_key_scopes"


def is_api_key_auth(request: Request) -> bool:
    """Return True if the current request was authenticated via an API key."""
    return hasattr(request.state, _API_KEY_SCOPES_ATTR)


async def get_current_user(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=settings.jwt_cookie_name)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user.

    Auth paths (checked in order):
    1. httpOnly session cookie
    2. Authorization Bearer JWT
    3. X-API-Key header

    Returns:
        The authenticated User object

    Raises:
        HTTPException 401: If no valid credentials are found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # --- Path 1 & 2: Cookie / Bearer JWT ---
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header[7:]

    if session_token:
        payload = decode_access_token(session_token)
        if payload is None:
            raise credentials_exception

        try:
            token_data = TokenData(payload)
        except (KeyError, ValueError):
            raise credentials_exception

        if token_data.jti and await is_token_blacklisted(token_data.jti):
            raise credentials_exception

        result = await db.execute(select(User).where(User.id == token_data.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise credentials_exception
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is disabled",
            )
        return user

    # --- Path 3: X-API-Key header ---
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        from src.services.api_key_service import validate_api_key

        pair = await validate_api_key(db, api_key_header)
        if pair is None:
            from src.services.audit_service import log_event

            ip = request.client.host if request.client else None
            await log_event(
                db,
                event_type="api_key.auth_failed",
                detail={
                    "prefix": api_key_header[:12]
                    if len(api_key_header) >= 12
                    else "short"
                },
                ip_address=ip,
            )
            try:
                await db.commit()
            except Exception:
                logger.exception("Failed to commit audit log for failed API key auth")
            raise credentials_exception
        api_key_obj, user = pair
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is disabled",
            )
        # Stash scopes and build_type on request.state for downstream checks
        request.state._api_key_scopes = {
            s.strip() for s in api_key_obj.scopes.split(",") if s.strip()
        }
        request.state._api_key_build_type = api_key_obj.build_type
        return user

    raise credentials_exception


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current active user.

    This is a convenience dependency that ensures the user is active.
    It's an alias for get_current_user since that already checks is_active.

    Args:
        current_user: The authenticated user from get_current_user

    Returns:
        The authenticated User object
    """
    return current_user


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]


# ============================================================================
# Scope-based access control (API keys)
# ============================================================================


class ScopeChecker:
    """Dependency that enforces required scopes for API-key-authenticated requests.

    JWT/cookie requests are treated as first-party and granted all scopes.
    API-key requests must have every required scope in their key's scope list.

    Usage:
        @router.get("/glucose")
        async def get_glucose(
            user: CurrentUser,
            _: bool = Depends(ScopeChecker(["read:glucose"])),
        ):
            ...
    """

    def __init__(self, required_scopes: list[str]):
        self.required_scopes = set(required_scopes)

    async def __call__(self, request: Request, _user: CurrentUser) -> bool:
        key_scopes: set[str] | None = getattr(request.state, _API_KEY_SCOPES_ATTR, None)
        # First-party auth (JWT/cookie) -- all scopes granted
        if key_scopes is None:
            return True

        missing = self.required_scopes - key_scopes
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(sorted(missing))}",
            )
        return True


# ============================================================================
# Role-Based Access Control
# ============================================================================


class RoleChecker:
    """Dependency class for checking user roles.

    This class creates a callable dependency that verifies the current user
    has one of the allowed roles. If not, it raises a 403 Forbidden exception.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: CurrentUser, _: bool = Depends(RoleChecker([UserRole.ADMIN]))):
            ...

        # Or use the convenience dependencies below
        @router.get("/admin-only")
        async def admin_endpoint(user: AdminUser):
            ...
    """

    def __init__(self, allowed_roles: list[UserRole]):
        """Initialize the role checker.

        Args:
            allowed_roles: List of roles that are allowed to access the endpoint
        """
        self.allowed_roles = allowed_roles

    async def __call__(
        self,
        request: Request,
        current_user: CurrentUser,
    ) -> bool:
        """Check if the current user has one of the allowed roles.

        Args:
            request: The HTTP request (for logging)
            current_user: The authenticated user

        Returns:
            True if the user has an allowed role

        Raises:
            HTTPException 403: If the user doesn't have an allowed role
        """
        if current_user.role not in self.allowed_roles:
            # Log the unauthorized access attempt
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(
                "Unauthorized access attempt",
                user_id=str(current_user.id),
                email=current_user.email,
                user_role=current_user.role.value,
                required_roles=[r.value for r in self.allowed_roles],
                path=request.url.path,
                method=request.method,
                client_ip=client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this resource",
            )
        return True


def require_roles(*roles: UserRole) -> RoleChecker:
    """Create a role checker dependency for the specified roles.

    This is a convenience function for creating RoleChecker instances.

    Args:
        *roles: One or more UserRole values that are allowed

    Returns:
        A RoleChecker instance configured with the specified roles

    Usage:
        @router.get("/settings")
        async def get_settings(
            user: CurrentUser,
            _: bool = Depends(require_roles(UserRole.DIABETIC, UserRole.ADMIN))
        ):
            ...
    """
    return RoleChecker(list(roles))


# Pre-configured role checkers for common use cases
require_admin = require_roles(UserRole.ADMIN)
require_diabetic = require_roles(UserRole.DIABETIC)
require_caregiver = require_roles(UserRole.CAREGIVER)
require_diabetic_or_admin = require_roles(UserRole.DIABETIC, UserRole.ADMIN)
require_any_role = require_roles(UserRole.DIABETIC, UserRole.CAREGIVER, UserRole.ADMIN)


# Convenience type aliases for role-restricted endpoints
async def get_admin_user(
    current_user: CurrentUser,
    request: Request,
) -> User:
    """Get the current user and verify they are an admin.

    Args:
        current_user: The authenticated user
        request: The HTTP request (for logging)

    Returns:
        The authenticated admin user

    Raises:
        HTTPException 403: If the user is not an admin
    """
    await require_admin(request, current_user)
    return current_user


async def get_diabetic_user(
    current_user: CurrentUser,
    request: Request,
) -> User:
    """Get the current user and verify they are a diabetic.

    Args:
        current_user: The authenticated user
        request: The HTTP request (for logging)

    Returns:
        The authenticated diabetic user

    Raises:
        HTTPException 403: If the user is not a diabetic
    """
    await require_diabetic(request, current_user)
    return current_user


async def get_diabetic_or_admin_user(
    current_user: CurrentUser,
    request: Request,
) -> User:
    """Get the current user and verify they are a diabetic or admin.

    Args:
        current_user: The authenticated user
        request: The HTTP request (for logging)

    Returns:
        The authenticated user (diabetic or admin)

    Raises:
        HTTPException 403: If the user is not a diabetic or admin
    """
    await require_diabetic_or_admin(request, current_user)
    return current_user


# Type aliases for role-restricted users
AdminUser = Annotated[User, Depends(get_admin_user)]
DiabeticUser = Annotated[User, Depends(get_diabetic_user)]
DiabeticOrAdminUser = Annotated[User, Depends(get_diabetic_or_admin_user)]
