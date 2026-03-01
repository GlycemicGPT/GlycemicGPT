"""Story 28.7: API key management endpoints.

All endpoints require JWT/cookie auth -- API keys cannot create or manage
other API keys.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser, is_api_key_auth
from src.database import get_db
from src.middleware.rate_limit import limiter
from src.services.api_key_service import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from src.services.audit_service import log_event

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(..., min_length=1, max_length=10)
    build_type: Literal["debug", "release"] = "release"
    expires_at: datetime | None = None


class CreateApiKeyResponse(BaseModel):
    id: str
    prefix: str
    name: str
    scopes: list[str]
    raw_key: str  # Only returned once at creation time


class ApiKeyListItem(BaseModel):
    id: str
    prefix: str
    name: str
    scopes: list[str]
    is_active: bool
    last_used_at: str | None = None
    expires_at: str | None = None
    created_at: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyListItem]


@router.post(
    "",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def create_api_key_endpoint(
    body: CreateApiKeyRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CreateApiKeyResponse:
    """Create a new API key. The raw key is returned only once."""
    # Reject if this request came via an API key (no scope escalation)
    if is_api_key_auth(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot create other API keys",
        )

    try:
        api_key, raw_key = await create_api_key(
            db=db,
            user_id=current_user.id,
            name=body.name,
            scopes=body.scopes,
            build_type=body.build_type,
            expires_at=body.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    ip = request.client.host if request.client else None
    await log_event(
        db,
        event_type="api_key.created",
        user_id=current_user.id,
        detail={"key_prefix": api_key.prefix, "scopes": body.scopes},
        ip_address=ip,
    )
    await db.commit()

    return CreateApiKeyResponse(
        id=str(api_key.id),
        prefix=api_key.prefix,
        name=api_key.name,
        scopes=[s for s in api_key.scopes.split(",") if s],
        raw_key=raw_key,
    )


@router.get("", response_model=ApiKeyListResponse)
@limiter.limit("30/minute")
async def list_api_keys_endpoint(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    """List all API keys for the current user (never includes raw key or hash)."""
    if is_api_key_auth(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot list other API keys",
        )
    keys = await list_api_keys(db, current_user.id)
    return ApiKeyListResponse(
        keys=[
            ApiKeyListItem(
                id=str(k.id),
                prefix=k.prefix,
                name=k.name,
                scopes=[s for s in k.scopes.split(",") if s],
                is_active=k.is_active,
                last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
                expires_at=k.expires_at.isoformat() if k.expires_at else None,
                created_at=k.created_at.isoformat(),
            )
            for k in keys
        ]
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def revoke_api_key_endpoint(
    key_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke (deactivate) an API key."""
    if is_api_key_auth(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot revoke other API keys",
        )
    revoked = await revoke_api_key(db, key_id, current_user.id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    ip = request.client.host if request.client else None
    await log_event(
        db,
        event_type="api_key.revoked",
        user_id=current_user.id,
        detail={"key_id": str(key_id)},
        ip_address=ip,
    )
    await db.commit()
