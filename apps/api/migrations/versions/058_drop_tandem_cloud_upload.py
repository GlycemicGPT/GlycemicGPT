"""Drop Tandem cloud upload tables.

PR1c removes the Tandem cloud-upload feature entirely. The three tables
below existed only to support that direction (push events from GlycemicGPT
back to Tandem's t:connect cloud):

- ``tandem_upload_state``  -- per-user enable/interval/last-status + cached
   Tandem OAuth tokens. Only the now-deleted upload service read from or
   wrote to it.
- ``pump_raw_events``      -- raw BLE history-log bytes captured by the
   mobile client. Only the upload service consumed them. The mobile-push
   endpoint (`/api/integrations/pump/push`) still accepts the ``raw_events``
   array for back-compat with older mobile builds but no longer persists
   them.
- ``pump_hardware_info``   -- pump model/serial/feature flags. Only the
   upload service used these for the device-identification fields it sent
   to Tandem. The research-source-suggestions code that briefly used it as
   a "user has a Tandem pump?" signal has been pointed at
   ``integration_credentials`` instead.

We did not implement the upload feature responsibly enough to ship into
a clinical system (endocrinologist-facing t:connect portal) -- see the
deprecation note in ``docs/daily-use/connecting-tandem-cloud.md`` and the
CHANGELOG entry.

The downgrade re-creates the bare tables (no data restoration; the rows
themselves are gone). It is intended only for emergency rollback during
the deployment window; ongoing development should treat the upload
feature as permanently removed.

Revision ID: 058_drop_tandem_cloud_upload
Revises: 057_forecast_settings
Create Date: 2026-05-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "058_drop_tandem_cloud_upload"
down_revision: str | None = "057_forecast_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All three tables only ever held data for the upload feature, so we
    # drop them outright. Postgres drops dependent indexes automatically
    # when the parent table is dropped; no explicit ``drop_index`` is
    # needed.  Order: alphabetical (no inter-table FKs today, but if any
    # are added later a strict dependency-order drop will be required).
    op.drop_table("pump_hardware_info")
    op.drop_table("pump_raw_events")
    op.drop_table("tandem_upload_state")


def downgrade() -> None:
    # Re-create the tables with the schema produced by the original
    # ``032_add_tandem_cloud_upload`` plus the ``034_add_tandem_pumper_id``
    # column-append. NOTE: this restores only the table shape, not the
    # data. Cached OAuth tokens, pending raw events, and pump-hardware info
    # are lost permanently. Indexes/uniqueness constraints are recreated to
    # match the original schema so an emergency rollback to revision 057
    # leaves the database in a state byte-identical to the historical 032+034
    # state, modulo row contents.
    op.create_table(
        "tandem_upload_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "upload_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column("last_upload_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_upload_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "max_event_index_uploaded",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("tandem_access_token", sa.Text(), nullable=True),
        sa.Column("tandem_refresh_token", sa.Text(), nullable=True),
        sa.Column("tandem_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # ``tandem_pumper_id`` was appended last by revision 034. Keep that
        # ordinal position so ``pg_dump`` after a rollback matches what an
        # untouched 057-state database would look like.
        sa.Column("tandem_pumper_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_tandem_upload_state_user_id",
        "tandem_upload_state",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "pump_raw_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("raw_bytes_b64", sa.Text(), nullable=False),
        sa.Column("event_type_id", sa.Integer(), nullable=False),
        sa.Column("pump_time_seconds", sa.BigInteger(), nullable=False),
        sa.Column(
            "uploaded_to_tandem",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "sequence_number", name="uq_pump_raw_event_user_seq"
        ),
    )
    op.create_index("ix_pump_raw_events_user_id", "pump_raw_events", ["user_id"])
    # Composite index from 032 that backed the "pending uploads for user"
    # query. Restoring it on downgrade preserves the original query plan.
    op.create_index(
        "ix_pump_raw_events_user_uploaded",
        "pump_raw_events",
        ["user_id", "uploaded_to_tandem"],
    )

    op.create_table(
        "pump_hardware_info",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("serial_number", sa.BigInteger(), nullable=False),
        sa.Column("model_number", sa.BigInteger(), nullable=False),
        sa.Column("part_number", sa.BigInteger(), nullable=False),
        sa.Column("pump_rev", sa.String(50), nullable=False),
        sa.Column("arm_sw_ver", sa.BigInteger(), nullable=False),
        sa.Column("msp_sw_ver", sa.BigInteger(), nullable=False),
        sa.Column("config_a_bits", sa.BigInteger(), nullable=False),
        sa.Column("config_b_bits", sa.BigInteger(), nullable=False),
        sa.Column("pcba_sn", sa.BigInteger(), nullable=False),
        sa.Column("pcba_rev", sa.String(50), nullable=False),
        sa.Column(
            "pump_features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Unique index from 032. The column-level ``unique=True`` above already
    # creates an implicit unique index, but 032 also created an explicit
    # named one (``ix_pump_hardware_info_user_id``) -- recreate it so the
    # post-rollback schema matches the historical 032+034 state.
    op.create_index(
        "ix_pump_hardware_info_user_id",
        "pump_hardware_info",
        ["user_id"],
        unique=True,
    )
