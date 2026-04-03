"""Device registration API.

Allows mobile apps to register/unregister for alert delivery,
with device fingerprinting and per-user limits.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser, ScopeChecker
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.services.audit_service import log_event
from src.services.device_service import (
    get_devices_for_user,
    register_device,
    unregister_device,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


class DeviceRegistrationRequest(BaseModel):
    """Request to register a device."""

    device_token: str = Field(..., min_length=1, max_length=255)
    device_name: str = Field(..., min_length=1, max_length=255)
    platform: Literal["android", "ios", "wear"] = "android"
    device_fingerprint: str | None = Field(default=None, min_length=1, max_length=64)
    app_version: str | None = Field(default=None, max_length=50)
    build_type: Literal["debug", "release"] | None = None


class DeviceRegistrationResponse(BaseModel):
    """Response after device registration."""

    id: str
    device_token: str


class DeviceListItem(BaseModel):
    """Single device in a list response."""

    id: str
    device_name: str
    platform: str
    app_version: str | None = None
    build_type: str | None = None
    last_seen_at: str


class DeviceListResponse(BaseModel):
    """List of registered devices."""

    devices: list[DeviceListItem]


@router.get("", response_model=DeviceListResponse)
@limiter.limit("30/minute")
async def list_devices_endpoint(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    _scope: bool = Depends(ScopeChecker(["read:profile"])),
) -> DeviceListResponse:
    """List all devices registered to the current user."""
    devices = await get_devices_for_user(db, current_user.id)
    return DeviceListResponse(
        devices=[
            DeviceListItem(
                id=str(d.id),
                device_name=d.device_name,
                platform=d.platform,
                app_version=d.app_version,
                build_type=d.build_type,
                last_seen_at=d.last_seen_at.isoformat(),
            )
            for d in devices
        ]
    )


@router.post(
    "/register",
    response_model=DeviceRegistrationResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def register_device_endpoint(
    body: DeviceRegistrationRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    _scope: bool = Depends(ScopeChecker(["write:device"])),
) -> DeviceRegistrationResponse:
    """Register a mobile device for alert delivery."""
    try:
        device = await register_device(
            db=db,
            user_id=current_user.id,
            device_token=body.device_token,
            device_name=body.device_name,
            platform=body.platform,
            device_fingerprint=body.device_fingerprint,
            app_version=body.app_version,
            build_type=body.build_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    ip = request.client.host if request.client else None
    await log_event(
        db,
        event_type="device.registered",
        user_id=current_user.id,
        detail={
            "device_name": body.device_name,
            "platform": body.platform,
            "build_type": body.build_type,
        },
        ip_address=ip,
    )
    await db.commit()

    return DeviceRegistrationResponse(
        id=str(device.id),
        device_token=device.device_token,
    )


@router.delete(
    "/{device_token}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unregister_device_endpoint(
    device_token: str,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    _scope: bool = Depends(ScopeChecker(["write:device"])),
) -> None:
    """Unregister a device (e.g., on logout). Only the device owner can unregister."""
    removed = await unregister_device(
        db=db,
        device_token=device_token,
        user_id=current_user.id,
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    ip = request.client.host if request.client else None
    await log_event(
        db,
        event_type="device.unregistered",
        user_id=current_user.id,
        detail={"device_token_prefix": device_token[:8]},
        ip_address=ip,
    )
    await db.commit()
