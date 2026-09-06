"""Schemas for the per-user web-session timeout preference.

The value is an absolute session lifetime in minutes, applied when the browser
session cookie is minted at login (see ``routers/auth.py``). Bounds come from
``Settings`` so a deployment can widen or narrow the allowed range without a
code change; the UI offers a preset ladder within these bounds.
"""

from pydantic import BaseModel, Field, field_validator

from src.config import settings

# Preset ladder surfaced by clients (minutes): 15m, 1h, 6h, 12h, 24h, 7d. This
# is advisory for the UI only -- the API accepts any value within the bounds.
SESSION_TIMEOUT_PRESET_MINUTES = [15, 60, 360, 720, 1440, 10080]


class SessionTimeoutResponse(BaseModel):
    """Current user's web-session timeout preference and the allowed range."""

    minutes: int = Field(
        ...,
        description="Absolute web-session lifetime in minutes, applied at next login",
    )
    min_minutes: int = Field(
        ...,
        description="Smallest session length the user may choose",
    )
    max_minutes: int = Field(
        ...,
        description="Largest session length the user may choose",
    )
    presets: list[int] = Field(
        ...,
        description="Suggested session-length presets (minutes) for the UI",
    )


class SessionTimeoutUpdate(BaseModel):
    """Request to update the current user's web-session timeout preference."""

    minutes: int = Field(
        ...,
        description="Absolute web-session lifetime in minutes, applied at next login",
    )

    @field_validator("minutes")
    @classmethod
    def _within_bounds(cls, value: int) -> int:
        low = settings.session_timeout_min_minutes
        high = settings.session_timeout_max_minutes
        if value < low or value > high:
            raise ValueError(
                f"session timeout must be between {low} and {high} minutes"
            )
        return value
