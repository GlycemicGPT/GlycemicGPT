"""Plugin declaration schemas.

Validates mobile-pushed plugin metadata and category mappings.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from src.schemas.analytics_config import VALID_CATEGORY_KEYS

_PLUGIN_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_PLUGIN_NAME_RE = re.compile(r"^[\w\s.()-]+$")
_PLUGIN_VERSION_RE = re.compile(r"^[a-zA-Z0-9.+-]+$")
_CATEGORY_KEY_RE = re.compile(r"^[A-Z0-9_]+$")


class PluginDeclarationCreate(BaseModel):
    """Request schema for upserting a plugin declaration."""

    model_config = {"extra": "forbid"}

    plugin_id: str = Field(
        ...,
        max_length=128,
        description="Unique identifier for the pump plugin (e.g. 'com.tandem.pump').",
    )
    plugin_name: str = Field(
        ...,
        max_length=64,
        description="Human-readable plugin name (e.g. 'Tandem Insulin Pump').",
    )
    plugin_version: str = Field(
        ...,
        max_length=32,
        description="Plugin version string (e.g. '1.0.0').",
    )
    declared_categories: list[str] = Field(
        ...,
        min_length=1,
        description="Pump-native category names declared by the plugin.",
    )
    category_mappings: dict[str, str] = Field(
        ...,
        description="Maps pump-native category -> platform category key.",
    )

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, v: str) -> str:
        if not _PLUGIN_ID_RE.match(v):
            raise ValueError(f"plugin_id must match ^[a-zA-Z0-9._-]+$ (got: {v!r})")
        return v

    @field_validator("plugin_name")
    @classmethod
    def validate_plugin_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plugin_name must not be blank.")
        if not _PLUGIN_NAME_RE.match(v):
            raise ValueError(
                f"plugin_name must contain only word characters, spaces, "
                f"periods, hyphens, or parentheses (got: {v!r})."
            )
        return v

    @field_validator("plugin_version")
    @classmethod
    def validate_plugin_version(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("plugin_version must not be blank.")
        if not _PLUGIN_VERSION_RE.match(v):
            raise ValueError(
                f"plugin_version must match ^[a-zA-Z0-9.+-]+$ (got: {v!r})."
            )
        return v

    @field_validator("declared_categories")
    @classmethod
    def validate_declared_categories(cls, v: list[str]) -> list[str]:
        for cat in v:
            if not isinstance(cat, str) or len(cat) > 32:
                raise ValueError(
                    f"Each declared category must be a string of at most 32 chars (got: {cat!r})."
                )
            if not _CATEGORY_KEY_RE.match(cat):
                raise ValueError(
                    f"Declared category must match ^[A-Z0-9_]+$ (got: {cat!r})."
                )
        if len(v) != len(set(v)):
            raise ValueError("declared_categories must be unique.")
        return v

    @field_validator("category_mappings")
    @classmethod
    def validate_category_mappings(cls, v: dict[str, str]) -> dict[str, str]:
        invalid_values = {val for val in v.values() if val not in VALID_CATEGORY_KEYS}
        if invalid_values:
            raise ValueError(
                f"Mapping values must be valid platform categories. "
                f"Invalid: {sorted(invalid_values)}. "
                f"Valid: {sorted(VALID_CATEGORY_KEYS)}"
            )
        return v

    @model_validator(mode="after")
    def validate_mapping_keys_subset_of_declared(self) -> "PluginDeclarationCreate":
        """Mapping keys must be a subset of declared_categories."""
        declared_set = set(self.declared_categories)
        extra_keys = set(self.category_mappings.keys()) - declared_set
        if extra_keys:
            raise ValueError(
                f"category_mappings keys must be a subset of declared_categories. "
                f"Extra keys: {sorted(extra_keys)}"
            )
        return self


class PluginDeclarationResponse(BaseModel):
    """Response schema for a plugin declaration."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    plugin_id: str
    plugin_name: str
    plugin_version: str
    declared_categories: list[str]
    category_mappings: dict[str, str]
    updated_at: datetime
