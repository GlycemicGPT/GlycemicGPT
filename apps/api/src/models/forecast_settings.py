"""Forecast picker preference (Story 43.12 PR 3).

Stores the user's choice of which closed-loop forecast source to draw
on the dashboard chart and feed to the AI context (PR 5). One row per
user; defaults to `'auto'` so the picker is opt-in to a specific
source.

`source` semantics:

| Value | Meaning |
|---|---|
| `'auto'` | Pick the only source publishing forecasts; if multiple, render nothing until user picks (per design doc Section 3) |
| `'none'` | Opt out -- never render a forecast overlay |
| `'loop'` / `'aaps'` / `'trio'` / `'oref0'` / `'iaps'` | Pin to that engine; render nothing if that engine has gone silent |
| `'glycemicgpt'` | Future GlycemicGPT prediction engine (not shipped); schema-ready |

The CHECK constraint mirrors PR 1's `forecast_snapshots.source_engine`
allow-list plus the two picker-only states (`'auto'`, `'none'`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class ForecastSettings(Base, TimestampMixin):
    """User's forecast-picker preference. One-to-one with `User`."""

    __tablename__ = "forecast_settings"

    __table_args__ = (
        # Mirror of migration CHECK. Keeping it on the ORM means
        # `alembic --autogenerate` stays quiet and the invariant lives
        # next to the column.
        CheckConstraint(
            "source IN ('auto','none','loop','aaps','trio','oref0','iaps','glycemicgpt')",
            name="ck_forecast_settings_source_known",
        ),
        Index("ix_forecast_settings_user", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # See module docstring for semantics. Default `'auto'` so a new
    # user with a single forecast-publishing integration sees the
    # overlay immediately (single-source case), and a user with
    # multiple sources gets a clean prompt-to-pick state.
    # `server_default` must be a SQL expression -- a plain string
    # becomes `DEFAULT auto` (unquoted identifier) which is invalid.
    # Use `text("'auto'")` to match the migration's `sa.text("'auto'")`
    # so `alembic --autogenerate` doesn't suggest spurious diffs.
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="auto",
        server_default=text("'auto'"),
    )

    def __repr__(self) -> str:
        return f"<ForecastSettings(user_id={self.user_id}, source={self.source!r})>"
