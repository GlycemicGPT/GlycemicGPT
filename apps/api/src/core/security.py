"""Story 2.1 & 2.2: Security utilities.

Password hashing, verification, and JWT token management.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from src.config import settings

# Password validation regex
# At least 8 characters, one uppercase, one lowercase, one digit
PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    Args:
        plain_password: The plain text password to verify
        hashed_password: The bcrypt hash to verify against

    Returns:
        True if password matches, False otherwise
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The plain text password to hash

    Returns:
        The bcrypt hash of the password
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """Validate password meets strength requirements.

    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit

    Args:
        password: The password to validate

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"

    return True, None


# ============================================================================
# Story 2.2: JWT Token Management
# ============================================================================


def create_access_token(
    user_id: uuid.UUID,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role (diabetic, caregiver, admin)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.session_expire_hours)

    expire = datetime.now(UTC) + expires_delta

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token.

    Args:
        token: The JWT token string to decode

    Returns:
        Token payload dict if valid, None if invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        # Verify it's an access token
        if payload.get("type") != "access":
            return None

        return payload

    except JWTError:
        return None


def create_refresh_token(
    user_id: uuid.UUID,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token (longer-lived, for mobile token renewal).

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT refresh token string
    """
    if expires_delta is None:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)

    expire = datetime.now(UTC) + expires_delta

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_refresh_token(token: str) -> dict | None:
    """Decode and validate a JWT refresh token.

    Args:
        token: The JWT token string to decode

    Returns:
        Token payload dict if valid, None if invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != "refresh":
            return None

        return payload

    except JWTError:
        return None


class TokenData:
    """Parsed token data for type safety."""

    def __init__(self, payload: dict):
        self.user_id: uuid.UUID = uuid.UUID(payload["sub"])
        self.email: str = payload["email"]
        self.role: str = payload["role"]
        self.exp: datetime = datetime.fromtimestamp(payload["exp"], tz=UTC)
        self.jti: str | None = payload.get("jti")
