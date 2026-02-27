"""Story 5.1 / 14.2 / 28.9: AI provider configuration schemas.

Pydantic schemas for AI provider configuration endpoints.
Supports 5 provider types with conditional validation.
Story 28.9: SSRF prevention for base_url.
"""

import ipaddress
import socket
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from src.config import settings
from src.models.ai_provider import AIProviderStatus, AIProviderType

# Sentinel API key value for providers that don't require authentication
API_KEY_NOT_NEEDED = "not-needed"

# Provider types that require a base_url
# Note: subscription types no longer require base_url -- the sidecar handles routing
_BASE_URL_REQUIRED_TYPES = {
    AIProviderType.OPENAI_COMPATIBLE,
}

# Provider types that require a model_name
_MODEL_REQUIRED_TYPES = {
    AIProviderType.OPENAI_COMPATIBLE,
}

# Legacy provider types that should not be used for new configurations
_LEGACY_TYPES = {
    AIProviderType.CLAUDE,
    AIProviderType.OPENAI,
}

# Provider types that should NOT have a base_url (direct API only)
_DIRECT_API_TYPES = {
    AIProviderType.CLAUDE_API,
    AIProviderType.OPENAI_API,
}


# Cloud metadata endpoints -- always blocked regardless of settings
_CLOUD_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.internal",
}

# Cloud metadata IPs -- block hostnames that resolve to these
_CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to any private/reserved IP address.

    Checks ALL resolved addresses -- not just the first -- to prevent bypass
    via multi-homed DNS records.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
        )
    except ValueError:
        pass

    # It's a hostname, resolve and check ALL addresses
    try:
        resolved = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        if not resolved:
            return True  # Fail closed: unresolvable hosts blocked
        for entry in resolved:
            addr = ipaddress.ip_address(entry[4][0])
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            ):
                return True
        return False
    except (socket.gaierror, OSError):
        return True  # Fail closed: DNS errors block the request


def _validate_base_url(url: str) -> str:
    """Validate base_url to prevent SSRF (Story 28.9).

    Always blocks cloud metadata endpoints (169.254.169.254, etc.).
    When ALLOW_PRIVATE_AI_URLS is False, also blocks RFC 1918,
    loopback, and link-local addresses.

    Args:
        url: The base URL to validate.

    Returns:
        The validated URL.

    Raises:
        ValueError: If the URL is invalid or targets a blocked address.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https scheme")

    if not parsed.hostname:
        raise ValueError("base_url must contain a valid hostname")

    hostname = parsed.hostname.lower()

    # Always block cloud metadata endpoints (hostname check)
    if hostname in _CLOUD_METADATA_HOSTS:
        raise ValueError("base_url must not target cloud metadata services")

    # Always resolve DNS and block cloud metadata IPs (prevents bypass via aliases)
    try:
        resolved = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        for entry in resolved:
            addr = ipaddress.ip_address(entry[4][0])
            if addr in _CLOUD_METADATA_IPS:
                raise ValueError("base_url must not target cloud metadata services")
    except (socket.gaierror, OSError) as exc:
        raise ValueError("base_url hostname could not be resolved") from exc

    # Block private IPs when not allowed
    if not settings.allow_private_ai_urls and _is_private_ip(hostname):
        raise ValueError(
            "base_url must not target private network addresses "
            "(set ALLOW_PRIVATE_AI_URLS=true for homelab deployments)"
        )

    return url


class AIProviderConfigRequest(BaseModel):
    """Request schema for configuring an AI provider."""

    provider_type: AIProviderType = Field(..., description="AI provider type")
    api_key: str = Field(
        ...,
        min_length=1,
        description=(
            "API key for the selected provider "
            f"(use '{API_KEY_NOT_NEEDED}' for subscription proxies)"
        ),
    )
    model_name: str | None = Field(
        default=None,
        max_length=100,
        description="Model name override (required for openai_compatible)",
    )
    base_url: str | None = Field(
        default=None,
        max_length=500,
        description="Base URL for subscription proxies or self-hosted endpoints",
    )

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> "AIProviderConfigRequest":
        """Validate conditional requirements based on provider type."""
        # Reject legacy provider types for new configurations
        if self.provider_type in _LEGACY_TYPES:
            raise ValueError(
                f"'{self.provider_type.value}' is deprecated. "
                f"Use '{self.provider_type.value}_api' instead."
            )

        if self.provider_type in _BASE_URL_REQUIRED_TYPES and not self.base_url:
            raise ValueError(
                f"base_url is required for {self.provider_type.value} provider"
            )

        if self.provider_type in _MODEL_REQUIRED_TYPES and not self.model_name:
            raise ValueError(
                f"model_name is required for {self.provider_type.value} provider"
            )

        # Strip base_url for direct API types before validation (it would be ignored anyway)
        if self.provider_type in _DIRECT_API_TYPES:
            self.base_url = None

        # Validate base_url format when provided
        if self.base_url:
            _validate_base_url(self.base_url)

        return self


class AIProviderConfigResponse(BaseModel):
    """Response schema for AI provider configuration."""

    model_config = {"from_attributes": True}

    provider_type: AIProviderType
    status: AIProviderStatus
    model_name: str | None = None
    base_url: str | None = None
    sidecar_provider: str | None = None
    masked_api_key: str = Field(
        ...,
        description="Masked API key (last 4 chars) or 'sidecar-managed' for subscription types",
    )
    last_validated_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class AIProviderTestResponse(BaseModel):
    """Response schema for AI provider key test."""

    success: bool
    message: str


class AIProviderDeleteResponse(BaseModel):
    """Response schema for deleting AI provider configuration."""

    message: str = Field(default="AI provider configuration removed successfully")


class AIChatRequest(BaseModel):
    """Request schema for AI chat messages."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's question about their glucose data",
    )


class AIChatResponse(BaseModel):
    """Response schema for AI chat messages."""

    response: str = Field(..., description="AI-generated response text")
    disclaimer: str = Field(
        default="Not medical advice. Consult your healthcare provider.",
        description="Safety disclaimer",
    )


# ── Story 15.4: Subscription Configuration ──

# Subscription provider types that use the managed sidecar
_SUBSCRIPTION_TYPES = {
    AIProviderType.CLAUDE_SUBSCRIPTION,
    AIProviderType.CHATGPT_SUBSCRIPTION,
}

# Map sidecar provider names to AIProviderType
SIDECAR_PROVIDER_MAP: dict[str, AIProviderType] = {
    "claude": AIProviderType.CLAUDE_SUBSCRIPTION,
    "codex": AIProviderType.CHATGPT_SUBSCRIPTION,
}


class SubscriptionConfigureRequest(BaseModel):
    """Request schema for configuring a subscription provider via sidecar.

    Unlike AIProviderConfigRequest, this does not require api_key or base_url.
    The sidecar handles authentication and the API auto-populates the base_url.
    """

    sidecar_provider: str = Field(
        ..., description="Sidecar provider name: 'claude' or 'codex'"
    )
    model_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional model name override",
    )

    @model_validator(mode="after")
    def validate_provider(self) -> "SubscriptionConfigureRequest":
        if self.sidecar_provider not in SIDECAR_PROVIDER_MAP:
            raise ValueError(
                f"Invalid sidecar provider '{self.sidecar_provider}'. "
                f"Must be one of: {', '.join(sorted(SIDECAR_PROVIDER_MAP))}."
            )
        return self


# ── Story 15.2: Subscription Auth Schemas ──

VALID_SIDECAR_PROVIDERS = {"claude", "codex"}


class SubscriptionAuthStartRequest(BaseModel):
    """Request to start sidecar auth for a subscription provider."""

    provider: str = Field(..., description="Sidecar provider name: 'claude' or 'codex'")

    @model_validator(mode="after")
    def validate_provider(self) -> "SubscriptionAuthStartRequest":
        if self.provider not in VALID_SIDECAR_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'. Must be 'claude' or 'codex'."
            )
        return self


class SubscriptionAuthStartResponse(BaseModel):
    """Response with auth method info from the sidecar."""

    provider: str
    auth_method: str
    instructions: str


class SubscriptionAuthTokenRequest(BaseModel):
    """Request to submit a token to the sidecar."""

    provider: str = Field(..., description="Sidecar provider name: 'claude' or 'codex'")
    token: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="OAuth token obtained from CLI",
    )

    @model_validator(mode="after")
    def validate_provider(self) -> "SubscriptionAuthTokenRequest":
        if self.provider not in VALID_SIDECAR_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'. Must be 'claude' or 'codex'."
            )
        return self


class SubscriptionAuthTokenResponse(BaseModel):
    """Response after submitting a token."""

    success: bool
    provider: str
    error: str | None = None


class SubscriptionAuthRevokeRequest(BaseModel):
    """Request to revoke sidecar auth for a subscription provider."""

    provider: str = Field(..., description="Sidecar provider name: 'claude' or 'codex'")

    @model_validator(mode="after")
    def validate_provider(self) -> "SubscriptionAuthRevokeRequest":
        if self.provider not in VALID_SIDECAR_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{self.provider}'. Must be 'claude' or 'codex'."
            )
        return self


class SubscriptionAuthStatusResponse(BaseModel):
    """Current auth status from the sidecar."""

    sidecar_available: bool
    claude: dict | None = None
    codex: dict | None = None
