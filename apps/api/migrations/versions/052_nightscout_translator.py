"""Translator schema: pump_events extensions + snapshot tables.

Lands the storage layer for the Nightscout translator:

- Adds PumpEventType enum values for events Nightscout can carry but
  the existing Tandem-shaped enum doesn't cover (carbs, overrides,
  profile switches, combo boluses, temp targets, notes, device events,
  APS-offline markers).
- Adds pump_events.metadata_json (JSONB) for type-specific extras
  that don't fit the Tandem-shaped columns (override correctionRange,
  profile switch tuple, AAPS pump composite dedup key, etc.).
- Adds pump_events.meal_event_id (UUID) for linking the two rows
  produced when a meal_bolus_pair is split into a bolus + carb_entry.
- Adds pump_events.ns_id (text) -- the Nightscout-server-assigned _id
  (or client-generated identifier/syncIdentifier) for per-connection
  dedupe when re-fetching the same record across sync cycles.
- Creates nightscout_profile_snapshots: read-only mirror of the user's
  Nightscout profile, written on each profile fetch. Read by the
  onboarding wizard to pre-fill the user's canonical settings form;
  never queried by AI / charts / mobile / alerts.
- Creates device_status_snapshots: periodic IOB / COB / predBGs / loop
  dosing decision snapshots. Translator writes one row per devicestatus
  fetch; downstream consumers (AI chat, advanced web views) read recent
  rows for closed-loop analysis context.

**Operational notes:**

- The PumpEventType enum extension uses `op.execute("COMMIT")` followed
  by `ALTER TYPE ... ADD VALUE IF NOT EXISTS` -- this is the required
  PostgreSQL pattern (enum-value adds can't run inside a transaction)
  and mirrors migration 036. If the migration errors out *after* the
  COMMIT but before later DDL completes, the new enum values persist
  on re-run; the rest of the schema is recreated fresh thanks to
  `IF NOT EXISTS` guards. Rollback cannot remove the new enum values.

- Downgrade restores the non-partial `ix_pump_events_user_event_unique`
  index. If Nightscout-sourced rows already exist with duplicate
  `(user_id, event_timestamp, event_type)` values (the partial-index
  shape this migration introduces tolerates these), the
  `op.create_index` call in `downgrade()` will fail with a uniqueness
  violation. Ops should clean up Nightscout-sourced duplicates (or
  delete all `pump_events` rows where `source LIKE 'nightscout:%'`)
  before downgrading.

Revision ID: 052_nightscout_translator
Revises: 051_nightscout_connections
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "052_nightscout_translator"
down_revision = "051_nightscout_connections"
branch_labels = None
depends_on = None


# New PumpEventType enum values added by this migration. Order matches
# the additions in src/models/pump_data.py.
_NEW_PUMP_EVENT_TYPES = (
    "carbs",
    "override",
    "profile_switch",
    "combo_bolus",
    "temp_target",
    "note",
    "device_event",
    "aps_offline",
)


def upgrade() -> None:
    # --- 1. Extend the pumpeventtype enum --------------------------------
    # ALTER TYPE ... ADD VALUE must run outside a transaction; mirror the
    # pattern from migration 036.
    op.execute("COMMIT")
    for value in _NEW_PUMP_EVENT_TYPES:
        op.execute(f"ALTER TYPE pumpeventtype ADD VALUE IF NOT EXISTS '{value}'")

    # --- 2. pump_events extensions ---------------------------------------
    op.add_column(
        "pump_events",
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "pump_events",
        sa.Column(
            "meal_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "pump_events",
        sa.Column("ns_id", sa.Text(), nullable=True),
    )
    # Dedupe index for Nightscout-sourced events. Per-connection
    # uniqueness on (source, ns_id). NULL ns_id (direct integrations)
    # doesn't participate -- partial index gates on ns_id IS NOT NULL.
    op.create_index(
        "ix_pump_events_source_nsid",
        "pump_events",
        ["source", "ns_id"],
        unique=True,
        postgresql_where=sa.text("ns_id IS NOT NULL"),
    )
    # Relax the existing (user_id, event_timestamp, event_type) unique
    # index to NOT apply to Nightscout-sourced rows -- otherwise, two
    # legitimate but distinct events at the same timestamp (e.g. two
    # AAPS SMBs in the same second with different `_id`s, or a real
    # bolus that happens to share a timestamp with a Loop SMB) would
    # collide and silently drop one. Direct integrations (Tandem,
    # Dexcom) keep the natural-key dedupe by being on the WHERE
    # ns_id IS NULL branch; Nightscout-sourced rows dedupe via the
    # `ix_pump_events_source_nsid` partial index above.
    op.drop_index(
        "ix_pump_events_user_event_unique", table_name="pump_events"
    )
    op.create_index(
        "ix_pump_events_user_event_unique",
        "pump_events",
        ["user_id", "event_timestamp", "event_type"],
        unique=True,
        postgresql_where=sa.text("ns_id IS NULL"),
    )
    # Index for the meal-bolus-pair sibling lookup ("find the carb_entry
    # row paired with this bolus row").
    op.create_index(
        "ix_pump_events_meal_event_id",
        "pump_events",
        ["meal_event_id"],
        postgresql_where=sa.text("meal_event_id IS NOT NULL"),
    )

    # --- 3. glucose_readings: ns_id for per-connection dedupe ------------
    # Same rationale as pump_events: the unique index on
    # (user_id, reading_timestamp) handles cross-source conflicts via
    # ON CONFLICT DO NOTHING (direct integrations win by being inserted
    # first), but per-connection dedupe needs an explicit ns_id key.
    op.add_column(
        "glucose_readings",
        sa.Column("ns_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_glucose_readings_source_nsid",
        "glucose_readings",
        ["source", "ns_id"],
        unique=True,
        postgresql_where=sa.text("ns_id IS NOT NULL"),
    )

    # --- 4. nightscout_profile_snapshots ---------------------------------
    op.create_table(
        "nightscout_profile_snapshots",
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
        ),
        sa.Column(
            "nightscout_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nightscout_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Source metadata (from Nightscout's profile document)
        sa.Column("source_default_profile_name", sa.String(120), nullable=True),
        sa.Column("source_units", sa.String(40), nullable=True),
        sa.Column("source_timezone", sa.String(60), nullable=True),
        sa.Column("source_dia_hours", sa.Float(), nullable=True),
        # Time-segmented schedules. Each is a list of {"time": "HH:MM",
        # "value": <number>, "timeAsSeconds": <int>} -- preserved
        # verbatim from Nightscout's wire format. Per synthesis §7.4,
        # NS profile entries are (time, value) pairs; duration to next
        # entry is implicit (computed downstream by the wizard).
        sa.Column("basal_segments", postgresql.JSONB(), nullable=True),
        sa.Column("carb_ratio_segments", postgresql.JSONB(), nullable=True),
        sa.Column("sensitivity_segments", postgresql.JSONB(), nullable=True),
        sa.Column("target_low_segments", postgresql.JSONB(), nullable=True),
        sa.Column("target_high_segments", postgresql.JSONB(), nullable=True),
        # Raw blob for re-parsing if the wizard needs additional fields
        # we didn't break out into columns.
        sa.Column("profile_json_full", postgresql.JSONB(), nullable=True),
        # The Nightscout-side `startDate` (when the profile became
        # active per Nightscout's clock). Different from `fetched_at`
        # which is when our translator wrote the snapshot row.
        sa.Column("source_start_date", sa.DateTime(timezone=True), nullable=True),
    )
    # One latest snapshot per (user, connection). Re-fetch upserts.
    op.create_index(
        "ix_nsps_user_connection",
        "nightscout_profile_snapshots",
        ["user_id", "nightscout_connection_id"],
        unique=True,
    )

    # --- 5. device_status_snapshots --------------------------------------
    op.create_table(
        "device_status_snapshots",
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
        ),
        sa.Column(
            "nightscout_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nightscout_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Source attribution
        sa.Column("source_uploader", sa.String(40), nullable=True),
        sa.Column("source_device", sa.String(200), nullable=True),
        sa.Column("ns_id", sa.Text(), nullable=False),
        # Extracted scalars (frequently queried)
        sa.Column("iob_units", sa.Float(), nullable=True),
        sa.Column("cob_grams", sa.Float(), nullable=True),
        sa.Column("pump_battery_percent", sa.Integer(), nullable=True),
        sa.Column("pump_reservoir_units", sa.Float(), nullable=True),
        sa.Column("pump_suspended", sa.Boolean(), nullable=True),
        sa.Column("loop_failure_reason", sa.Text(), nullable=True),
        # Verbatim subtree blobs. Translator preserves them rather than
        # parsing further; downstream AI/analytics layers do the work.
        # Per synthesis §7.3: never modify, never parse the `reason`
        # string here, never strip predBGs.
        sa.Column("loop_subtree_json", postgresql.JSONB(), nullable=True),
        sa.Column("openaps_subtree_json", postgresql.JSONB(), nullable=True),
        sa.Column("pump_subtree_json", postgresql.JSONB(), nullable=True),
        sa.Column("uploader_subtree_json", postgresql.JSONB(), nullable=True),
    )
    # Per-connection dedupe by Nightscout-assigned ns_id.
    op.create_index(
        "ix_devicestatus_connection_nsid",
        "device_status_snapshots",
        ["nightscout_connection_id", "ns_id"],
        unique=True,
    )
    # Time-window query index: "give me the latest IOB for this user"
    # / "snapshots in the last 30 min".
    op.create_index(
        "ix_devicestatus_user_timestamp",
        "device_status_snapshots",
        ["user_id", "snapshot_timestamp"],
    )


def downgrade() -> None:
    # device_status_snapshots
    op.drop_index(
        "ix_devicestatus_user_timestamp",
        table_name="device_status_snapshots",
    )
    op.drop_index(
        "ix_devicestatus_connection_nsid",
        table_name="device_status_snapshots",
    )
    op.drop_table("device_status_snapshots")

    # nightscout_profile_snapshots
    op.drop_index(
        "ix_nsps_user_connection",
        table_name="nightscout_profile_snapshots",
    )
    op.drop_table("nightscout_profile_snapshots")

    # glucose_readings rollbacks
    op.drop_index(
        "ix_glucose_readings_source_nsid",
        table_name="glucose_readings",
    )
    op.drop_column("glucose_readings", "ns_id")

    # pump_events rollbacks
    op.drop_index(
        "ix_pump_events_meal_event_id",
        table_name="pump_events",
    )
    op.drop_index(
        "ix_pump_events_source_nsid",
        table_name="pump_events",
    )
    # Restore the original (un-partial) unique index. Drop the partial
    # one first since they share a name.
    op.drop_index(
        "ix_pump_events_user_event_unique", table_name="pump_events"
    )
    op.create_index(
        "ix_pump_events_user_event_unique",
        "pump_events",
        ["user_id", "event_timestamp", "event_type"],
        unique=True,
    )
    op.drop_column("pump_events", "ns_id")
    op.drop_column("pump_events", "meal_event_id")
    op.drop_column("pump_events", "metadata_json")

    # PumpEventType enum values cannot be removed without recreating
    # the type. Leave them in place; they're harmless when unused.
