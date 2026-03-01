"""Story 28.7: API key management service."""

import hashlib
import hmac as _hmac
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.scopes import VALID_SCOPES
from src.logging_config import get_logger
from src.models.api_key import ApiKey
from src.models.user import User

logger = get_logger(__name__)

_KEY_PREFIX = "ggpt_"
_MAX_KEYS_PER_USER = 20


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    scopes: list[str],
    build_type: str = "release",
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Create a new API key for a user.

    Returns:
        Tuple of (ApiKey model, raw_key). The raw key is only available at
        creation time and must be shown to the user immediately.

    Raises:
        ValueError: If scopes are invalid or user has too many keys.
    """
    invalid = set(scopes) - VALID_SCOPES
    if invalid:
        raise ValueError(f"Invalid scopes: {', '.join(sorted(invalid))}")
    if not scopes:
        raise ValueError("At least one scope is required")

    # Enforce per-user limit (only count active keys)
    count_result = await db.execute(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.is_active.is_(True))
    )
    if count_result.scalar_one() >= _MAX_KEYS_PER_USER:
        raise ValueError(f"Maximum of {_MAX_KEYS_PER_USER} API keys per user reached")

    max_prefix_retries = 3
    for attempt in range(max_prefix_retries):
        raw_key = _KEY_PREFIX + secrets.token_urlsafe(32)
        prefix = raw_key[:12]
        key_hash = _hash_key(raw_key)

        api_key = ApiKey(
            user_id=user_id,
            name=name,
            prefix=prefix,
            key_hash=key_hash,
            scopes=",".join(sorted(scopes)),
            build_type=build_type,
            expires_at=expires_at,
        )
        db.add(api_key)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            if attempt == max_prefix_retries - 1:
                raise
            continue
        await db.refresh(api_key)
        break

    logger.info(
        "API key created",
        user_id=str(user_id),
        key_prefix=prefix,
        scopes=scopes,
    )
    return api_key, raw_key


async def validate_api_key(
    db: AsyncSession,
    raw_key: str,
) -> tuple[ApiKey, User] | None:
    """Validate a raw API key and return the key + owning user.

    Returns None if the key is invalid, inactive, or expired.
    """
    if not raw_key.startswith(_KEY_PREFIX):
        return None

    prefix = raw_key[:12]
    result = await db.execute(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None

    if not _hmac.compare_digest(_hash_key(raw_key), api_key.key_hash):
        return None

    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        return None

    # Fetch owning user
    user_result = await db.execute(
        select(User).where(User.id == api_key.user_id, User.is_active.is_(True))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return None

    # Touch last_used_at
    api_key.last_used_at = datetime.now(UTC)
    await db.flush()

    return api_key, user


async def revoke_api_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Revoke (deactivate) an API key owned by the given user.

    Returns True if the key was found and revoked, False otherwise.
    """
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return False

    api_key.is_active = False
    await db.flush()

    logger.info(
        "API key revoked",
        user_id=str(user_id),
        key_prefix=api_key.prefix,
    )
    return True


async def list_api_keys(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[ApiKey]:
    """List all API keys for a user (never includes hash or raw key)."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())
