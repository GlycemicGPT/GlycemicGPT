"""Schemas for the cross-source CGM primary-source picker (Story 43.10)."""

from pydantic import BaseModel, Field


class CgmSourceItem(BaseModel):
    """One CGM-providing integration the user has configured."""

    source: str = Field(
        ..., description="glucose_readings.source string -- the stable key"
    )
    label: str = Field(..., description="Human-readable name for the picker")
    role: str = Field(..., description="primary | secondary | off")
    kind: str = Field(..., description="dexcom | nightscout")


class CgmSourcesResponse(BaseModel):
    """The user's CGM sources and which one drives the charts."""

    sources: list[CgmSourceItem]
    primary_source: str | None = Field(
        None, description="The source string currently marked primary, if any."
    )
    multiple_sources: bool = Field(
        ...,
        description=(
            "True when more than one CGM source exists -- the picker only "
            "needs to render in that case (a single source is always primary)."
        ),
    )


class CgmPrimaryUpdate(BaseModel):
    """Request body to switch the primary CGM source."""

    source: str = Field(
        ..., description="The glucose source string to promote to primary."
    )


class CgmPrimaryResponse(BaseModel):
    """The persisted primary CGM source after an update."""

    primary_source: str | None
