"""Story 2.2 & 2.4: Authentication and authorization dependencies.

FastAPI dependencies for extracting and validating user authentication,
and role-based access control.
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


async def get_current_user(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=settings.jwt_cookie_name)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from a session cookie or Bearer token.

    Checks the httpOnly cookie first, then falls back to an Authorization
    Bearer header (used by mobile clients).

    Args:
        request: The HTTP request (for reading Authorization header)
        session_token: JWT token from the session cookie
        db: Database session

    Returns:
        The authenticated User object

    Raises:
        HTTPException 401: If no token, invalid token, or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header[7:]
        if not session_token:
            raise credentials_exception

    # Decode and validate the token
    payload = decode_access_token(session_token)
    if payload is None:
        raise credentials_exception

    # Extract user ID from token
    try:
        token_data = TokenData(payload)
    except (KeyError, ValueError):
        raise credentials_exception

    # Check token blacklist (Story 28.3)
    if token_data.jti and await is_token_blacklisted(token_data.jti):
        raise credentials_exception

    # Fetch the user from the database
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
# Story 2.4: Role-Based Access Control
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
