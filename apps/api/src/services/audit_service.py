"""Story 28.7: Security audit logging service."""

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.security_audit_log import SecurityAuditLog

logger = get_logger(__name__)


async def log_event(
    db: AsyncSession,
    event_type: str,
    user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Write a security audit log entry.

    Fire-and-forget: logs errors but never raises so callers are not disrupted.
    """
    try:
        detail_json = json.dumps(detail) if detail else None
        entry = SecurityAuditLog(
            event_type=event_type,
            user_id=user_id,
            detail=detail_json,
            ip_address=ip_address,
        )
        db.add(entry)
        await db.flush()
    except Exception:
        # Expunge the failed entry to prevent session corruption
        try:
            db.expunge(entry)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        logger.exception(
            "Failed to write audit log",
            event_type=event_type,
        )
