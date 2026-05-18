"""Integration schemas.

Pydantic schemas for third-party integration credentials.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from src.core.tandem_regions import SUPPORTED_TANDEM_COUNTRIES
from src.models.integration import IntegrationStatus, IntegrationType

_TANDEM_COUNTRY_PATTERN = "^(" + "|".join(sorted(SUPPORTED_TANDEM_COUNTRIES)) + ")$"


class DexcomCredentialsRequest(BaseModel):
    """Request schema for Dexcom Share credentials."""

    username: EmailStr = Field(..., description="Dexcom Share email address")
    password: str = Field(
        ...,
        min_length=1,
        description="Dexcom Share password",
    )
    region: str = Field(
        default="US",
        pattern="^(US|OUS|JP)$",
        description=(
            "Dexcom Share region: 'US' (United States), "
            "'OUS' (Outside US - EU, UK, Canada, Australia, etc.), "
            "or 'JP' (Japan & Asia-Pacific)."
        ),
    )


class TandemCredentialsRequest(BaseModel):
    """Request schema for Tandem t:connect credentials."""

    username: EmailStr = Field(..., description="Tandem t:connect email address")
    password: str = Field(
        ...,
        min_length=1,
        description="Tandem t:connect password",
    )
    country: str = Field(
        default="US",
        pattern=_TANDEM_COUNTRY_PATTERN,
        description=(
            "ISO-3166-1 alpha-2 country code (e.g. 'US', 'GB', 'DE', 'CA'). "
            "Used to route uploads to the correct Tandem cloud backend."
        ),
    )


class IntegrationResponse(BaseModel):
    """Response schema for integration status."""

    model_config = {"from_attributes": True}

    integration_type: IntegrationType
    status: IntegrationStatus
    last_sync_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    region: str | None = Field(
        default=None,
        description=(
            "Per-integration region/locale value stored on the credential. "
            "For Tandem: ISO-3166 alpha-2 country code (or legacy 'EU'). "
            "For Dexcom: pydexcom region ('US' | 'OUS' | 'JP')."
        ),
    )


class IntegrationConnectResponse(BaseModel):
    """Response schema for successful integration connection."""

    message: str = Field(..., description="Success message")
    integration: IntegrationResponse


class IntegrationListResponse(BaseModel):
    """Response schema for listing all integrations."""

    integrations: list[IntegrationResponse]


class IntegrationDisconnectResponse(BaseModel):
    """Response schema for disconnecting an integration."""

    message: str = Field(default="Integration disconnected successfully")
