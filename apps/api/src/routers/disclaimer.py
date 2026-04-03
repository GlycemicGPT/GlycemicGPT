"""Disclaimer acknowledgment endpoints.

Story 1.3: First-Run Safety Disclaimer
FR50: System can display experimental software disclaimer on first use
FR51: User must acknowledge disclaimer before using system
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser
from src.database import get_db, get_session_maker
from src.models.disclaimer import DisclaimerAcknowledgment
from src.schemas.disclaimer import (
    DisclaimerAcknowledgeRequest,
    DisclaimerAcknowledgeResponse,
    DisclaimerStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/disclaimer", tags=["Disclaimer"])

# Current disclaimer version - increment when disclaimer text changes
DISCLAIMER_VERSION = "1.0"


@router.get("/status", response_model=DisclaimerStatusResponse)
async def get_disclaimer_status(session_id: str) -> DisclaimerStatusResponse:
    """Check if the disclaimer has been acknowledged for a session.

    Args:
        session_id: Unique session identifier (UUID from localStorage)

    Returns:
        DisclaimerStatusResponse with acknowledgment status
    """
    async with get_session_maker()() as session:
        result = await session.execute(
            select(DisclaimerAcknowledgment).where(
                DisclaimerAcknowledgment.session_id == session_id
            )
        )
        acknowledgment = result.scalar_one_or_none()

        if acknowledgment:
            return DisclaimerStatusResponse(
                acknowledged=True,
                acknowledged_at=acknowledgment.acknowledged_at,
                disclaimer_version=acknowledgment.disclaimer_version,
            )

        return DisclaimerStatusResponse(
            acknowledged=False,
            acknowledged_at=None,
            disclaimer_version=DISCLAIMER_VERSION,
        )


@router.post("/acknowledge", response_model=DisclaimerAcknowledgeResponse)
async def acknowledge_disclaimer(
    request: Request,
    data: DisclaimerAcknowledgeRequest,
) -> DisclaimerAcknowledgeResponse:
    """Record acknowledgment of the safety disclaimer.

    Both checkboxes must be checked for acknowledgment to be valid.

    Args:
        request: FastAPI request object (for IP and user agent)
        data: Acknowledgment request with session_id and checkbox states

    Returns:
        DisclaimerAcknowledgeResponse with success status

    Raises:
        HTTPException: If checkboxes are not both checked
    """
    # Validate both checkboxes are checked
    if not data.checkbox_experimental or not data.checkbox_not_medical_advice:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both acknowledgment checkboxes must be checked",
        )

    # Get client info for audit purposes
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]

    async with get_session_maker()() as session:
        # Check if already acknowledged
        result = await session.execute(
            select(DisclaimerAcknowledgment).where(
                DisclaimerAcknowledgment.session_id == data.session_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(
                "Disclaimer already acknowledged",
                extra={
                    "session_id": data.session_id,
                    "acknowledged_at": existing.acknowledged_at.isoformat(),
                },
            )
            return DisclaimerAcknowledgeResponse(
                success=True,
                acknowledged_at=existing.acknowledged_at,
                message="Disclaimer was previously acknowledged",
            )

        # Create new acknowledgment
        acknowledgment = DisclaimerAcknowledgment(
            session_id=data.session_id,
            disclaimer_version=DISCLAIMER_VERSION,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        try:
            session.add(acknowledgment)
            await session.commit()
            await session.refresh(acknowledgment)

            logger.info(
                "Disclaimer acknowledged",
                extra={
                    "session_id": data.session_id,
                    "ip_address": client_ip,
                    "version": DISCLAIMER_VERSION,
                },
            )

            return DisclaimerAcknowledgeResponse(
                success=True,
                acknowledged_at=acknowledgment.acknowledged_at,
                message="Disclaimer acknowledged successfully",
            )

        except IntegrityError:
            await session.rollback()
            # Race condition - already acknowledged
            result = await session.execute(
                select(DisclaimerAcknowledgment).where(
                    DisclaimerAcknowledgment.session_id == data.session_id
                )
            )
            existing = result.scalar_one()
            return DisclaimerAcknowledgeResponse(
                success=True,
                acknowledged_at=existing.acknowledged_at,
                message="Disclaimer was previously acknowledged",
            )


@router.post("/acknowledge-auth")
async def acknowledge_disclaimer_auth(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record disclaimer acknowledgment for an authenticated user.

    Story 15.5: Sets disclaimer_acknowledged=True on the user record.
    This is separate from the session-based acknowledgment used on the
    landing page (pre-auth).

    Args:
        current_user: The authenticated user from the session cookie
        db: Database session

    Returns:
        Success response
    """
    if current_user.disclaimer_acknowledged:
        return {"success": True, "message": "Disclaimer was previously acknowledged"}

    current_user.disclaimer_acknowledged = True
    await db.commit()
    await db.refresh(current_user)

    # Redact email: show first char + masked domain (e.g., j***@gmail.com)
    email = current_user.email or ""
    local, _, domain = email.partition("@")
    redacted_email = f"{local[0]}***@{domain}" if local and domain else "***"

    logger.info(
        "Authenticated disclaimer acknowledged",
        extra={"user_id": str(current_user.id), "email": redacted_email},
    )

    return {"success": True, "message": "Disclaimer acknowledged successfully"}


@router.get("/content")
async def get_disclaimer_content() -> dict[str, Any]:
    """Get the disclaimer content to display to users.

    Returns the structured disclaimer content that must be shown
    in the modal before users can proceed.
    """
    return {
        "version": DISCLAIMER_VERSION,
        "title": "Important Safety Information",
        "warnings": [
            {
                "icon": "flask",
                "title": "Experimental Software",
                "text": "This is experimental open-source software. It has not been validated for clinical use and may contain bugs or errors.",
            },
            {
                "icon": "brain",
                "title": "AI Limitations",
                "text": "AI can and will make mistakes. All suggestions should be verified with your healthcare provider before acting on them.",
            },
            {
                "icon": "shield-x",
                "title": "Not FDA Approved",
                "text": "This software is not FDA approved for medical use. It is not intended to diagnose, treat, cure, or prevent any disease.",
            },
            {
                "icon": "stethoscope",
                "title": "Consult Your Healthcare Provider",
                "text": "Always consult your healthcare provider before making any changes to your diabetes management regimen.",
            },
        ],
        "checkboxes": [
            {
                "id": "checkbox_experimental",
                "label": "I understand this is experimental software and that AI suggestions may be incorrect",
            },
            {
                "id": "checkbox_not_medical_advice",
                "label": "I understand this is not medical advice and I will consult my healthcare provider before making any changes",
            },
        ],
        "button_text": "I Understand & Accept",
    }
