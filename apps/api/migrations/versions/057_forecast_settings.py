"""Forecast settings (Story 43.12 PR 3).

Adds `forecast_settings` -- a per-user single-row preference table for
the forecast-overlay picker. The default `'auto'` means "pick the only
available source" (per design doc Section 3); `'none'` opts out;
specific engine values pin the picker to that source.

Why a new table (not a column on `users` and not folded into
`analytics_config`):

- Matches the existing per-domain config pattern (`analytics_config`,
  `data_retention_config`, `escalation_config`, `safety_limits`,
  `insulin_config`). Each owns its concern; cross-domain coupling
  stays out of the schema.
- Story 43.10's primary-CGM picker (queued, not shipped) will likely
  grow alongside this -- room to add a `primary_cgm` column without
  another migration.
- Future power-user toggles ("show all AAPS curves", "horizon cap")
  fit here naturally.

`source_engine` allow-list mirrors PR 1's CHECK on
`forecast_snapshots.source_engine` exactly so the picker can't store
a value the schema can't otherwise produce, plus `'auto'` and
`'none'` for the picker-only states.

Revision ID: 057_forecast_settings
Revises: 056_reset_disclaimer_for_v1_1
Create Date: 2026-05-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "057_forecast_settings"
down_revision = "056_reset_disclaimer_for_v1_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # 'auto' | 'none' | 'loop' | 'aaps' | 'trio' | 'oref0' | 'iaps' |
        # 'glycemicgpt'. Free-form text bounded by a CHECK so the picker
        # can't store a value the API doesn't understand. Matches
        # `forecast_snapshots.source_engine`'s allow-list plus the two
        # picker-only states.
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.CheckConstraint(
            "source IN ('auto','none','loop','aaps','trio','oref0','iaps','glycemicgpt')",
            name="ck_forecast_settings_source_known",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # One-to-one with users: enforced by UNIQUE on user_id. The
    # `get_or_create` service layer relies on this -- racing inserts
    # land cleanly via ON CONFLICT.
    op.create_index(
        "ix_forecast_settings_user",
        "forecast_settings",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_settings_user", table_name="forecast_settings")
    op.drop_table("forecast_settings")
